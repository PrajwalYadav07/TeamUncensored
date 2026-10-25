import asyncio
import os
import tempfile
import threading
import unittest
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
from fastapi.testclient import TestClient

from app import jobs, main, transcribe
from app.config import speech_model
from app.frames import VideoInfo
from app.options import Options


TRANSCRIPT = {"language": "en", "segments": [{
    "start": 1.0, "end": 2.0, "text": "shit", "words": [{"start": 1.2, "end": 1.5, "word": "shit"}],
}]}
EMPTY_REVIEW = {"bias_flags": [], "claims": [], "disclaimers": [], "model": "test"}


class PipelineTests(unittest.IsolatedAsyncioTestCase):
    async def test_speech_only_skips_all_external_calls_and_frames(self):
        fd, path = tempfile.mkstemp(suffix=".mp4")
        os.close(fd)
        job = jobs.Job("test", Options(check_bias=False, check_claims=False))
        with ExitStack() as stack:
            asr = stack.enter_context(patch.object(jobs, "transcribe", return_value=TRANSCRIPT))
            stack.enter_context(patch.object(jobs, "video_info", return_value=VideoInfo(4, 320, 240, 1)))
            frame_sampler = stack.enter_context(patch.object(jobs, "sample_frames"))
            visual = stack.enter_context(patch.object(jobs.gemma, "visual"))
            speech = stack.enter_context(patch.object(jobs.gemma, "speech"))
            verify = stack.enter_context(patch.object(jobs.gemma, "verify_bias"))
            await jobs._run(job, path)
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(job.result["profanity_flags"][0]["start"], 1.2)
        self.assertEqual(job.result["models"], [])
        self.assertEqual(job.result["video"]["frames_analyzed"], 0)
        self.assertEqual(job.result["whisper"], speech_model("fast"))
        self.assertEqual(asr.call_args.args[-1], speech_model("fast"))
        for function in (frame_sampler, visual, speech, verify):
            function.assert_not_called()
        self.assertFalse(os.path.exists(path))

    async def test_preview_is_published_before_visual_review_completes(self):
        visual_started = threading.Event()
        finish_visual = threading.Event()

        def visual(*args):
            visual_started.set()
            finish_visual.wait(timeout=5)
            return EMPTY_REVIEW

        job = jobs.Job("test", Options())
        with patch.object(jobs, "transcribe", return_value=TRANSCRIPT), \
             patch.object(jobs, "sample_frames", return_value=(VideoInfo(4, 320, 240, 1), [])), \
             patch.object(jobs.gemma, "visual", side_effect=visual), \
             patch.object(jobs.gemma, "speech", return_value=EMPTY_REVIEW):
            task = asyncio.create_task(jobs._run(job, "missing-test-input"))
            try:
                async def ready():
                    while job.preview is None or not visual_started.is_set():
                        await asyncio.sleep(0.01)
                await asyncio.wait_for(ready(), timeout=3)
                self.assertEqual(job.status, "running")
                self.assertEqual(len(job.public()["preview"]["profanity_flags"]), 1)
            finally:
                finish_visual.set()
                await task
        self.assertEqual(job.status, "done", job.error)

    async def test_profanity_can_be_disabled_and_accurate_model_is_selected(self):
        job = jobs.Job("test", Options(mode="accurate", check_profanity=False))
        with patch.object(jobs, "transcribe", return_value=TRANSCRIPT) as asr, \
             patch.object(jobs, "sample_frames", return_value=(VideoInfo(4, 320, 240, 1), [])), \
             patch.object(jobs.gemma, "visual", return_value=EMPTY_REVIEW), \
             patch.object(jobs.gemma, "speech", return_value=EMPTY_REVIEW):
            await jobs._run(job, "missing-test-input")
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(job.result["profanity_flags"], [])
        self.assertEqual(job.stages["profanity"]["state"], "skipped")
        self.assertEqual(asr.call_args.args[-1], speech_model("accurate"))

    async def test_asr_error_is_not_reported_as_clean_speech(self):
        job = jobs.Job("test", Options(check_bias=False, check_claims=False))
        with patch.object(jobs, "transcribe", return_value={"segments": [], "error": "decoder failed"}), \
             patch.object(jobs, "video_info", return_value=VideoInfo(4, 320, 240, 1)), \
             self.assertLogs("app.jobs", level="ERROR"):
            await jobs._run(job, "missing-test-input")
        self.assertEqual(job.status, "error")
        self.assertIsNone(job.result)
        self.assertEqual(job.stages["transcribe"]["state"], "error")

    async def test_empty_transcription_finishes_as_incomplete_without_a_score(self):
        job = jobs.Job("test", Options(check_bias=False, check_claims=False))
        with patch.object(jobs, "transcribe", return_value={"segments": [], "language": None}), \
             patch.object(jobs, "video_info", return_value=VideoInfo(4, 320, 240, 1)):
            await jobs._run(job, "missing-test-input")
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(job.result["verdict"], "review incomplete")
        self.assertIsNone(job.result["score"])
        self.assertEqual(job.result["speech_assessment"]["status"], "needs_review")

    async def test_contextual_profanity_is_included_in_final_score(self):
        value = {"language": "en", "segments": [{"start": 1, "end": 2, "text": "an offensive expression", "words": []}]}
        speech_result = {**EMPTY_REVIEW, "profanity_reviewed": True, "profanity_flags": [
            {"start": 1, "text": "offensive expression", "severity": "high", "language": "en"},
        ]}
        job = jobs.Job("test", Options())
        with patch.object(jobs, "transcribe", return_value=value), \
             patch.object(jobs, "sample_frames", return_value=(VideoInfo(4, 320, 240, 1), [])), \
             patch.object(jobs.gemma, "visual", return_value=EMPTY_REVIEW), \
             patch.object(jobs.gemma, "speech", return_value=speech_result):
            await jobs._run(job, "missing-test-input")
        self.assertEqual(job.status, "done", job.error)
        self.assertEqual(job.result["profanity_method"], "vocabulary_and_context")
        self.assertEqual(len(job.result["profanity_flags"]), 1)
        self.assertEqual(job.result["score"], 80)


