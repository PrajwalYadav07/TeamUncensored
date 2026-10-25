import re
from difflib import SequenceMatcher

from .config import (
    CLAIM_WINDOW_AFTER,
    CLAIM_WINDOW_BEFORE,
    MIN_DISCLAIMER_SECONDS,
    MIN_TEXT_HEIGHT_PCT,
    READING_WORDS_PER_SEC,
)

SEVERITY_PENALTY = {"high": 20, "medium": 12, "low": 5}
UNSUPPORTED_CLAIM_PENALTY = 10
SHORT_DISCLAIMER_PENALTY = 10
SMALL_DISCLAIMER_PENALTY = 8


def _norm(text: str) -> str:
    return re.sub(r"\W+", " ", (text or "").lower()).strip()


def _num(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def disclaimer_spans(entries: list[dict], interval: float) -> list[dict]:
    """Merge per-frame disclaimer sightings into continuous on-screen spans."""
    entries = sorted(
        (e for e in entries if isinstance(e.get("box_2d"), list) and len(e["box_2d"]) == 4),
        key=lambda e: _num(e.get("time")),
    )
    spans: list[dict] = []
    for e in entries:
        t = _num(e.get("time"))
        text = e.get("text") or ""
        match = None
        for s in reversed(spans):
            if t - s["_last"] > interval * 1.6:
                break
            if SequenceMatcher(None, _norm(text), _norm(s["text"])).ratio() >= 0.6:
                match = s
                break
        if match is None:
            match = {"text": text, "start": t, "_last": t, "_samples": []}
            spans.append(match)
        match["_last"] = t
        if len(text) > len(match["text"]):
            match["text"] = text
        match["_samples"].append(e)

    out = []
    for s in spans:
        heights, boxes = [], []
        for e in s["_samples"]:
            ymin, xmin, ymax, xmax = (_num(v) for v in e["box_2d"])
            lines = max(1, int(_num(e.get("line_count"), 1)))
            heights.append(max(0.0, ymax - ymin) / 10.0 / lines)
            boxes.append([ymin, xmin, ymax, xmax])
        duration = round(s["_last"] - s["start"] + interval, 2)
        words = len(_norm(s["text"]).split())
        required = round(max(MIN_DISCLAIMER_SECONDS, words / READING_WORDS_PER_SEC), 1)
        text_height = round(sum(heights) / len(heights), 2) if heights else 0.0
        issues = []
        if duration < required:
            issues.append("too_short")
        if text_height < MIN_TEXT_HEIGHT_PCT:
            issues.append("too_small")
        out.append(
            {
                "text": s["text"],
                "start": s["start"],
                "end": round(s["_last"] + interval, 2),
                "duration": duration,
                "required_duration": required,
                "word_count": words,
                "text_height_pct": text_height,
                "min_text_height_pct": MIN_TEXT_HEIGHT_PCT,
                "box_2d": boxes[len(boxes) // 2],
                "issues": issues,
            }
        )
    return out


def match_claims(claims: list[dict], spans: list[dict]) -> list[dict]:
    out = []
    for c in claims:
        t = _num(c.get("time"))
        lo, hi = t - CLAIM_WINDOW_BEFORE, t + CLAIM_WINDOW_AFTER
        covering = [i for i, s in enumerate(spans) if s["start"] <= hi and s["end"] >= lo]
        needs = bool(c.get("needs_disclaimer", True))
        out.append(
            {
                **c,
                "time": t,
                "needs_disclaimer": needs,
                "disclaimer_ids": covering,
                "supported": (not needs) or bool(covering),
            }
        )
    return out


def build_report(bias_flags: list[dict], claims: list[dict], spans: list[dict]) -> dict:
    findings = []
    score = 100

    for i, f in enumerate(bias_flags):
        sev = f.get("severity") if f.get("severity") in SEVERITY_PENALTY else "medium"
        score -= SEVERITY_PENALTY[sev]
        start = _num(f.get("start"))
        findings.append(
            {
                "id": f"bias-{i}",
                "kind": "bias",
                "start": start,
                "end": max(start, _num(f.get("end"), start)),
                "severity": sev,
                "title": (f.get("category") or "bias").replace("_", " "),
                "detail": f,
            }
        )

    for i, c in enumerate(claims):
        if c["supported"]:
            continue
        score -= UNSUPPORTED_CLAIM_PENALTY
        findings.append(
            {
                "id": f"claim-{i}",
                "kind": "claim",
                "start": c["time"],
                "end": c["time"],
                "severity": "medium",
                "title": "claim without disclaimer",
                "detail": c,
            }
        )

    for i, s in enumerate(spans):
        if not s["issues"]:
            continue
        if "too_short" in s["issues"]:
            score -= SHORT_DISCLAIMER_PENALTY
        if "too_small" in s["issues"]:
            score -= SMALL_DISCLAIMER_PENALTY
        findings.append(
            {
                "id": f"disclaimer-{i}",
                "kind": "disclaimer",
                "start": s["start"],
                "end": s["end"],
                "severity": "high" if len(s["issues"]) == 2 else "medium",
                "title": "disclaimer " + " and ".join(x.replace("_", " ") for x in s["issues"]),
                "detail": s,
            }
        )

    findings.sort(key=lambda f: f["start"])
    score = max(0, score)
    has_high = any(f["severity"] == "high" for f in findings)
    if score >= 85 and not has_high:
        verdict = "ready"
    elif score >= 60:
        verdict = "fix before release"
    else:
        verdict = "high risk"
    return {"score": score, "verdict": verdict, "findings": findings}
