import os

from dotenv import load_dotenv

load_dotenv()

GEMMA_ATTEMPTS = int(os.getenv("GEMMA_ATTEMPTS", "2"))

# Numbered names are checked after GEMINI_API_KEYS. A lone GEMINI_API_KEY still works.
_GEMINI_KEY_VARS = ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3", "GEMINI_API_KEY_4")


def gemini_api_keys() -> list[str]:
    """Configured Gemini keys, in failover order, with duplicates removed."""
    ordered: list[str] = []
    seen: set[str] = set()

    def add(value: str | None, *, split: bool) -> None:
        if not value:
            return
        parts = value.split(",") if split else (value,)
        for part in parts:
            key = part.strip()
            if key and key not in seen:
                seen.add(key)
                ordered.append(key)

    add(os.getenv("GEMINI_API_KEYS"), split=True)
    for name in _GEMINI_KEY_VARS:
        add(os.getenv(name), split=False)
    return ordered

# 26B is a mixture-of-experts model with ~4B active parameters, so it answers much faster than 31B.
MODES = {
    "fast": {
        "model": os.getenv("FAST_MODEL", "gemma-4-26b-a4b-it"),
        "fallback": os.getenv("FAST_FALLBACK_MODEL", "gemma-4-31b-it"),
        "thinking": "minimal",
        "frame_side": 640,
        "beam_size": 1,
        "batch_frames": 12,
    },
    "accurate": {
        "model": os.getenv("ACCURATE_MODEL", "gemma-4-31b-it"),
        "fallback": os.getenv("ACCURATE_FALLBACK_MODEL", "gemma-4-26b-a4b-it"),
        "thinking": "high",
        "frame_side": 768,
        "beam_size": 5,
        "batch_frames": 20,
    },
}

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

MAX_FRAMES = int(os.getenv("MAX_FRAMES", "60"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))

# Default disclaimer rules. Product defaults the user can override per check, not quotes from a regulator.
READING_WORDS_PER_SEC = 3.0
MIN_DISCLAIMER_SECONDS = 2.0
MIN_TEXT_HEIGHT_PCT = 2.5
CLAIM_WINDOW_BEFORE = 2.0
CLAIM_WINDOW_AFTER = 5.0
