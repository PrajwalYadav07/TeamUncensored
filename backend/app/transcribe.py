import logging
import threading

import av
import numpy as np

from .config import WHISPER_COMPUTE_TYPE, WHISPER_CPU_THREADS, WHISPER_DEVICE, WHISPER_MODEL

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

_models = {}
_lock = threading.Lock()


def _get_model(model_name: str = WHISPER_MODEL):
    with _lock:
        if model_name not in _models:
            from faster_whisper import WhisperModel

            log.info("Loading Whisper model %s (first run downloads it)", model_name)
            _models[model_name] = WhisperModel(
                model_name, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE_TYPE,
                cpu_threads=WHISPER_CPU_THREADS,
            )
        return _models[model_name]


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
    # Match Whisper's joint silence test. A high silence estimate on its own
    # must not erase confidently decoded speech (common in short interjections).
    if seg.no_speech_prob is not None and seg.no_speech_prob >= 0.6 and (seg.avg_logprob is None or seg.avg_logprob <= -1.0):
        return False
    if seg.avg_logprob is not None and seg.avg_logprob <= -1.0:
        return False
    if seg.compression_ratio is not None and seg.compression_ratio >= 2.4:
        return False
    low = text.casefold().strip(" .,!?:;।")
    if low in _JUNK:
        return False
    words = list(seg.words or [])
    probs = [w.probability for w in words if getattr(w, "probability", None) is not None]
    if probs and (sum(probs) / len(probs)) < 0.4:
        return False
    return True


def transcribe(path: str, language: str | None = None, beam_size: int = 5, model_name: str = WHISPER_MODEL) -> dict:
    """Returns {"language": str | None, "segments": [{"start", "end", "text", "words": [...]}]}.

    Low-confidence and known-hallucination lines are dropped so music and silence
    are not shown as a transcript.
    """
    try:
        audio = load_audio(path)
        if audio is None or audio.size == 0:
            return {"language": None, "segments": []}
        segments, info = _get_model(model_name).transcribe(
            audio,
            language=language or None,
            task="transcribe",
            multilingual=language is None,
            word_timestamps=True,
            vad_filter=True,
            beam_size=beam_size,
            best_of=1 if beam_size <= 3 else 5,
            temperature=0.0 if beam_size <= 3 else (0.0, 0.2, 0.4, 0.6, 0.8, 1.0),
            condition_on_previous_text=False,
            hallucination_silence_threshold=2.0,
            vad_parameters={"min_silence_duration_ms": 300, "min_speech_duration_ms": 0, "speech_pad_ms": 400},
        )
        out = []
        dropped = 0
        probabilities = []
        uncertain_segments = []
        for seg in segments:
            text = seg.text.strip()
            if not _keep_segment(seg):
                dropped += 1
                if text:
                    uncertain_segments.append(_serialize_segment(seg))
                continue
            probabilities.extend(w.probability for w in (seg.words or []) if getattr(w, "probability", None) is not None)
            out.append(_serialize_segment(seg))
        note = None
        if not out and dropped:
            note = "Speech was transcribed with low confidence. Review the uncertain lines against the audio."
        return {
            "language": info.language if out else None,
            "segments": out,
            "note": note,
            "language_probability": getattr(info, "language_probability", None),
            "word_probability": sum(probabilities) / len(probabilities) if probabilities else None,
            "discarded_segments": dropped,
            "speech_seconds": getattr(info, "duration_after_vad", None),
            "audio_seconds": getattr(info, "duration", None),
            "speech_padding_seconds": 0.4,
            "uncertain_segments": uncertain_segments,
        }
    except Exception as exc:  # silent ads or videos without an audio stream
        log.warning("Transcription failed: %s", exc)
        return {"language": None, "segments": [], "error": str(exc)}


def _serialize_segment(seg) -> dict:
    # Keep original wording and every aligned word, including low-confidence
    # words. Confidence affects review status, never censorship of the text.
    return {
        "start": round(float(seg.start), 2), "end": round(float(seg.end), 2),
        "text": seg.text.strip(),
        "words": [
            {"start": round(float(w.start), 2), "end": round(float(w.end), 2), "word": w.word.strip(), "probability": getattr(w, "probability", None)}
            for w in (seg.words or [])
        ],
    }


def preload(model_name: str = WHISPER_MODEL):
    try:
        _get_model(model_name)
    except Exception:
        log.exception("Could not preload speech model %s; will retry on the next upload", model_name)
