import logging
import threading

import av
import numpy as np

from .config import WHISPER_COMPUTE_TYPE, WHISPER_MODEL

SAMPLE_RATE = 16000

# Whisper invents these on music, silence, and ads with little speech.
_JUNK = (
    "subscribe",
    "thanks for watching",
    "thank you for watching",
    "like and share",
    "sustain the love",
    "subtitles by",
    "amara.org",
    "mbc.net",
)

log = logging.getLogger(__name__)

_model = None
_lock = threading.Lock()


def _get_model():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel

            log.info("Loading Whisper model %s (first run downloads it)", WHISPER_MODEL)
            _model = WhisperModel(WHISPER_MODEL, device="cpu", compute_type=WHISPER_COMPUTE_TYPE)
        return _model


def load_audio(path: str) -> np.ndarray | None:
    """Decode the first audio stream to 16 kHz mono float32, or None if the file has no audio.

    faster-whisper's own decoder passes an argument PyAV 15+ no longer accepts, so decode here.
    """
    with av.open(path) as container:
        if not container.streams.audio:
            return None
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        chunks = []
        for frame in container.decode(audio=0):
            for out in resampler.resample(frame):
                chunks.append(out.to_ndarray())
        for out in resampler.resample(None):
            chunks.append(out.to_ndarray())
    if not chunks:
        return None
    return np.concatenate(chunks, axis=1).reshape(-1).astype(np.float32) / 32768.0


def _keep_segment(seg) -> bool:
    text = (seg.text or "").strip()
    if len(text) < 2:
        return False
    if seg.no_speech_prob is not None and seg.no_speech_prob >= 0.45:
        return False
    if seg.avg_logprob is not None and seg.avg_logprob <= -1.0:
        return False
    if seg.compression_ratio is not None and seg.compression_ratio >= 2.4:
        return False
    low = text.lower()
    if any(phrase in low for phrase in _JUNK):
        return False
    words = list(seg.words or [])
    probs = [w.probability for w in words if getattr(w, "probability", None) is not None]
    if probs and (sum(probs) / len(probs)) < 0.4:
        return False
    return True


def transcribe(path: str, language: str | None = None, beam_size: int = 5) -> dict:
    """Returns {"language": str | None, "segments": [{"start", "end", "text", "words": [...]}]}.

    Low-confidence and known-hallucination lines are dropped so music and silence
    are not shown as a transcript.
    """
    try:
        audio = load_audio(path)
        if audio is None or audio.size == 0:
            return {"language": None, "segments": []}
        segments, info = _get_model().transcribe(
            audio,
            language=language or None,
            word_timestamps=True,
            vad_filter=True,
            beam_size=beam_size,
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
            vad_parameters={"min_silence_duration_ms": 500},
        )
        out = []
        seen: set[str] = set()
        dropped = 0
        for seg in segments:
            text = seg.text.strip()
            key = text.casefold()
            if not _keep_segment(seg) or key in seen:
                dropped += 1
                continue
            seen.add(key)
            out.append(
                {
                    "start": round(float(seg.start), 2),
                    "end": round(float(seg.end), 2),
                    "text": text,
                    "words": [
                        {"start": round(float(w.start), 2), "end": round(float(w.end), 2), "word": w.word.strip()}
                        for w in (seg.words or [])
                        if getattr(w, "probability", 1) >= 0.35
                    ],
                }
            )
        uncertain = language is None and getattr(info, "language_probability", 1.0) < 0.45
        if uncertain:
            dropped += len(out)
            out = []
        note = None
        if not out and dropped:
            note = "No clear speech in this video. Background audio was left out."
        return {
            "language": info.language if out else None,
            "segments": out,
            "note": note,
        }
    except Exception as exc:  # silent ads or videos without an audio stream
        log.warning("Transcription failed: %s", exc)
        return {"language": None, "segments": [], "error": str(exc)}


def preload():
    _get_model()
