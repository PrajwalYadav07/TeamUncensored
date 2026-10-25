"""Describe missing speech evidence instead of treating it as a clean result."""


def assess(transcript: dict) -> dict:
    reasons = []
    if not transcript.get("segments"):
        reasons.append("No clear speech was transcribed. Spoken content could not be checked.")
    if transcript.get("discarded_segments", 0):
        reasons.append("Some speech was discarded because transcription confidence was low.")
    probability = transcript.get("language_probability")
    if probability is not None and probability < 0.65:
        reasons.append("The spoken language was uncertain. Choose Hindi, English, or Gujarati explicitly and recheck the transcript.")
    if transcript.get("language") not in {None, "hi", "en", "gu"}:
        reasons.append("The detected language was outside Hindi, English, and Gujarati. Check the selected language.")
    probability = transcript.get("word_probability")
    if probability is not None and probability < 0.65:
        reasons.append("The speech transcript contains uncertain words. Review it against the audio.")
    speech_seconds = transcript.get("speech_seconds")
    # VAD duration includes padding around utterances, while word-aligned ASR
    # spans do not. Compare like-for-like and merge overlapping padded spans.
    pad = max(0, transcript.get("speech_padding_seconds", 0))
    duration = transcript.get("audio_seconds")
    spans = sorted((max(0, s["start"] - pad), min(s["end"] + pad, duration) if duration is not None else s["end"] + pad) for s in transcript.get("segments") or [])
    covered, last_end = 0, 0
    for start, end in spans:
        covered += max(0, end - max(start, last_end))
        last_end = max(last_end, end)
    if speech_seconds and covered < speech_seconds * 0.65:
        reasons.append("The transcript covers only part of the detected speech.")
    return {"status": "needs_review" if reasons else "complete", "reasons": reasons}
