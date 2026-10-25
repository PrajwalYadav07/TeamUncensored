import logging
import threading

import av
import numpy as np

from .config import WHISPER_COMPUTE_TYPE, WHISPER_MODEL

SAMPLE_RATE = 16000

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


def transcribe(path: str, language: str | None = None) -> dict:
    """Returns {"language": str | None, "segments": [{"start", "end", "text", "words": [...]}]}."""
    try:
        audio = load_audio(path)
        if audio is None or audio.size == 0:
            return {"language": None, "segments": []}
        segments, info = _get_model().transcribe(
            audio,
            language=language or None,
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
        )
        out = []
        for seg in segments:
            out.append(
                {
                    "start": round(float(seg.start), 2),
                    "end": round(float(seg.end), 2),
                    "text": seg.text.strip(),
                    "words": [
                        {"start": round(float(w.start), 2), "end": round(float(w.end), 2), "word": w.word.strip()}
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