class TranscriptionTests(unittest.TestCase):
    def segment(self, text, start):
        return SimpleNamespace(text=text, start=start, end=start + 1, no_speech_prob=0.01,
                               avg_logprob=-0.1, compression_ratio=1.0, words=[])

    def test_repeated_speech_and_uncertain_language_are_preserved(self):
        model = Mock()
        model.transcribe.return_value = ([self.segment("shit", 1), self.segment("shit", 3)],
                                         SimpleNamespace(language="hi", language_probability=0.3))
        with patch.object(transcribe, "load_audio", return_value=np.zeros(16000)), \
             patch.object(transcribe, "_get_model", return_value=model):
            result = transcribe.transcribe("unused", beam_size=1, model_name="small")
        self.assertEqual(len(result["segments"]), 2)
        self.assertEqual(model.transcribe.call_args.kwargs["temperature"], 0.0)
        self.assertEqual(model.transcribe.call_args.kwargs["best_of"], 1)

    def test_real_speech_containing_junk_phrase_is_kept(self):
        self.assertTrue(transcribe._keep_segment(self.segment("Subscribe, you idiot", 0)))
        self.assertFalse(transcribe._keep_segment(self.segment("Thanks for watching!", 0)))

    def test_no_audio_does_not_load_a_model(self):
        with patch.object(transcribe, "load_audio", return_value=None), \
             patch.object(transcribe, "_get_model") as model:
            self.assertEqual(transcribe.transcribe("unused")["segments"], [])
        model.assert_not_called()

    def test_discarded_speech_is_retained_as_uncertain_evidence(self):
        segment = self.segment("चूतिया", 1)
        segment.no_speech_prob = 0.7
        segment.avg_logprob = -1.2
        model = Mock()
        model.transcribe.return_value = ([segment], SimpleNamespace(language="hi", language_probability=0.9))
        with patch.object(transcribe, "load_audio", return_value=np.zeros(16000)), \
             patch.object(transcribe, "_get_model", return_value=model):
            result = transcribe.transcribe("unused")
        self.assertEqual(result["segments"], [])
        self.assertEqual(result["discarded_segments"], 1)
        self.assertEqual(result["uncertain_segments"][0]["text"], "चूतिया")

    def test_confident_short_profanity_is_not_erased_by_silence_estimate(self):
        segment = self.segment("bhenchod", 1)
        segment.no_speech_prob = 0.7
        self.assertTrue(transcribe._keep_segment(segment))

    def test_auto_mode_redetects_language_and_keeps_original_speech(self):
        model = Mock()
        segment = self.segment("fuck you", 1)
        segment.words = [SimpleNamespace(start=1, end=1.5, word="fuck", probability=0.2),
                         SimpleNamespace(start=1.5, end=2, word="you", probability=0.9)]
        model.transcribe.return_value = ([segment], SimpleNamespace(language="en", language_probability=0.9))
        with patch.object(transcribe, "load_audio", return_value=np.zeros(16000)), \
             patch.object(transcribe, "_get_model", return_value=model):
            result = transcribe.transcribe("unused", beam_size=3)
        self.assertTrue(model.transcribe.call_args.kwargs["multilingual"])
        self.assertEqual(model.transcribe.call_args.kwargs["task"], "transcribe")
        self.assertEqual(result["segments"][0]["text"], "fuck you")
        self.assertEqual([w["word"] for w in result["segments"][0]["words"]], ["fuck", "you"])

    def test_selected_language_is_respected(self):
        model = Mock()
        model.transcribe.return_value = ([], SimpleNamespace(language="gu", language_probability=1))
        with patch.object(transcribe, "load_audio", return_value=np.zeros(16000)), \
             patch.object(transcribe, "_get_model", return_value=model):
            transcribe.transcribe("unused", language="gu")
        self.assertEqual(model.transcribe.call_args.kwargs["language"], "gu")
        self.assertFalse(model.transcribe.call_args.kwargs["multilingual"])


class ApiTests(unittest.TestCase):
    def test_speech_only_upload_works_without_gemini_key(self):
        saved = []

        def create(path, opts):
            saved.append(path)
            self.assertTrue(opts.check_profanity)
            self.assertFalse(opts.check_bias or opts.check_claims)
            return jobs.Job("test", opts)

        try:
            with patch.object(main, "gemini_api_keys", return_value=[]), \
                 patch.object(main.jobs, "create", side_effect=create):
                response = TestClient(main.app).post("/api/jobs", files={"video": ("clip.mp4", b"test", "video/mp4")},
                                                     data={"check_bias": "false", "check_claims": "false", "check_profanity": "true", "language": "gu"})
            self.assertEqual(response.status_code, 200, response.text)
        finally:
            for path in saved:
                os.remove(path)

    def test_no_checks_is_rejected(self):
        response = TestClient(main.app).post("/api/jobs", files={"video": ("clip.mp4", b"test")},
                                            data={"check_bias": "false", "check_claims": "false", "check_profanity": "false"})
        self.assertEqual(response.status_code, 400)

    def test_visual_checks_still_require_api_key(self):
        with patch.object(main, "gemini_api_keys", return_value=[]):
            response = TestClient(main.app).post("/api/jobs", files={"video": ("clip.mp4", b"test")})
        self.assertEqual(response.status_code, 500)


if __name__ == "__main__":
    unittest.main()
