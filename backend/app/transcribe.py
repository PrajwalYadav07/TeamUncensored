import logging
import threading

from .config import WHISPER_COMPUTE_TYPE, WHISPER_MODEL

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


def transcribe(path: str, language: str | None = None) -> dict:
    """Returns {"language": str | None, "segments": [{"start", "end", "text", "words": [...]}]}."""
    try:
        segments, info = _get_model().transcribe(
            path,
            language=language or None,
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
        )
        out = []
        for seg in segments:
            out.append(
                {
                    "start": round(seg.start, 2),
                    "end": round(seg.end, 2),
                    "text": seg.text.strip(),
                    "words": [
                        {"start": round(w.start, 2), "end": round(w.end, 2), "word": w.word.strip()}
                        for w in (seg.words or [])
                    ],
                }
            )
        return {"language": info.language, "segments": out}
    except Exception as exc:  # silent ads or videos without an audio stream
        log.warning("Transcription failed: %s", exc)
        return {"language": None, "segments": [], "error": str(exc)}


def preload():
    _get_model()
