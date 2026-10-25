import os

from dotenv import load_dotenv

load_dotenv()

GEMMA_MODEL = os.getenv("GEMMA_MODEL", "gemma-4-31b-it")
GEMMA_THINKING = os.getenv("GEMMA_THINKING", "high")  # "high" or "minimal"

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "medium")
WHISPER_COMPUTE_TYPE = os.getenv("WHISPER_COMPUTE_TYPE", "int8")

MAX_FRAMES = int(os.getenv("MAX_FRAMES", "60"))
FRAME_MAX_SIDE = int(os.getenv("FRAME_MAX_SIDE", "768"))
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "200"))

# Thresholds are product defaults, not quotes from any regulator's code.
READING_WORDS_PER_SEC = float(os.getenv("READING_WORDS_PER_SEC", "3"))
MIN_DISCLAIMER_SECONDS = float(os.getenv("MIN_DISCLAIMER_SECONDS", "2"))
MIN_TEXT_HEIGHT_PCT = float(os.getenv("MIN_TEXT_HEIGHT_PCT", "2.5"))
CLAIM_WINDOW_BEFORE = float(os.getenv("CLAIM_WINDOW_BEFORE", "2"))
CLAIM_WINDOW_AFTER = float(os.getenv("CLAIM_WINDOW_AFTER", "5"))
