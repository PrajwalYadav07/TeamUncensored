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

ANALYZE_SYSTEM = """You are a pre-release compliance reviewer for Indian television and social media ads.
You receive sampled video frames in time order (each labelled with its timestamp in seconds) and a
timestamped transcript of the voiceover and dialogue. The ad may be in Hindi, English, Gujarati, or a mix.

Find three things:

1. bias_flags: moments that could reasonably be read as harmful stereotyping in an Indian context.
   Categories: {categories}.
   Only flag what is actually shown or said. Do not flag an ad merely for featuring a woman, a family,
   a religious festival, or a regional setting. Flag the framing: for example fair skin presented as the
   route to success or marriage, only women doing housework while men relax, a regional accent used as
   the joke, a body type used as the punchline.

2. claims: product claims that would normally need substantiation or a disclaimer, such as
   "kills 99.9% germs", "No. 1 brand", "doctor recommended", "clinically proven", "results in 7 days",
   prices, offers, and statistics. Types: {claim_types}. Include spoken claims (source "speech") with the
   time the claim starts in the transcript, and on-screen claims (source "on_screen_text") with the frame time.

3. disclaimers: for EVERY frame where small-print or disclaimer text is visible (for example
   "*conditions apply", "*based on lab tests", "*T&C"), output one entry for that frame with the frame time,
   the text you can read, the number of text lines, and a bounding box around the whole disclaimer block as
   box_2d = [ymin, xmin, ymax, xmax] normalised to 0-1000. If the same disclaimer appears in 5 frames,
   output 5 entries.

Return ONLY a JSON object, no markdown, in this shape:
{{
  "bias_flags": [
    {{"start": 0.0, "end": 0.0, "category": "...", "source": "visual|on_screen_text|speech",
      "evidence": "what is visible or said", "why": "why this could be read as harmful",
      "suggested_fix": "a concrete edit", "severity": "low|medium|high", "confidence": 0.0}}
  ],
  "claims": [
    {{"time": 0.0, "source": "speech|on_screen_text", "text": "...", "claim_type": "...",
      "needs_disclaimer": true}}
  ],
  "disclaimers": [
    {{"time": 0.0, "text": "...", "line_count": 1, "box_2d": [0, 0, 0, 0]}}
  ]
}}
Use English for evidence, why and suggested_fix, but quote claim and disclaimer text in the original language.
""".format(categories=", ".join(BIAS_CATEGORIES), claim_types=", ".join(CLAIM_TYPES))

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
