"""Local, whole-word profanity checks. No network request or translation is needed.

This is an explicit vocabulary, not a guarantee of detecting every abusive phrase.
Keep original evidence and distinguish word timing from segment-level timing.
"""

import unicodedata
from dataclasses import dataclass


@dataclass(frozen=True)
class Term:
    language: str
    severity: str
    variants: str


# Native scripts and common Roman spellings are intentionally kept together.
# Shared Hindi/Gujarati terms are labelled hi/gu rather than guessing a language.
TERMS = (
    Term("en", "high", "fuck you|fuck off|go fuck yourself|f**k you|f*ck you|f*** you|f**k|f*ck|f***"),
    Term("en", "high", "fuck|fucks|fucked|fucker|fuckers|fucking|motherfucker|motherfuckers|motherfucking"),
    Term("en", "medium", "shit|shits|shitty|bullshit|bitch|bitches|bitching|asshole|assholes|arsehole|bastard|bastards|dickhead|dickheads"),
    Term("en", "medium", "idiot|idiots|moron|morons"),
    Term("en", "high", "cunt|cunts|slut|sluts|whore|whores"),
    Term("en", "medium", "dumbass|dumbasses|piss off|pissed off"),
    Term("hi/gu", "high", "madarchod|madarchodd|maderchod|madar chod|motherchod|मादरचोद|मादर चोद|માદરચોદ|માદર ચોદ"),
    Term("hi/gu", "high", "behenchod|bhenchod|bahenchod|behen chod|bhen chod|बहनचोद|बहन चोद|बहनचोद|भेंचोद|બહેનચોદ|બહેન ચોદ|ભેનચોદ"),
    Term("hi/gu", "high", "behnchod|behanchod|bahinchod|behench*d|bhench*d|भेनचोद|भैनचोद|बेहनचोद|बहनचोदो|बहनचोदों|બેનચોદ|બેન ચોદ|ભેંચોદ|બેન્ચોદ|ભેન્ચોદ"),
    Term("hi/gu", "high", "bhosdike|bhosdi ke|bhosadike|bhosadi ke|भोसड़ीके|भोसड़ी के|भोसडीके|भोसडी के|ભોસડીકે|ભોસડી કે"),
    Term("hi/gu", "high", "chutiya|chutiye|chutiyo|chootiya|chutiyaa|चूतिया|चूतिये|चुतिया|चुतिये|ચૂતિયા|ચુતિયા|ચુતીયા|ચુતિયો|ચૂતિયો|ચુતિયાં"),
    Term("hi/gu", "high", "gaand|gand|gandu|gaandu|गांड|गाँड|गांडू|गाँडू|ગાંડ|ગાંડુ|ગાંડૂ"),
    Term("hi/gu", "high", "lund|loda|lauda|lavda|lavdo|लंड|लण्ड|लौड़ा|लवड़ा|લંડ|લવડો|લવડા"),
    Term("hi/gu", "high", "randi|रंडी|રંડી|રાંડ"),
    Term("hi/gu", "high", "bhosdiwale|bhosdiwala|bhosdi wale|bhosdi waale|भोसड़ीवाले|भोसड़ी वाले|भोसडीवाले|भोसडी वाले|ભોસડીના|ભોસડીનો|ભોસડીની"),
    Term("hi/gu", "high", "chutiyapa|chutiyap|chutiyas|chootiye|chutiyon|चुतियापा|चूतियापा|चूतिये|चूतियों|चुतियों|ચુતિયાપા|ચૂતિયાઓ"),
    Term("hi/gu", "high", "chodu|chodna|chudai|chut|choot|laude|lode|bakchod|bakchodi|चोदू|चोदना|चुदाई|चूत|चुत|लौड़े|लौडे|बकचोद|बकचोदी|ચોદુ|ચોદવો"),
    Term("hi/gu", "medium", "harami|haraami|haramkhor|haram khor|हरामी|हरामखोर|हराम खोर|હરામી|હરામખોર|હરામ ખોર"),
    Term("hi/gu", "medium", "kameena|kamina|kamine|kameene|कमीना|कमीने|કમીનો|કમીના"),
    Term("hi", "medium", "bewakoof|bewakuf|bevakoof|बेवकूफ|बेवकूफ़|बेवकूफों"),
    Term("gu", "medium", "gadhedo|gadheda|ગધેડો|ગધેડા|મૂરખ|મૂર્ખ|મુર્ખ|બેવકૂફ|નાલાયક|નાલાયકો"),
)


def _pieces(text: str) -> list[tuple[str, int, int]]:
    """Tokenize without losing Indic vowel marks or original character offsets."""
    out = []
    start = None
    letters = []
    for i, char in enumerate(text):
        category = unicodedata.category(char)
        if category == "Cf":  # Ignore zero-width joiners inside words.
            continue
        if category[0] in "LMN" or (char == "*" and start is not None):
            if start is None:
                start = i
            letters.append(char)
        elif start is not None:
            out.append((unicodedata.normalize("NFKC", "".join(letters)).casefold(), start, i))
            start, letters = None, []
    if start is not None:
        out.append((unicodedata.normalize("NFKC", "".join(letters)).casefold(), start, len(text)))
    return out


