import json
import logging
import re

from google import genai
from google.genai import types

from .config import GEMMA_MODEL, GEMMA_THINKING
from .frames import Frame
from .prompts import ANALYZE_SYSTEM, VERIFY_SYSTEM, transcript_block

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
        parts.append(types.Part.from_bytes(data=f.jpeg, mime_type="image/jpeg"))
        parts.append(f"Frame at {f.time:.1f}s")
    return parts


def _generate(system: str, parts: list) -> dict:
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        temperature=0.2,
        thinking_config=types.ThinkingConfig(thinking_level=GEMMA_THINKING),
    )
    resp = client().models.generate_content(model=GEMMA_MODEL, contents=parts, config=config)
    return _parse_json(resp.text)


def analyze(frames: list[Frame], transcript: dict, script: str | None) -> dict:
    parts = _frame_parts(frames)
    parts.append(transcript_block(transcript))
    if script:
        parts.append("SCRIPT PROVIDED BY THE USER (may include lines the transcript missed):\n" + script)
    parts.append("Review this ad now and return the JSON object.")
    data = _generate(ANALYZE_SYSTEM, parts)
    return {
        "bias_flags": data.get("bias_flags") or [],
        "claims": data.get("claims") or [],
        "disclaimers": data.get("disclaimers") or [],
    }


def verify_bias(flags: list[dict], frames: list[Frame], transcript: dict, interval: float) -> list[dict]:
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
    context = sorted(wanted.values(), key=lambda f: f.time) or frames

    candidates = [
        {"id": i, **{k: fl.get(k) for k in ("start", "end", "category", "evidence", "why")}}
        for i, fl in enumerate(flags)
    ]
    parts = _frame_parts(context)
    parts.append(transcript_block(transcript))
    parts.append("CANDIDATE FLAGS:\n" + json.dumps(candidates, ensure_ascii=False, indent=1))

    try:
        verdicts = {v["id"]: v for v in _generate(VERIFY_SYSTEM, parts).get("verdicts", [])}
    except Exception as exc:
        log.warning("Verification pass failed, keeping unverified flags: %s", exc)
        return [{**fl, "verified": False} for fl in flags]

    kept = []
    for i, fl in enumerate(flags):
        v = verdicts.get(i)
        if v is None or v.get("keep"):
            kept.append({**fl, "verified": v is not None, "verify_reason": (v or {}).get("reason")})
    return kept
