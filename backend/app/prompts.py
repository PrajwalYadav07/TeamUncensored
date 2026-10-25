BIAS_CATEGORIES = [
    "colourism",
    "gender_stereotype",
    "body_shaming",
    "caste_or_community",
    "regional_stereotype",
    "religious_stereotype",
    "age_or_disability",
]

CLAIM_TYPES = ["efficacy", "superiority", "health", "statistic", "price_or_offer", "endorsement"]

_CONTEXT = """You are a pre-release compliance reviewer for Indian television and social media ads.
The ad may be in Hindi, English, Gujarati, or a mix. Use English for evidence, why and suggested_fix,
but quote claim and disclaimer text in the original language."""

_BIAS_RULES = f"""Bias: flag moments that could reasonably be read as harmful stereotyping in an Indian context.
Categories: {", ".join(BIAS_CATEGORIES)}.
Only flag what is actually shown or said. Do not flag an ad merely for featuring a woman, a family, a
religious festival, or a regional setting. Flag the framing: fair skin presented as the route to success or
marriage, only women doing housework while men relax, a regional accent used as the joke, a body type used
as the punchline."""

_BIAS_SHAPE = """{"start": 0.0, "end": 0.0, "category": "...", "source": "%s",
      "evidence": "what is visible or said", "why": "why this could be read as harmful",
      "suggested_fix": "a concrete edit", "severity": "low|medium|high", "confidence": 0.0}"""

_CLAIM_RULES = f"""Claims: product claims that would normally need substantiation or a disclaimer, such as
"kills 99.9% germs", "No. 1 brand", "doctor recommended", "clinically proven", "results in 7 days", prices,
offers and statistics. Types: {", ".join(CLAIM_TYPES)}."""

_CLAIM_SHAPE = """{"time": 0.0, "source": "%s", "text": "...", "claim_type": "...", "needs_disclaimer": true}"""

_DISCLAIMER_RULES = """Disclaimers: for EVERY frame where small-print or disclaimer text is visible (for example
"*conditions apply", "*based on lab tests", "*T&C"), output one entry for that frame with the frame time, the
text you can read, the number of text lines, and a bounding box around the whole disclaimer block as
box_2d = [ymin, xmin, ymax, xmax] normalised to 0-1000. If the same disclaimer appears in 5 frames, output
5 entries."""

_DISCLAIMER_SHAPE = """{"time": 0.0, "text": "...", "line_count": 1, "box_2d": [0, 0, 0, 0]}"""


def visual_system(check_bias: bool, check_claims: bool) -> str:
    tasks, shape = [], []
    if check_bias:
        tasks.append(_BIAS_RULES + " Use source \"visual\" or \"on_screen_text\".")
        shape.append('"bias_flags": [' + _BIAS_SHAPE % "visual|on_screen_text" + "]")
    if check_claims:
        tasks.append(
            _CLAIM_RULES + " Only on-screen claims here. List each distinct claim ONCE, at the first frame where it appears."
        )
        tasks.append(_DISCLAIMER_RULES)
        shape.append('"claims": [' + _CLAIM_SHAPE % "on_screen_text" + "]")
        shape.append('"disclaimers": [' + _DISCLAIMER_SHAPE + "]")
    return (
        _CONTEXT
        + "\nYou receive sampled video frames in time order, each labelled with its timestamp in seconds."
        + " There is no audio in this request.\n\n"
        + "\n\n".join(tasks)
        + "\n\nReturn ONLY a JSON object, no markdown:\n{\n  "
        + ",\n  ".join(shape)
        + "\n}"
    )


def speech_system(check_bias: bool, check_claims: bool) -> str:
    tasks, shape = [], []
    if check_bias:
        tasks.append(_BIAS_RULES + ' Only judge what is said. Use source "speech".')
        shape.append('"bias_flags": [' + _BIAS_SHAPE % "speech" + "]")
    if check_claims:
        tasks.append(_CLAIM_RULES + " Only spoken claims, with the time the claim starts in the transcript.")
        shape.append('"claims": [' + _CLAIM_SHAPE % "speech" + "]")
    return (
        _CONTEXT
        + "\nYou receive a timestamped transcript of the voiceover and dialogue.\n\n"
        + "\n\n".join(tasks)
        + "\n\nReturn ONLY a JSON object, no markdown:\n{\n  "
        + ",\n  ".join(shape)
        + "\n}"
    )


VERIFY_SYSTEM = """You are a second, sceptical reviewer for an Indian ad compliance tool.
Another reviewer produced the candidate bias flags below. For each flag you see the frames around it and
the transcript. Keep a flag only if a reasonable Indian viewer could read that moment as harmful
stereotyping. Drop flags that are neutral depictions, over-reading, or not supported by the frames or
transcript.

Return ONLY a JSON object, no markdown:
{"verdicts": [{"id": 0, "keep": true, "reason": "one sentence"}]}
"""


def transcript_block(transcript: dict) -> str:
    segs = transcript.get("segments") or []
    if not segs:
        return "TRANSCRIPT: (no speech detected)"
    lines = [f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segs]
    return "TRANSCRIPT:\n" + "\n".join(lines)
