import unittest

from app.measure import build_report
from app.profanity import detect, detect_with_uncertain, merge_contextual
from app.prompts import speech_system
from app.speech_quality import assess


def transcript(text="Hello everyone", **extra):
    return {"language": "hi", "segments": [{"start": 1, "end": 3, "text": text, "words": []}], **extra}


class SpeechQualityTests(unittest.TestCase):
    def test_empty_speech_cannot_be_scored_as_ready(self):
        assessment = assess({"segments": []})
        report = build_report([], [], [], [], assessment)
        self.assertEqual(assessment["status"], "needs_review")
        self.assertIsNone(report["score"])
        self.assertEqual(report["verdict"], "review incomplete")

    def test_rejected_speech_is_not_clean_speech(self):
        assessment = assess(transcript(discarded_segments=5))
        self.assertEqual(assessment["status"], "needs_review")
        self.assertIsNone(build_report([], [], [], [], assessment)["score"])

    def test_uncertain_words_or_language_require_review(self):
        for extra in ({"word_probability": 0.5}, {"language_probability": 0.4}, {"language": "es"}):
            with self.subTest(extra=extra):
                self.assertEqual(assess(transcript(**extra))["status"], "needs_review")

    def test_partial_transcript_does_not_certify_untranscribed_speech(self):
        self.assertEqual(assess(transcript(speech_seconds=30))["status"], "needs_review")

    def test_speech_padding_does_not_make_a_complete_transcript_look_partial(self):
        value = {
            "language": "en", "speech_seconds": 4.752, "speech_padding_seconds": 0.4, "audio_seconds": 5.359,
            "segments": [{"start": 0, "end": 1.2}, {"start": 2.01, "end": 2.73}, {"start": 3.58, "end": 4.26}],
        }
        self.assertEqual(assess(value)["status"], "complete")

    def test_overlapping_padding_does_not_count_missing_speech_twice(self):
        value = {
            "language": "en", "speech_seconds": 10, "speech_padding_seconds": 0.4,
            "segments": [{"start": 1, "end": 2}] * 10,
        }
        self.assertEqual(assess(value)["status"], "needs_review")

    def test_complete_clean_transcript_reports_no_flags_not_ready(self):
        assessment = assess(transcript(language_probability=0.98, word_probability=0.95))
        self.assertEqual(assessment["status"], "complete")
        report = build_report([], [], [], [], assessment)
        self.assertEqual(report["verdict"], "no flags detected")
        self.assertEqual(report["score"], 100)


class ContextualProfanityTests(unittest.TestCase):
    def test_hindi_slang_and_inflections_are_detected(self):
        for phrase in ("भोसड़ी वाले", "चूतियों", "बकचोदी", "chutiyapa", "bhosdi wale", "ભોસડીના"):
            with self.subTest(phrase=phrase):
                self.assertTrue(detect(transcript(phrase)))
        self.assertEqual(detect(transcript("मुझे छोड़ दो")), [])

    def test_model_quote_must_be_present_in_transcript(self):
        self.assertEqual(merge_contextual([], [{"start": 1, "text": "invented abuse"}], transcript()), [])

    def test_grounded_contextual_phrase_gets_asr_timestamps(self):
        value = transcript("some abusive expression")
        flags = merge_contextual([], [{"start": 1.5, "text": "abusive expression", "severity": "high", "language": "en"}], value)
        self.assertEqual(len(flags), 1)
        self.assertEqual((flags[0]["start"], flags[0]["end"]), (1, 3))
        self.assertEqual(flags[0]["timing_precision"], "segment")
        self.assertEqual(flags[0]["detector"], "gemma")

    def test_contextual_results_do_not_double_penalize_dictionary_match(self):
        value = transcript("you fucking idiot")
        local = detect(value)
        self.assertEqual(merge_contextual(local, [{"start": 1, "text": "fucking idiot"}], value), local)

    def test_model_cannot_assign_quote_to_another_moment(self):
        self.assertEqual(merge_contextual([], [{"start": 99, "text": "Hello"}], transcript()), [])

    def test_profanity_review_is_separate_from_bias(self):
        prompt = speech_system(False, False, True)
        self.assertIn('"profanity_flags"', prompt)
        self.assertIn("separate from bias", prompt)
        self.assertNotIn('"bias_flags"', prompt)

    def test_rejected_speech_retains_explicitly_uncertain_bad_word_candidates(self):
        value = {"segments": [], "uncertain_segments": [{"start": 1, "end": 2, "text": "चूतिया", "words": []}], "discarded_segments": 1}
        flags = detect_with_uncertain(value)
        self.assertEqual(len(flags), 1)
        self.assertTrue(flags[0]["uncertain"])
        self.assertEqual(build_report([], [], [], flags, assess(value))["verdict"], "review incomplete")


if __name__ == "__main__":
    unittest.main()
