import logging
import os
import tempfile
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import jobs
from .config import MAX_UPLOAD_MB, MODES, WHISPER_MODEL, WHISPER_PRELOAD, gemini_api_keys, speech_model
from .options import Options, Rules
from .transcribe import preload

logging.basicConfig(level=logging.INFO)

@asynccontextmanager
async def lifespan(app: FastAPI):
    if WHISPER_PRELOAD:
        threading.Thread(target=preload, args=(speech_model("fast"),), daemon=True).start()
    yield


app = FastAPI(title="adlint", lifespan=lifespan)

_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
_origins += [o.strip().rstrip("/") for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_origin_regex=r"https://.*\.vercel\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)

LANGUAGES = {"auto": None, "hi": "hi", "en": "en", "gu": "gu"}


@app.get("/api/health")
def health():
    key_count = len(gemini_api_keys())
    return {
        "ok": True,
        "analysis_version": 2,
        "modes": {k: v["model"] for k, v in MODES.items()},
        "whisper": WHISPER_MODEL,
        "speech_models": {mode: speech_model(mode) for mode in MODES},
        "api_key_set": key_count > 0,
        "api_key_count": key_count,
    }


@app.post("/api/jobs")
async def create_job(
    video: UploadFile = File(...),
    mode: str = Form("fast"),
    language: str = Form("auto"),
    script: str = Form(""),
    check_bias: bool = Form(True),
    check_claims: bool = Form(True),
    check_profanity: bool = Form(True),
    recheck: bool = Form(True),
    min_disclaimer_seconds: float = Form(Rules.min_disclaimer_seconds),
    min_text_height_pct: float = Form(Rules.min_text_height_pct),
    reading_words_per_sec: float = Form(Rules.reading_words_per_sec),
):
    if (check_bias or check_claims) and not gemini_api_keys():
        raise HTTPException(500, "No Gemini API key is set in backend/.env")
    if mode not in MODES:
        raise HTTPException(400, f"mode must be one of {list(MODES)}")
    if language not in LANGUAGES:
        raise HTTPException(400, f"language must be one of {list(LANGUAGES)}")
    if not (check_bias or check_claims or check_profanity):
        raise HTTPException(400, "Select at least one check")
    if reading_words_per_sec <= 0:
        raise HTTPException(400, "reading_words_per_sec must be positive")

    suffix = os.path.splitext(video.filename or "")[1] or ".mp4"
    fd, path = tempfile.mkstemp(suffix=suffix)
    size = 0
    with os.fdopen(fd, "wb") as out:
        while chunk := await video.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB * (1 << 20):
                out.close()
                os.remove(path)
                raise HTTPException(413, f"Video is larger than {MAX_UPLOAD_MB} MB")
            out.write(chunk)

    opts = Options(
        mode=mode,
        language=LANGUAGES[language],
        script=script.strip() or None,
        check_bias=check_bias,
        check_claims=check_claims,
        check_profanity=check_profanity,
        recheck=recheck,
        rules=Rules(
            min_disclaimer_seconds=min_disclaimer_seconds,
            min_text_height_pct=min_text_height_pct,
            reading_words_per_sec=reading_words_per_sec,
        ),
    )
    return jobs.create(path, opts).public()


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    job = jobs.JOBS.get(job_id)
    if job is None:
        raise HTTPException(404, "Job not found")
    return job.public()
