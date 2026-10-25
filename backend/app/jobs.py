import asyncio
import logging
import os
import time
import uuid
from dataclasses import dataclass, field

from . import gemma, measure
from .config import WHISPER_MODEL
from .frames import sample_frames
from .options import Options
from .transcribe import transcribe

log = logging.getLogger(__name__)

STAGES = [
    ("frames", "Extract frames"),
    ("transcribe", "Transcribe audio"),
    ("visual", "Gemma: review frames"),
    ("speech", "Gemma: review speech"),
    ("recheck", "Gemma: re-check bias flags"),
    ("report", "Measure and score"),
]


@dataclass
class Job:
    id: str
    options: Options
    status: str = "running"  # running | done | error
    stages: dict = field(default_factory=lambda: {k: {"label": l, "state": "pending", "seconds": None} for k, l in STAGES})
    result: dict | None = None
    error: str | None = None
    created: float = field(default_factory=time.time)

    def public(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "stages": [{"key": k, **self.stages[k]} for k, _ in STAGES],
            "result": self.result,
            "error": self.error,
        }


JOBS: dict[str, Job] = {}


class _Stage:
    def __init__(self, job: Job, key: str):
        self.job, self.key = job, key

    def __enter__(self):
        self.t0 = time.perf_counter()
        self.job.stages[self.key]["state"] = "running"
        return self

    def __exit__(self, exc_type, exc, tb):
        s = self.job.stages[self.key]
        s["seconds"] = round(time.perf_counter() - self.t0, 1)
        s["state"] = "error" if exc_type else "done"
        return False


def _skip(job: Job, key: str):
    job.stages[key]["state"] = "skipped"


def create(path: str, opts: Options) -> Job:
    job = Job(id=uuid.uuid4().hex[:12], options=opts)
    JOBS[job.id] = job
    for old in [j for j in JOBS.values() if time.time() - j.created > 3600]:
        JOBS.pop(old.id, None)
    asyncio.get_running_loop().create_task(_run(job, path))
    return job


async def _run(job: Job, path: str):
    opts = job.options
    t_start = time.perf_counter()
    try:
        async def frames_then_visual():
            with _Stage(job, "frames"):
                info, frames = await asyncio.to_thread(sample_frames, path, opts.profile["frame_side"])
            with _Stage(job, "visual"):
                visual = await asyncio.to_thread(gemma.visual, frames, opts)
            return info, frames, visual

        async def transcript_then_speech():
            with _Stage(job, "transcribe"):
                transcript = await asyncio.to_thread(transcribe, path, opts.language, opts.profile["beam_size"])
            if not transcript.get("segments") and not opts.script:
                _skip(job, "speech")
                return transcript, {"bias_flags": [], "claims": []}
            with _Stage(job, "speech"):
                speech = await asyncio.to_thread(gemma.speech, transcript, opts)
            return transcript, speech

        (info, frames, visual), (transcript, speech) = await asyncio.gather(
            frames_then_visual(), transcript_then_speech()
        )

        bias = measure.merge_bias(visual["bias_flags"] + speech["bias_flags"], info.interval)
        candidates = len(bias)
        if opts.check_bias and opts.recheck and bias:
            with _Stage(job, "recheck"):
                bias = await asyncio.to_thread(gemma.verify_bias, bias, frames, transcript, info.interval, opts)
        else:
            _skip(job, "recheck")

        with _Stage(job, "report"):
            spans = measure.disclaimer_spans(visual["disclaimers"], info.interval, opts.rules)
            claims = measure.match_claims(measure.dedupe_claims(visual["claims"] + speech["claims"]), spans, opts.rules)
            report = measure.build_report(sorted(bias, key=lambda b: float(b.get("start") or 0)), claims, spans)

        job.result = {
            "video": {
                "duration": info.duration,
                "width": info.width,
                "height": info.height,
                "frame_interval": info.interval,
                "frames_analyzed": len(frames),
            },
            "transcript": transcript,
            "bias_flags": sorted(bias, key=lambda b: float(b.get("start") or 0)),
            "bias_flags_dropped": candidates - len(bias),
            "claims": claims,
            "disclaimers": spans,
            **report,
            "settings": {
                "mode": opts.mode,
                "check_bias": opts.check_bias,
                "check_claims": opts.check_claims,
                "recheck": opts.recheck,
                "language": opts.language or "auto",
                "rules": vars(opts.rules),
            },
            "models": sorted({visual.get("model"), speech.get("model")} - {None}),
            "visual_batches": visual.get("batches", 1),
            "whisper": WHISPER_MODEL,
            "total_seconds": round(time.perf_counter() - t_start, 1),
        }
        job.status = "done"
    except Exception as exc:
        log.exception("Job %s failed", job.id)
        job.status = "error"
        job.error = str(exc)
        for s in job.stages.values():
            if s["state"] in ("pending", "running"):
                s["state"] = "skipped" if s["state"] == "pending" else "error"
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
