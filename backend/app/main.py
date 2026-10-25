import asyncio
import logging
import os
import tempfile
import time

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

from . import gemma, measure
from .config import GEMMA_MODEL, MAX_UPLOAD_MB, WHISPER_MODEL
from .frames import sample_frames
from .transcribe import transcribe

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("adlint")

app = FastAPI(title="adlint")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

LANGUAGES = {"auto": None, "hi": "hi", "en": "en", "gu": "gu"}


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "model": GEMMA_MODEL,
        "whisper": WHISPER_MODEL,
        "api_key_set": bool(os.getenv("GEMINI_API_KEY")),
    }


@app.post("/api/analyze")
async def analyze(
    video: UploadFile = File(...),
    language: str = Form("auto"),
    script: str = Form(""),
):
    if not os.getenv("GEMINI_API_KEY"):
        raise HTTPException(500, "GEMINI_API_KEY is not set in backend/.env")
    if language not in LANGUAGES:
        raise HTTPException(400, f"language must be one of {list(LANGUAGES)}")

    suffix = os.path.splitext(video.filename or "")[1] or ".mp4"
    fd, path = tempfile.mkstemp(suffix=suffix)
    timings: dict[str, float] = {}
    try:
        size = 0
        with os.fdopen(fd, "wb") as out:
            while chunk := await video.read(1 << 20):
                size += len(chunk)
                if size > MAX_UPLOAD_MB * (1 << 20):
                    raise HTTPException(413, f"Video is larger than {MAX_UPLOAD_MB} MB")
                out.write(chunk)

        t0 = time.perf_counter()
        try:
            (info, frames), transcript = await asyncio.gather(
                asyncio.to_thread(sample_frames, path),
                asyncio.to_thread(transcribe, path, LANGUAGES[language]),
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        timings["extract_s"] = round(time.perf_counter() - t0, 1)

        t1 = time.perf_counter()
        try:
            raw = await asyncio.to_thread(gemma.analyze, frames, transcript, script.strip() or None)
        except Exception as exc:
            log.exception("Gemma analysis failed")
            raise HTTPException(502, f"Gemma analysis failed: {exc}")
        timings["analyze_s"] = round(time.perf_counter() - t1, 1)

        t2 = time.perf_counter()
        bias = await asyncio.to_thread(gemma.verify_bias, raw["bias_flags"], frames, transcript, info.interval)
        timings["verify_s"] = round(time.perf_counter() - t2, 1)

        spans = measure.disclaimer_spans(raw["disclaimers"], info.interval)
        claims = measure.match_claims(raw["claims"], spans)
        report = measure.build_report(bias, claims, spans)

        return {
            "video": {
                "duration": info.duration,
                "width": info.width,
                "height": info.height,
                "frame_interval": info.interval,
                "frames_analyzed": len(frames),
            },
            "transcript": transcript,
            "bias_flags": bias,
            "bias_flags_dropped": len(raw["bias_flags"]) - len(bias),
            "claims": claims,
            "disclaimers": spans,
            **report,
            "model": raw["model"],
            "timings": timings,
        }
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
