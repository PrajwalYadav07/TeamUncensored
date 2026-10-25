import unittest

from app.measure import build_report
from app.profanity import detect


def transcript(text, words=None, start=1.0, end=4.0):
    return {"language": None, "segments": [{"start": start, "end": end, "text": text, "words": words or []}]}


class ProfanityTests(unittest.TestCase):
    def test_native_and_roman_spellings_in_all_languages(self):
        cases = {
            "What the FUCK!": "en",
            "तू चूतिया है।": "hi/gu",
            "તમે ગધેડો છો.": "gu",
            "તમે ચૂતિયા છો.": "hi/gu",
            "Ye madar chod hai": "hi/gu",
            "tu gadhedo che": "gu",
        }
        for text, language in cases.items():
            with self.subTest(text=text):
                flags = detect(transcript(text))
                self.assertEqual(len(flags), 1)
                self.assertEqual(flags[0]["language"], language)

    def test_boundaries_do_not_flag_substrings(self):
        self.assertEqual(detect(transcript("Scunthorpe, class, assembly, shitake, badassery and Gandhi.")), [])
        self.assertEqual(detect(transcript("नमस्ते आपका स्वागत है. નમસ્તે તમે કેમ છો? Hello everyone.")), [])

    def test_precise_word_timing_and_repetitions(self):
        flags = detect(transcript("shit, shit!", [
            {"word": "shit,", "start": 1.1, "end": 1.3},
            {"word": "shit!", "start": 2.1, "end": 2.4},
        ]))
        self.assertEqual([(f["start"], f["end"]) for f in flags], [(1.1, 1.3), (2.1, 2.4)])
        self.assertTrue(all(f["timing_precision"] == "word" for f in flags))

    def test_unknown_word_timing_uses_segment_and_does_not_shift(self):
        flags = detect(transcript("hello shit friend", [
            {"word": "hello", "start": 1.1, "end": 1.3},
            {"word": "friend", "start": 3.1, "end": 3.4},
        ]))
        self.assertEqual(flags[0]["timing_precision"], "segment")
        self.assertEqual((flags[0]["start"], flags[0]["end"]), (1, 4))

    def test_phrase_split_between_word_timestamps(self):
        flags = detect(transcript("behen chod", [
            {"word": "behen", "start": 1.1, "end": 1.4},
            {"word": "chod", "start": 1.5, "end": 1.9},
        ]))
        self.assertEqual(len(flags), 1)
        self.assertEqual((flags[0]["start"], flags[0]["end"]), (1.1, 1.9))

    def test_phrase_split_between_segments_but_not_across_long_pause(self):
        value = {"segments": [
            {"start": 1, "end": 2, "text": "behen", "words": []},
            {"start": 2.1, "end": 3, "text": "chod", "words": []},
        ]}
        self.assertEqual(len(detect(value)), 1)
        value["segments"][1]["start"] = 5
        value["segments"][1]["end"] = 6
        self.assertEqual(detect(value), [])

    def test_unicode_normalization_preserves_original_evidence(self):
        flags = detect(transcript("ＦＵＣＫ चु\u200dतिया"))
        self.assertEqual(len(flags), 2)
        self.assertEqual(flags[0]["text"], "ＦＵＣＫ")
        self.assertEqual(flags[1]["text"], "चु\u200dतिया")

    def test_mixed_speech_reports_every_language(self):
        flags = detect(transcript("shit तू चूतिया है અને ગધેડો"))
        self.assertEqual([f["language"] for f in flags], ["en", "hi/gu", "gu"])

    def test_report_scores_profanity_without_bias(self):
        flags = detect(transcript("fuck"))
        report = build_report([], [], [], flags)
        self.assertEqual(report["score"], 80)
        self.assertEqual(report["verdict"], "fix before release")
        self.assertEqual(report["findings"][0]["kind"], "profanity")
        self.assertEqual(build_report([], [], [])["score"], 100)

    def test_empty_transcript(self):
        self.assertEqual(detect({"segments": []}), [])

    def test_requested_phrases_and_native_variants(self):
        for text in ("bhenchod", "behnchod", "भेनचोद", "ભેંચોદ", "બેનચોદ", "fuck you", "f**k you", "bhench*d"):
            with self.subTest(text=text):
                flags = detect(transcript(text))
                self.assertEqual(len(flags), 1)
                self.assertEqual(flags[0]["text"], text)

    def test_full_english_phrase_uses_both_word_timestamps(self):
        flags = detect(transcript("fuck you", [
            {"word": "fuck", "start": 1.1, "end": 1.4},
            {"word": "you", "start": 1.5, "end": 1.9},
        ]))
        self.assertEqual((flags[0]["start"], flags[0]["end"]), (1.1, 1.9))
        self.assertEqual(flags[0]["text"], "fuck you")


if __name__ == "__main__":
    unittest.main()
