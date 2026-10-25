import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
from google import genai
from google.genai import errors, types

from .config import GEMMA_ATTEMPTS
from .frames import Frame
from .options import Options
from .prompts import VERIFY_SYSTEM, speech_system, transcript_block, visual_system

log = logging.getLogger(__name__)

_client: genai.Client | None = None


def client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client()  # reads GEMINI_API_KEY
    return _client


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise


def _frame_parts(frames: list[Frame]) -> list:
    parts: list = []
    for f in frames:
        parts.append(f"Frame at {f.time:.1f}s:")
        parts.append(types.Part.from_bytes(data=f.jpeg, mime_type="image/jpeg"))
    return parts


def _as_obj(data, list_key: str) -> dict:
    """Smaller models sometimes return a bare list instead of the requested object; sort items by their fields."""
    if isinstance(data, dict):
        return data
    if not isinstance(data, list):
        return {}
    out: dict[str, list] = {}
    for d in data:
        if not isinstance(d, dict):
            continue
        wrapped = {k: v for k, v in d.items() if isinstance(v, list)}
        if wrapped and any(k in d for k in ("bias_flags", "claims", "disclaimers", "verdicts")):
            for k, v in wrapped.items():
                out.setdefault(k, []).extend(v)
            continue
        if "claim_type" in d or "needs_disclaimer" in d:
            key = "claims"
        elif "box_2d" in d or "line_count" in d:
            key = "disclaimers"
        elif "category" in d:
            key = "bias_flags"
        else:
            key = list_key
        out.setdefault(key, []).append(d)
    return out


def _generate(system: str, parts: list, opts: Options) -> tuple[dict, str]:
    """Returns (parsed JSON, model that answered). Retries 5xx and bad JSON, then falls back to a second model."""
    profile = opts.profile
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        temperature=0.2,
        thinking_config=types.ThinkingConfig(thinking_level=profile["thinking"]),
    )
    models = [profile["model"]]
    if profile["fallback"] and profile["fallback"] != profile["model"]:
        models.append(profile["fallback"])
    last_exc: Exception | None = None
    for model in models:
        for attempt in range(GEMMA_ATTEMPTS):
            try:
                resp = client().models.generate_content(model=model, contents=parts, config=config)
                return _parse_json(resp.text), model
            except (errors.ServerError, json.JSONDecodeError, httpx.TransportError, OSError) as exc:
                last_exc = exc
            log.warning("%s attempt %d failed: %s", model, attempt + 1, str(last_exc)[:120])
            time.sleep(1.0 * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def _script_part(opts: Options) -> list:
    if not opts.script:
        return []
    return ["SCRIPT PROVIDED BY THE USER (may include lines the transcript missed):\n" + opts.script]


def _chunks(frames: list[Frame], size: int) -> list[list[Frame]]:
    if len(frames) <= size:
        return [frames]
    n = -(-len(frames) // size)
    step = -(-len(frames) // n)
    # One frame of overlap so a scene that crosses a boundary is seen in context by both batches.
    return [frames[max(0, i - 1) : i + step] for i in range(0, len(frames), step)]


def _visual_batch(frames: list[Frame], opts: Options) -> dict:
    parts = _frame_parts(frames) + ["Review these frames now and return the JSON object."]
    data, model = _generate(visual_system(opts.check_bias, opts.check_claims), parts, opts)
    data = _as_obj(data, "disclaimers" if not opts.check_bias else "bias_flags")
    return {
        "bias_flags": data.get("bias_flags") or [],
        "claims": data.get("claims") or [],
        "disclaimers": data.get("disclaimers") or [],
        "model": model,
    }


def visual(frames: list[Frame], opts: Options) -> dict:
    """Frames only, so it can start before transcription finishes. Long ads are split into parallel batches."""
    batches = _chunks(frames, opts.profile["batch_frames"])
    with ThreadPoolExecutor(max_workers=len(batches)) as pool:
        results = list(pool.map(lambda b: _visual_batch(b, opts), batches))
    seen_disclaimer_times: set[tuple[float, str]] = set()
    disclaimers = []
    for r in results:
        for d in r["disclaimers"]:
            key = (round(float(d.get("time") or 0), 1), str(d.get("text") or "")[:40].lower())
            if key not in seen_disclaimer_times:
                seen_disclaimer_times.add(key)
                disclaimers.append(d)
    return {
        "bias_flags": [b for r in results for b in r["bias_flags"]],
        "claims": [c for r in results for c in r["claims"]],
        "disclaimers": disclaimers,
        "model": results[0]["model"],
        "batches": len(batches),
    }


def speech(transcript: dict, opts: Options) -> dict:
    """Text only, which is far cheaper and faster than a call with images."""
    parts = [transcript_block(transcript), *_script_part(opts), "Review this transcript now and return the JSON object."]
    data, model = _generate(speech_system(opts.check_bias, opts.check_claims), parts, opts)
    data = _as_obj(data, "claims" if not opts.check_bias else "bias_flags")
    return {"bias_flags": data.get("bias_flags") or [], "claims": data.get("claims") or [], "model": model}


def verify_bias(flags: list[dict], frames: list[Frame], transcript: dict, interval: float, opts: Options) -> list[dict]:
    if not flags:
        return []
    pad = interval * 2
    wanted: dict[int, Frame] = {}
    for fl in flags:
        start = float(fl.get("start", 0)) - pad
        end = float(fl.get("end", fl.get("start", 0))) + pad
        for f in frames:
            if start <= f.time <= end:
                wanted[f.index] = f
    context = sorted(wanted.values(), key=lambda f: f.time)

    candidates = [
        {"id": i, **{k: fl.get(k) for k in ("start", "end", "category", "source", "evidence", "why")}}
        for i, fl in enumerate(flags)
    ]
    parts = _frame_parts(context)
    parts.append(transcript_block(transcript))
    parts.append("CANDIDATE FLAGS:\n" + json.dumps(candidates, ensure_ascii=False, indent=1))

    try:
        data = _as_obj(_generate(VERIFY_SYSTEM, parts, opts)[0], "verdicts")
        verdicts = {v.get("id"): v for v in data.get("verdicts", []) if isinstance(v, dict)}
    except Exception as exc:
        log.warning("Verification pass failed, keeping unverified flags: %s", exc)
        return [{**fl, "verified": False} for fl in flags]

    kept = []
    for i, fl in enumerate(flags):
        v = verdicts.get(i)
        if v is None or v.get("keep"):
            kept.append({**fl, "verified": v is not None, "verify_reason": (v or {}).get("reason")})
    return kept