_VOCAB = {}
for _term in TERMS:
    for _variant in _term.variants.split("|"):
        _VOCAB[tuple(p[0] for p in _pieces(_variant))] = _term
_LENGTHS = sorted({len(key) for key in _VOCAB}, reverse=True)


def _timed_tokens(transcript: dict) -> list[dict]:
    tokens = []
    for segment_index, segment in enumerate(transcript.get("segments") or []):
        text = segment.get("text") or ""
        pieces = _pieces(text)
        timings = {}
        cursor = 0
        for word in segment.get("words") or []:
            word_pieces = _pieces(word.get("word") or "")
            for value, _, _ in word_pieces:
                index = next((i for i in range(cursor, len(pieces)) if pieces[i][0] == value), None)
                if index is not None:
                    timings[index] = (word["start"], word["end"])
                    cursor = index + 1
        for index, (value, lo, hi) in enumerate(pieces):
            precise = index in timings
            start, end = timings.get(index, (segment["start"], segment["end"]))
            tokens.append({
                "value": value, "evidence": text[lo:hi], "start": start, "end": end,
                "precise": precise, "segment": segment_index,
                "segment_start": segment["start"], "segment_end": segment["end"],
            })
    return tokens


def detect(transcript: dict) -> list[dict]:
    """Find every occurrence, including phrases split across adjacent segments."""
    tokens = _timed_tokens(transcript)

    flags = []
    i = 0
    while i < len(tokens):
        for length in _LENGTHS:
            group = tokens[i:i + length]
            if len(group) != length:
                continue
            term = _VOCAB.get(tuple(t["value"] for t in group))
            if term is None:
                continue
            if any(b["segment"] != a["segment"] and b["start"] - a["end"] > 1.0 for a, b in zip(group, group[1:])):
                continue
            flags.append({
                "start": round(float(group[0]["start"]), 2),
                "end": round(float(group[-1]["end"]), 2),
                "text": " ".join(t["evidence"] for t in group),
                "language": term.language,
                "severity": term.severity,
                "source": "speech",
                "timing_precision": "word" if all(t["precise"] for t in group) else "segment",
                "why": "Known profanity or insult in the transcript. Review the surrounding speech for context.",
                "suggested_fix": "Mute, bleep, or replace this wording before publishing.",
            })
            i += length
            break
        else:
            i += 1
    return flags


def detect_with_uncertain(transcript: dict) -> list[dict]:
    flags = detect(transcript)
    # Preserve possible profanity as an explicitly uncertain review candidate.
    for flag in detect({"segments": transcript.get("uncertain_segments") or []}):
        flags.append({**flag, "uncertain": True, "why": "Possible profanity in low-confidence speech. Listen to this moment to confirm the wording."})
    return sorted(flags, key=lambda f: f["start"])


def merge_contextual(local: list[dict], candidates: list[dict], transcript: dict) -> list[dict]:
    """Accept only model quotes present in the transcript near the claimed time.

    Derive timestamps from ASR evidence, and do not charge twice when a model
    quotes a longer phrase containing an existing dictionary match.
    """
    out = list(local)
    tokens = _timed_tokens(transcript)
    for candidate in candidates:
        if not isinstance(candidate, dict) or not isinstance(candidate.get("text"), str):
            continue
        phrase = tuple(p[0] for p in _pieces(candidate["text"]))
        if not 1 <= len(phrase) <= 12:
            continue
        try:
            proposed = float(candidate["start"])
        except (KeyError, ValueError, TypeError):
            continue
        matches = []
        for i in range(len(tokens) - len(phrase) + 1):
            group = tokens[i:i + len(phrase)]
            if tuple(t["value"] for t in group) != phrase:
                continue
            if not group[0]["segment_start"] - 0.5 <= proposed <= group[-1]["segment_end"] + 0.5:
                continue
            if any(b["segment"] != a["segment"] and b["start"] - a["end"] > 1 for a, b in zip(group, group[1:])):
                continue
            matches.append(group)
        if not matches:
            continue
        group = min(matches, key=lambda g: abs(g[0]["start"] - proposed))
        start, end = float(group[0]["start"]), float(group[-1]["end"])
        if any(start <= f["end"] and end >= f["start"] for f in out):
            continue
        language = candidate.get("language")
        out.append({
            "start": round(start, 2), "end": round(end, 2),
            "text": " ".join(t["evidence"] for t in group),
            "language": language if language in {"hi", "en", "gu", "hi/gu"} else transcript.get("language") or "unknown",
            "severity": candidate.get("severity") if candidate.get("severity") in {"low", "medium", "high"} else "medium",
            "source": "speech", "detector": "gemma",
            "timing_precision": "word" if all(t["precise"] for t in group) else "segment",
            "why": str(candidate.get("why") or "Potential abusive language identified in the transcript. Review the context."),
            "suggested_fix": "Mute, bleep, or replace this wording before publishing.",
        })
    return sorted(out, key=lambda f: f["start"])
