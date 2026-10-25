# adlint / OnlyUncensored

Upload a video to review spoken bad words, bias, claims, and disclaimer visibility.

## Run locally

Backend (Python 3.10+):

```powershell
cd backend
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
# Set a Gemini key in .env for bias and claims reviews.
.venv/Scripts/python.exe -m uvicorn app.main:app
```

Frontend, in another terminal:

```powershell
cd frontend
npm install
npm run dev
```

Restart the backend after editing its Python sources. Keeping automatic reload
off while uploading avoids interrupting an in-progress analysis.

## Faster speech checks

Click **Quick setup: bad words only**, choose the main spoken language, and run the
check. This skips frame extraction, visual review, speech AI review, and bias
verification. It works without a Gemini key; the speech model must be available
locally or downloadable on the first run.

When other checks are selected, speech and visual analysis run concurrently.
Bad-word results appear as soon as transcription finishes, while the remaining
review continues. The final report includes timestamped findings, a bad-words
timeline, reviewer actions, and JSON export.

Fast mode defaults to multilingual Whisper `small`, integer quantization on CPU,
a three-beam search, and no repeated temperature fallback passes. Accurate defaults
to `medium` and a wider beam. The Fast model loads in the background at startup
and is reused across uploads. The first model download can still take time.

Configure these in `backend/.env`:

| Variable | Default | Purpose |
| --- | --- | --- |
| `WHISPER_FAST_MODEL` | `small` | Fast speech model; use a multilingual model for Hindi/Gujarati |
| `WHISPER_ACCURATE_MODEL` | `medium` | Larger Accurate speech model, independent of the legacy setting |
| `WHISPER_DEVICE` | `cpu` | Use `cuda` on a host with compatible GPU libraries |
| `WHISPER_COMPUTE_TYPE` | `int8` | Speech inference precision |
| `WHISPER_CPU_THREADS` | Up to 4 | CPU threads per speech model |
| `WHISPER_PRELOAD` | `true` | Warm the Fast model at startup |

`WHISPER_MODEL` remains available for legacy direct transcription calls. It no
longer forces Accurate mode onto the same small model as Fast. Set
`WHISPER_ACCURATE_MODEL` explicitly to override its `medium` default. The first
Accurate run downloads that model if it is not cached and needs more memory than
Fast. Restart the backend after changing environment settings.

Speech options follow the [faster-whisper documentation](https://github.com/SYSTRAN/faster-whisper).

## Bad-word detection coverage

The local vocabulary in `backend/app/profanity.py` covers known English, Hindi,
and Gujarati profanity and insults in native scripts and common Roman spellings.
It handles mixed scripts, Unicode vowel marks, word boundaries, repeated
occurrences, and adjacent multiword phrases. It does not translate audio or send
the vocabulary check to an external API. Supplied scripts remain context for the
AI bias/claims review; bad-word findings come from the audio transcript only.

Auto mode redetects the spoken language across decoding windows; choosing a
language explicitly keeps that language fixed. Recognition uses transcription,
not translation. Every recognized word and its original spelling is retained,
including uncertain words. The speech panel shows uncertain lines separately
with an audio-review label and highlights detected wording without censoring it.
Whole phrases such as `fuck you`, plus Hindi/Gujarati native-script and Roman
variants of `bhenchod`, are matched with their available word timestamps.

Findings use word timestamps where alignment is available, and explicitly label
segment timestamps as approximate otherwise. Shared Hindi/Gujarati terms are
marked `hi/gu`. Vocabulary matches are candidates for human review: quotation,
names, and context can change the meaning. The check cannot catch every spelling,
slur, euphemism, censored word, or word missed by transcription. It does not
automatically mute or edit the video.

When Bias or Claims is enabled, the existing Gemma transcript review also checks
for abusive expressions beyond the vocabulary. Model quotes must match the
transcript near the reported time; invented quotes are rejected and overlapping
findings are not counted twice. Bad-words-only checks remain local.

The finding score is a penalty score, **not an accuracy percentage or a guarantee
that a video is clean**. Empty, partially discarded, low-confidence, and poorly
covered speech produces **review incomplete** with no numeric score. A completed
run without findings says **no flags detected**, rather than **ready**. Possible
profanity in discarded speech is retained as an explicitly uncertain candidate
for listening and review, rather than being silently lost.

For difficult Hindi/Gujarati audio, choose the main language explicitly and try
Accurate mode with the medium model. Mixed spoken languages, music, accents, and
overlapping voices still require checking the transcript. A transcription error
fails the job instead of producing a clean report.

## Validate changes

```powershell
cd backend
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

```powershell
cd frontend
npm test
npm run build
```

Frontend regression tests render completed reports from both older and current
backends, including speech previews with missing bad-word data.
