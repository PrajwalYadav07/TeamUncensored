import { Component, useEffect, useMemo, useRef, useState, type ErrorInfo, type MouseEvent, type ReactNode } from "react";
import type {
  BiasFlag,
  Claim,
  DisclaimerSpan,
  Finding,
  Job,
  Mode,
  ProfanityFlag,
  Report,
  ReviewMark,
  Severity,
  Stage,
} from "./types";

const LANGS = [
  { id: "auto", label: "Auto" },
  { id: "hi", label: "Hindi" },
  { id: "en", label: "English" },
  { id: "gu", label: "Gujarati" },
];

const BIAS_LANES = [
  { key: "colourism", label: "colourism" },
  { key: "gender_stereotype", label: "gender" },
  { key: "body_shaming", label: "body" },
  { key: "caste_or_community", label: "caste / community" },
  { key: "regional_stereotype", label: "regional" },
  { key: "religious_stereotype", label: "religious" },
  { key: "age_or_disability", label: "age / disability" },
] as const;

const API = (import.meta.env.VITE_API_URL ?? "").replace(/\/$/, "");

const SEV_PENALTY: Record<Severity, number> = { high: 20, medium: 12, low: 5 };

function fmt(s: number) {
  if (!Number.isFinite(s) || s < 0) s = 0;
  const m = Math.floor(s / 60);
  const sec = s - m * 60;
  return `${String(m).padStart(2, "0")}:${sec.toFixed(1).padStart(4, "0")}`;
}

function errMsg(data: unknown, status: number) {
  if (data && typeof data === "object" && "detail" in data) {
    const d = (data as { detail: unknown }).detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) return d.map((x) => (x && x.msg) || JSON.stringify(x)).join("; ");
  }
  return `Request failed (${status})`;
}

function laneOf(category: string) {
  const c = (category || "").toLowerCase();
  return BIAS_LANES.find((l) => c === l.key || c.startsWith(l.key.split("_")[0]))?.key;
}

function speechWarnings(report: Report) {
  const reasons = [...(report.speech_assessment?.reasons ?? [])];
  if (report.speech_assessment?.status === "needs_review" && !reasons.length) reasons.push("The speech review is incomplete.");
  if (!report.transcript.segments.length) reasons.push("No clear speech was transcribed. Spoken content could not be checked.");
  if (report.settings.check_profanity !== false && report.profanity_flags == null) reasons.push("Bad-word results were not included in this report. Run a new check with the updated backend.");
  if (report.transcript.discarded_segments) reasons.push("Some speech was discarded because transcription confidence was low.");
  if (report.transcript.language_probability != null && report.transcript.language_probability < 0.65) reasons.push("The spoken language was uncertain. Choose Hindi, English, or Gujarati explicitly and recheck the transcript.");
  if (report.transcript.word_probability != null && report.transcript.word_probability < 0.65) reasons.push("The speech transcript contains uncertain words. Review it against the audio.");
  return [...new Set(reasons)];
}

function rescore(report: Report, marks: Record<string, ReviewMark>) {
  const findings = report.findings;
  let score = 100;
  let hasHigh = false;
  for (const f of findings) {
    if (marks[f.id] === "false_positive") continue;
    if (f.severity === "high") hasHigh = true;
    if (f.kind === "bias" || f.kind === "profanity") score -= SEV_PENALTY[f.severity] ?? 12;
    else if (f.kind === "claim") score -= 10;
    else if (f.kind === "disclaimer") {
      const issues = (f.detail as DisclaimerSpan).issues ?? [];
      if (issues.includes("too_short")) score -= 10;
      if (issues.includes("too_small")) score -= 8;
    }
  }
  score = Math.max(0, score);
  const warnings = speechWarnings(report);
  if (warnings.length || report.score === null) return { score: null, verdict: "review incomplete" };
  const verdict = score >= 85 && !hasHigh ? (findings.some((f) => marks[f.id] !== "false_positive") ? "review findings" : "no flags detected") : score >= 60 ? "fix before release" : "high risk";
  return { score, verdict };
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>("fast");
  const [language, setLanguage] = useState("auto");
  const [script, setScript] = useState("");
  const [checkBias, setCheckBias] = useState(true);
  const [checkClaims, setCheckClaims] = useState(true);
  const [checkProfanity, setCheckProfanity] = useState(true);
  const [recheck, setRecheck] = useState(true);
  const [minSec, setMinSec] = useState(2);
  const [minH, setMinH] = useState(2.5);
  const [wps, setWps] = useState(3);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [posting, setPosting] = useState(false);
  const [marks, setMarks] = useState<Record<string, ReviewMark>>({});
  const [entered, setEntered] = useState(false);

  useEffect(() => {
    if (!file) {
      setVideoUrl(null);
      return;
    }
    const url = URL.createObjectURL(file);
    setVideoUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (!job || job.status !== "running") return;
    let stop = false;
    let timer = 0;
    const tick = async () => {
      try {
        const res = await fetch(`${API}/api/jobs/${job.id}`);
        const data = await res.json().catch(() => ({}));
        if (stop) return;
        if (!res.ok) throw new Error(errMsg(data, res.status));
        setJob(data as Job);
        if ((data as Job).status === "running") timer = window.setTimeout(tick, 500);
      } catch (e) {
        if (!stop) setError(e instanceof Error ? e.message : String(e));
      }
    };
    timer = window.setTimeout(tick, 400);
    return () => {
      stop = true;
      window.clearTimeout(timer);
    };
  }, [job?.id, job?.status]);

  async function run() {
    if (!file) return;
    if (!checkBias && !checkClaims && !checkProfanity) {
      setError("Select at least one check.");
      return;
    }
    setPosting(true);
    setError(null);
    setJob(null);
    setMarks({});
    const body = new FormData();
    body.append("video", file);
    body.append("mode", mode);
    body.append("language", language);
    body.append("script", script);
    body.append("check_bias", String(checkBias));
    body.append("check_claims", String(checkClaims));
    body.append("check_profanity", String(checkProfanity));
    body.append("recheck", String(recheck));
    body.append("min_disclaimer_seconds", String(minSec));
    body.append("min_text_height_pct", String(minH));
    body.append("reading_words_per_sec", String(wps));
    try {
      const res = await fetch(`${API}/api/jobs`, { method: "POST", body });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(errMsg(data, res.status));
      setJob(data as Job);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setPosting(false);
    }
  }

  function reset() {
    setJob(null);
    setError(null);
    setMarks({});
  }

  const report = job?.result ?? null;
  const reviewing = Boolean(report && videoUrl);
  const running = posting || job?.status === "running";

  if (!entered) {
    return (
      <div className="shell">
        <Gate onEnter={() => setEntered(true)} />
      </div>
    );
  }

  return (
    <div className="shell">
      {reviewing ? (
        <ReviewBoundary key={job?.id} onReset={reset} onExport={() => exportJson(report!, marks, job)}>
        <Review
          report={report!}
          videoUrl={videoUrl!}
          marks={marks}
          setMarks={setMarks}
          stages={job?.stages ?? []}
          onNew={reset}
          onExport={() => exportJson(report!, marks, job)}
          onHome={() => setEntered(false)}
        />
        </ReviewBoundary>
      ) : (
        <div className="workspace setup">
          <div className="setup-inner">
            <div className="desk-head">
              <button type="button" className="name-btn" onClick={() => setEntered(false)}>
                OnlyUncensored
              </button>
              {file && <span className="file-name">{file.name}</span>}
              {job && <span className={`st st-${job.status}`}>{job.status}</span>}
            </div>
            <UploadPane file={file} videoUrl={videoUrl} onFile={setFile} onSample={() => void loadSample(setFile, setError)} />
            <aside className="side-form">
              {running || job?.status === "error" ? (
                <>
                  <StageList stages={job?.stages ?? []} error={job?.error || error} posting={posting && !job} />
                  {job?.status === "error" && <button type="button" className="ghost retry" onClick={reset}>Back to settings</button>}
                </>
              ) : (
                <CheckForm
                  mode={mode}
                  setMode={setMode}
                  language={language}
                  setLanguage={setLanguage}
                  script={script}
                  setScript={setScript}
                  checkBias={checkBias}
                  setCheckBias={setCheckBias}
                  checkClaims={checkClaims}
                  setCheckClaims={setCheckClaims}
                  checkProfanity={checkProfanity}
                  setCheckProfanity={setCheckProfanity}
                  recheck={recheck}
                  setRecheck={setRecheck}
                  minSec={minSec}
                  setMinSec={setMinSec}
                  minH={minH}
                  setMinH={setMinH}
                  wps={wps}
                  setWps={setWps}
                  disabled={!file || posting}
                  error={error}
                  onRun={run}
                />
              )}
              {job?.preview && checkProfanity && (
                <SpeechPreview preview={job.preview} />
              )}
            </aside>
          </div>
        </div>
      )}
    </div>
  );
}

export function SpeechPreview({ preview }: { preview: NonNullable<Job["preview"]> }) {
  const flags = preview.profanity_flags ?? [];
  return (
    <section className="speech-preview" aria-live="polite">
      <h2>Speech results</h2>
      <p className="hint">See the stages above for the full review status.</p>
      {preview.speech_assessment?.status === "needs_review" && <p className="error">Speech review is incomplete. Check the transcript against the audio.</p>}
      {preview.profanity_flags == null ? (
        <p>Bad-word results are not available yet.</p>
      ) : flags.length ? (
        <ul>
          {flags.map((flag, i) => (
            <li key={i}><span className="mono">{fmt(flag.start)}</span> · {flag.text} · {flag.language}</li>
          ))}
        </ul>
      ) : (
        <p>{preview.transcript?.segments?.length ? "No known bad words found in the transcript." : "No clear speech detected; bad-word detection could not assess spoken content."}</p>
      )}
    </section>
  );
}

class ReviewBoundary extends Component<{
  children: ReactNode;
  onReset: () => void;
  onExport: () => void;
}, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Could not display the analysis report", error, info.componentStack);
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <section className="setup-inner" role="alert">
        <h1>Could not display this report</h1>
        <p>The analysis finished, but a display error prevented the report from opening. You can still download the results.</p>
        <button type="button" className="ghost" onClick={this.props.onExport}>Download results</button>{" "}
        <button type="button" className="ghost" onClick={this.props.onReset}>Back to settings</button>
      </section>
    );
  }
}

function Gate({ onEnter }: { onEnter: () => void }) {
  return (
    <section className="gate">
      <header className="intro-brand">OnlyUncensored<span>Video review, made clearer.</span></header>
      <div className="intro-body">
        <div className="mast">
          <p className="mast-kicker">A closer look before you publish</p>
          <h1>Check your video.<br /><span>Before you share it.</span></h1>
          <p className="mast-line">
            Find bad words, potential bias, and claims that need a second look.
            Upload your video and get a clear report showing what to review and exactly where to find it.
          </p>
          <button type="button" className="enter" onClick={onEnter}>Check a video <span aria-hidden="true">↗</span></button>
          <p className="intro-languages">Hindi · English · Gujarati</p>
        </div>
        <div className="intro-features">
          <section><span className="intro-number">01 / SPEECH</span><h2>Hear what matters.</h2><p>Turn speech into a transcript and flag known bad words in three languages.</p></section>
          <section><span className="intro-number">02 / CONTENT</span><h2>Look a little closer.</h2><p>Review potential bias, product claims, and disclaimers that may be too small or too brief.</p></section>
          <section><span className="intro-number">03 / RESULTS</span><h2>Go straight to the moment.</h2><p>Use timestamps to inspect each finding, review the context, and export your report.</p></section>
        </div>
      </div>
    </section>
  );
}

function exportJson(report: Report, marks: Record<string, ReviewMark>, job: Job | null) {
  const scored = rescore(report, marks);
  const blob = new Blob(
    [
      JSON.stringify(
        {
          job_id: job?.id,
          ...report,
          review: marks,
          score_adjusted: scored.score,
          verdict_adjusted: scored.verdict,
          review_warnings: speechWarnings(report),
        },
        null,
        2,
      ),
    ],
    { type: "application/json" },
  );
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `onlyuncensored-${job?.id ?? "report"}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

async function loadSample(onFile: (f: File) => void, onError: (s: string) => void) {
  try {
    const res = await fetch("/sample-ad.mp4");
    if (!res.ok) throw new Error("Sample ad failed to load");
    const blob = await res.blob();
    onFile(new File([blob], "Cheerios-V8-1960.mp4", { type: "video/mp4" }));
  } catch (e) {
    onError(e instanceof Error ? e.message : String(e));
  }
}

function UploadPane({
  file,
  videoUrl,
  onFile,
  onSample,
}: {
  file: File | null;
  videoUrl: string | null;
  onFile: (f: File | null) => void;
  onSample: () => void;
}) {
  const [over, setOver] = useState(false);
  const take = (list: FileList | null) => {
    const f = list?.[0];
    if (f) onFile(f);
  };
  return (
    <section className="pane ingest">
      <div
        className={`drop ${over ? "over" : ""} ${file ? "has" : ""}`}
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          take(e.dataTransfer.files);
        }}
      >
        {videoUrl ? (
          <video src={videoUrl} controls preload="metadata" />
        ) : (
          <div className="drop-lab">
            <label>
              <input type="file" accept="video/*" onChange={(e) => take(e.target.files)} />
              <span className="drop-kicker">Video</span>
              <span>Drop an ad file here, or click to choose.</span>
              <span className="muted">mp4 / mov · up to 200 MB</span>
            </label>
            <button type="button" className="sample-link" onClick={onSample}>
              Use the 1960 Cheerios / V-8 ad
            </button>
          </div>
        )}
      </div>
      {file && (
        <div className="ingest-bar">
          <span className="mono">{file.name}</span>
          <span className="muted">{(file.size / 1e6).toFixed(1)} MB</span>
          <label className="link">
            Replace
            <input type="file" accept="video/*" onChange={(e) => take(e.target.files)} />
          </label>
        </div>
      )}
    </section>
  );
}

function CheckForm(props: {
  mode: Mode;
  setMode: (m: Mode) => void;
  language: string;
  setLanguage: (s: string) => void;
  script: string;
  setScript: (s: string) => void;
  checkBias: boolean;
  setCheckBias: (v: boolean) => void;
  checkClaims: boolean;
  setCheckClaims: (v: boolean) => void;
  checkProfanity: boolean;
  setCheckProfanity: (v: boolean) => void;
  recheck: boolean;
  setRecheck: (v: boolean) => void;
  minSec: number;
  setMinSec: (n: number) => void;
  minH: number;
  setMinH: (n: number) => void;
  wps: number;
  setWps: (n: number) => void;
  disabled: boolean;
  error: string | null;
  onRun: () => void;
}) {
  return (
    <form
      className="form"
      onSubmit={(e) => {
        e.preventDefault();
        props.onRun();
      }}
    >
      <h1>New check</h1>

      <fieldset>
        <legend>Mode</legend>
        <div className="seg">
          {(["fast", "accurate"] as const).map((m) => (
            <button key={m} type="button" className={props.mode === m ? "on" : ""} onClick={() => props.setMode(m)}>
              {m === "fast" ? "Fast" : "Accurate"}
            </button>
          ))}
        </div>
        <p className="hint">{props.mode === "fast" ? "Speed-optimized speech decoding and quicker review." : "More thorough speech decoding and deeper review. Try this for difficult regional speech."}</p>
      </fieldset>

      <label className="field">
        Language
        <select value={props.language} onChange={(e) => props.setLanguage(e.target.value)}>
          {LANGS.map((l) => (
            <option key={l.id} value={l.id}>
              {l.label}
            </option>
          ))}
        </select>
        <span className="hint">Choose the main spoken language if Auto misses Hindi or Gujarati words.</span>
      </label>

      <fieldset>
        <legend>Checks</legend>
        <button type="button" className="ghost" onClick={() => {
          props.setCheckProfanity(true);
          props.setCheckBias(false);
          props.setCheckClaims(false);
          props.setMode("fast");
        }}>Quick setup: bad words only</button>
        <label className="chk">
          <input type="checkbox" checked={props.checkProfanity} onChange={(e) => props.setCheckProfanity(e.target.checked)} />
          Bad words · Hindi, English &amp; Gujarati
        </label>
        <label className="chk">
          <input type="checkbox" checked={props.checkBias} onChange={(e) => props.setCheckBias(e.target.checked)} />
          Bias
        </label>
        <label className="chk">
          <input type="checkbox" checked={props.checkClaims} onChange={(e) => props.setCheckClaims(e.target.checked)} />
          Claims
        </label>
        <label className="chk">
          <input type="checkbox" checked={props.recheck} disabled={!props.checkBias} onChange={(e) => props.setRecheck(e.target.checked)} />
          Recheck bias flags
        </label>
        <p className="hint">Bad words only uses a local vocabulary scan. With Bias or Claims enabled, the existing speech review also checks context. Review the transcript for missed speech.</p>
      </fieldset>

      <fieldset>
        <legend>Disclaimer rules</legend>
        <div className="nums">
          <label>
            Min seconds
            <input type="number" min={0} step={0.1} value={props.minSec} onChange={(e) => props.setMinSec(+e.target.value)} />
          </label>
          <label>
            Min height %
            <input type="number" min={0} step={0.1} value={props.minH} onChange={(e) => props.setMinH(+e.target.value)} />
          </label>
          <label>
            Reading wps
            <input type="number" min={0.1} step={0.1} value={props.wps} onChange={(e) => props.setWps(+e.target.value)} />
          </label>
        </div>
      </fieldset>

      <label className="field">
        Script
        <textarea
          rows={3}
          value={props.script}
          onChange={(e) => props.setScript(e.target.value)}
          placeholder="Optional voiceover / super text"
        />
      </label>

      {props.error && <p className="error">{props.error}</p>}

      <button type="submit" className="run" disabled={props.disabled}>
        Run check
      </button>
    </form>
  );
}

function StageList({ stages, error, posting }: { stages: Stage[]; error: string | null; posting: boolean }) {
  const weights: Record<string, number> = {
    frames: 10,
    transcribe: 18,
    profanity: 2,
    visual: 40,
    speech: 16,
    recheck: 12,
    report: 4,
  };
  let pct = posting ? 6 : 0;
  let label = posting ? "Sending the file" : "Starting";
  if (stages.length) {
    let total = 0;
    let got = 0;
    for (const s of stages) {
      const w = weights[s.key] ?? 8;
      total += w;
      if (s.state === "done" || s.state === "skipped") got += w;
      else if (s.state === "running") {
        got += w * 0.45;
        label = s.label;
      } else if (s.state === "error") label = s.label;
    }
    const active = stages.find((s) => s.state === "running");
    if (active) label = active.label;
    pct = total ? Math.min(error ? 100 : 99, Math.round((got / total) * 100)) : pct;
  }
  return (
    <div className="stages">
      <div className="runbar">
        <div className="runbar-top">
          <span>{error ? "Stopped" : label}</span>
          <span className="mono">{pct}%</span>
        </div>
        <div className={`runbar-track ${error ? "bad" : ""}`}>
          <i style={{ width: `${pct}%` }} />
        </div>
      </div>
      <ol>
        {stages.map((s) => (
          <li key={s.key} className={`sg sg-${s.state}`}>
            <i />
            <span>{s.label}</span>
            <span className="mono">
              {s.state === "running" ? "…" : s.seconds != null ? `${s.seconds.toFixed(1)}s` : s.state}
            </span>
          </li>
        ))}
      </ol>
      {error && <p className="error">{error}</p>}
    </div>
  );
}

export function Review({
  report,
  videoUrl,
  marks,
  setMarks,
  stages,
  onNew,
  onExport,
  onHome,
}: {
  report: Report;
  videoUrl: string;
  marks: Record<string, ReviewMark>;
  setMarks: (m: Record<string, ReviewMark>) => void;
  stages: Stage[];
  onNew: () => void;
  onExport: () => void;
  onHome: () => void;
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [now, setNow] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const duration = report.video.duration || 1;
  const scored = useMemo(() => rescore(report, marks), [report, marks]);
  const warnings = speechWarnings(report);

  const seek = (t: number, id?: string) => {
    const v = videoRef.current;
    if (v) {
      v.currentTime = t;
      v.pause();
    }
    setNow(t);
    if (id) setSelected(id);
  };

  const mark = (id: string, next: ReviewMark) => {
    setMarks({ ...marks, [id]: marks[id] === next ? "open" : next });
  };

  const visible = report.disclaimers.filter((d) => now >= d.start && now <= d.end);
  const counts = {
    open: report.findings.filter((f) => (marks[f.id] ?? "open") === "open").length,
    approved: report.findings.filter((f) => marks[f.id] === "approved").length,
    fp: report.findings.filter((f) => marks[f.id] === "false_positive").length,
  };

  return (
    <div className="workspace review">
      <aside className="rail">
        <section className="pane player">
          <div
            className="video-wrap"
            style={{
              aspectRatio: report.video.width && report.video.height ? `${report.video.width} / ${report.video.height}` : "16 / 9",
            }}
          >
            <video
              ref={videoRef}
              src={videoUrl}
              controls
              onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)}
            />
            {visible.map((d, i) => {
              const [ymin, xmin, ymax, xmax] = d.box_2d;
              return (
                <div
                  key={i}
                  className={`obox ${d.issues.length ? "bad" : "ok"}`}
                  style={{
                    top: `${ymin / 10}%`,
                    left: `${xmin / 10}%`,
                    height: `${(ymax - ymin) / 10}%`,
                    width: `${(xmax - xmin) / 10}%`,
                  }}
                >
                  <span className="mono">
                    {d.duration}s · {d.text_height_pct}%
                  </span>
                </div>
              );
            })}
          </div>
          <div className="clock">
            <span className="mono">{fmt(now)}</span>
            <span className="muted">/</span>
            <span className="mono muted">{fmt(duration)}</span>
          </div>
        </section>

        <Lanes report={report} marks={marks} now={now} selected={selected} duration={duration} onSeek={seek} />

        <section className="pane speech">
          <h2>Speech</h2>
          <TranscriptPane report={report} now={now} onSeek={seek} />
        </section>
        <details className="run-fold">
          <summary>Run details</summary>
          <RunPane report={report} stages={stages} />
        </details>
      </aside>

      <section className="output">
        <div className={`scoreboard v-${scored.verdict.replace(/\s+/g, "-")}`}>
          <div>
            <p className="kicker">Finding score</p>
            <strong>{scored.score ?? "—"}</strong>
            <span>{scored.verdict}</span>
            <p className="hint">Based on detected findings, not an accuracy percentage.</p>
            {scored.score != null && scored.score !== report.score && report.score != null && <em>was {report.score}</em>}
          </div>
          <div className="score-side">
            <div className="tally">
              <span>{counts.open} open</span>
              <span>{counts.approved} approved</span>
              <span>{counts.fp} false pos.</span>
            </div>
            <div className="score-actions">
              <button type="button" className="ghost" onClick={onExport}>
                Export JSON
              </button>
              <button type="button" className="ghost" onClick={onNew}>
                New check
              </button>
              <button type="button" className="ghost" onClick={onHome}>
                OnlyUncensored
              </button>
            </div>
          </div>
        </div>
        <div className="finding-list">
          {warnings.length > 0 && <section className="review-warnings" role="status"><h2>Speech needs review</h2><ul>{warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul><p>Try selecting Hindi or Gujarati explicitly and use Accurate mode for difficult speech.</p></section>}
          {report.findings.length === 0 && <p className="muted empty">{warnings.length ? "No findings from the completed checks. The speech review is incomplete." : "No flags detected in the analyzed content. Review the transcript for missed words."}</p>}
          {report.findings.map((f) => (
            <FindingCard
              key={f.id}
              f={f}
              mark={marks[f.id] ?? "open"}
              selected={selected === f.id}
              onSeek={() => seek(f.start, f.id)}
              onMark={(m) => mark(f.id, m)}
            />
          ))}
        </div>
        {report.claims.length > 0 && (
          <div className="claims-block">
            <h2>Claims</h2>
            <ClaimsPane report={report} onSeek={seek} />
          </div>
        )}
      </section>
    </div>
  );
}

function Lanes({
  report,
  marks,
  now,
  selected,
  duration,
  onSeek,
}: {
  report: Report;
  marks: Record<string, ReviewMark>;
  now: number;
  selected: string | null;
  duration: number;
  onSeek: (t: number, id?: string) => void;
}) {
  const tracksRef = useRef<HTMLDivElement>(null);
  const biasLanes = report.settings.check_bias ? BIAS_LANES : [];
  const pct = (t: number) => `${Math.min(100, Math.max(0, (t / duration) * 100))}%`;
  const width = (a: number, b: number) => `${Math.max(0.6, ((Math.max(b, a) - a) / duration) * 100)}%`;

  const clickTrack = (e: MouseEvent<HTMLDivElement>) => {
    const el = tracksRef.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    onSeek(((e.clientX - r.left) / r.width) * duration);
  };

  const buckets = 72;
  const density = Array.from({ length: buckets }, () => 0);
  for (const f of report.findings) {
    if (marks[f.id] === "false_positive") continue;
    const i = Math.min(buckets - 1, Math.floor((f.start / duration) * buckets));
    density[i] += f.severity === "high" ? 3 : f.severity === "medium" ? 2 : 1;
  }
  const peak = Math.max(1, ...density);

  return (
    <section className="pane lanes">
      <div className="lane-labs">
        {biasLanes.map((l) => (
          <div key={l.key} className="lab">
            <i className={`cdot c-${l.key}`} />
            {l.label}
          </div>
        ))}
        {report.settings.check_profanity && <div className="lab"><i className="cdot c-profanity" />bad words</div>}
        {report.settings.check_claims && <>
        <div className="lab">
          <i className="cdot c-claim" />
          claims
        </div>
        <div className="lab">
          <i className="cdot c-disc" />
          disclaimers
        </div>
        </>}
        <div className="lab dens">risk density</div>
      </div>
      <div className="lane-tracks" ref={tracksRef} onClick={clickTrack}>
        {biasLanes.map((l) => (
          <div key={l.key} className="track">
            {report.bias_flags
              .filter((f) => laneOf(f.category) === l.key)
              .map((f, i) => {
                const finding = report.findings.find(
                  (x) => x.kind === "bias" && x.start === f.start && (x.detail as BiasFlag).category === f.category,
                );
                const fp = finding && marks[finding.id] === "false_positive";
                return (
                  <button
                    key={i}
                    type="button"
                    className={`span c-${l.key} ${fp ? "fp" : ""} ${selected === finding?.id ? "sel" : ""}`}
                    style={{ left: pct(f.start), width: width(f.start, f.end) }}
                    title={`${fmt(f.start)} ${f.category}`}
                    onClick={(e) => {
                      e.stopPropagation();
                      onSeek(f.start, finding?.id);
                    }}
                  />
                );
              })}
          </div>
        ))}
        {report.settings.check_profanity && <div className="track">
          {report.findings.filter((f) => f.kind === "profanity").map((f) => (
            <button
              key={f.id}
              type="button"
              className={`span c-profanity ${marks[f.id] === "false_positive" ? "fp" : ""} ${selected === f.id ? "sel" : ""}`}
              style={{ left: pct(f.start), width: width(f.start, f.end) }}
              title={`${fmt(f.start)} ${(f.detail as ProfanityFlag).text}`}
              onClick={(e) => { e.stopPropagation(); onSeek(f.start, f.id); }}
            />
          ))}
        </div>}
        {report.settings.check_claims && <>
        <div className="track">
          {report.claims.map((c, i) => (
            <button
              key={i}
              type="button"
              className={`tick c-claim ${c.supported ? "ok" : ""}`}
              style={{ left: pct(c.time) }}
              title={`${fmt(c.time)} ${c.text}`}
              onClick={(e) => {
                e.stopPropagation();
                onSeek(c.time);
              }}
            />
          ))}
        </div>
        <div className="track">
          {report.disclaimers.map((d, i) => (
            <button
              key={i}
              type="button"
              className={`span c-disc ${d.issues.length ? "bad" : "ok"}`}
              style={{ left: pct(d.start), width: width(d.start, d.end) }}
              title={`${fmt(d.start)}–${fmt(d.end)}`}
              onClick={(e) => {
                e.stopPropagation();
                onSeek(d.start);
              }}
            />
          ))}
        </div>
        </>}
        <div className="track density">
          {density.map((n, i) => (
            <i key={i} style={{ height: `${(n / peak) * 100}%`, opacity: n ? 0.9 : 0.15 }} />
          ))}
        </div>
        <div className="playhead" style={{ left: pct(now) }} />
      </div>
    </section>
  );
}

function FindingCard({
  f,
  mark,
  selected,
  onSeek,
  onMark,
}: {
  f: Finding;
  mark: ReviewMark;
  selected: boolean;
  onSeek: () => void;
  onMark: (m: ReviewMark) => void;
}) {
  return (
    <article className={`finding k-${f.kind} ${f.severity} ${selected ? "sel" : ""} ${mark}`}>
      <header>
        <button type="button" className="ts" onClick={onSeek}>
          {fmt(f.start)}
          {f.end > f.start ? `–${fmt(f.end)}` : ""}
        </button>
        <strong>{f.title}</strong>
        <span className={`pill ${f.severity}`}>{f.severity}</span>
      </header>
      {f.kind === "bias" && <BiasBody d={f.detail as BiasFlag} />}
      {f.kind === "profanity" && <ProfanityBody d={f.detail as ProfanityFlag} />}
      {f.kind === "claim" && <ClaimBody d={f.detail as Claim} />}
      {f.kind === "disclaimer" && <DisclaimerBody d={f.detail as DisclaimerSpan} />}
      <footer>
        <button type="button" className={mark === "approved" ? "on" : ""} onClick={() => onMark("approved")}>
          Approve
        </button>
        <button type="button" className={mark === "false_positive" ? "on" : ""} onClick={() => onMark("false_positive")}>
          False positive
        </button>
      </footer>
    </article>
  );
}

function BiasBody({ d }: { d: BiasFlag }) {
  return (
    <div className="body">
      <p>{d.evidence}</p>
      <p className="muted">{d.why}</p>
      <p>
        <span className="k">Fix</span> {d.suggested_fix}
      </p>
      <p className="meta">
        {(d.source || "").replace(/_/g, " ")} · {Math.round((d.confidence ?? 0) * 100)}%
        {d.verified ? ` · recheck: ${d.verify_reason}` : ""}
      </p>
    </div>
  );
}

function ProfanityBody({ d }: { d: ProfanityFlag }) {
  return (
    <div className="body">
      <p><mark>{d.text}</mark></p>
      <p className="muted">{d.why}</p>
      <p><span className="k">Fix</span> {d.suggested_fix}</p>
      <p className="meta">{d.language} · {d.timing_precision === "word" ? "word timestamps" : "approximate segment timestamps"}{d.uncertain ? " · uncertain speech: confirm against audio" : ""}{d.detector === "gemma" ? " · contextual review" : ""}</p>
    </div>
  );
}

function ClaimBody({ d }: { d: Claim }) {
  return (
    <div className="body">
      <p>“{d.text}”</p>
      <p className="meta">
        {(d.source || "").replace(/_/g, " ")} · {(d.claim_type || "").replace(/_/g, " ")}
        {d.needs_disclaimer ? " · needs disclaimer" : ""}
      </p>
    </div>
  );
}

function DisclaimerBody({ d }: { d: DisclaimerSpan }) {
  return (
    <div className="body">
      <p>“{d.text}”</p>
      <p className="meta">
        on screen {d.duration}s, read time {d.required_duration}s · height {d.text_height_pct}% (min {d.min_text_height_pct}%)
      </p>
    </div>
  );
}

function TranscriptPane({ report, now, onSeek }: { report: Report; now: number; onSeek: (t: number) => void }) {
  const speechClaims = report.claims.filter((c) => c.source === "speech");
  const segments = [
    ...report.transcript.segments.map((segment) => ({ ...segment, uncertain: false })),
    ...(report.transcript.uncertain_segments ?? []).map((segment) => ({ ...segment, uncertain: true })),
  ].sort((a, b) => a.start - b.start);
  if (!segments.length) {
    return <p className="muted empty">{report.transcript.note || report.transcript.error || "No clear speech in this video."}</p>;
  }
  return (
    <div className="transcript">
      {report.transcript.language && <p className="meta">{report.transcript.language}</p>}
      {segments.map((s, i) => {
        const flags = (report.profanity_flags ?? []).filter((f) => f.start < s.end && f.end > s.start);
        const hit = speechClaims.some((c) => c.time >= s.start - 0.5 && c.time <= s.end + 0.5)
          || flags.length > 0;
        const live = now >= s.start && now <= s.end;
        return (
          <p key={i} className={`speech-line ${hit ? "hit" : ""} ${live ? "live" : ""} ${s.uncertain ? "uncertain" : ""}`}>
            <button type="button" className="ts" onClick={() => onSeek(s.start)}>
              {fmt(s.start)}
            </button>
            {markSpeech(s.text, flags)}
            {s.uncertain && <span className="speech-confidence">Uncertain speech · check audio</span>}
          </p>
        );
      })}
    </div>
  );
}

function markSpeech(text: string, flags: ProfanityFlag[]) {
  const phrases = [...new Set(flags.map((flag) => flag.text.trim()).filter(Boolean))]
    .sort((a, b) => b.length - a.length)
    .map((phrase) => phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&").replace(/\s+/g, "\\s+"));
  if (!phrases.length) return text;
  return text.split(new RegExp(`(${phrases.join("|")})`, "giu"))
    .map((part, i) => i % 2 ? <mark key={i}>{part}</mark> : part);
}

function ClaimsPane({ report, onSeek }: { report: Report; onSeek: (t: number) => void }) {
  if (!report.claims.length) return <p className="muted empty">No claims extracted.</p>;
  return (
    <table>
      <thead>
        <tr>
          <th>Time</th>
          <th>Src</th>
          <th>Type</th>
          <th>Claim</th>
          <th>Covered</th>
        </tr>
      </thead>
      <tbody>
        {report.claims.map((c, i) => (
          <tr key={i} className={c.supported ? "" : "bad"}>
            <td>
              <button type="button" className="ts" onClick={() => onSeek(c.time)}>
                {fmt(c.time)}
              </button>
            </td>
            <td>{c.source.replace(/_/g, " ")}</td>
            <td>{(c.claim_type || "").replace(/_/g, " ")}</td>
            <td>{c.text}</td>
            <td>{c.needs_disclaimer ? (c.supported ? "yes" : "no") : "n/a"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RunPane({ report, stages }: { report: Report; stages: Stage[] }) {
  const s = report.settings;
  return (
    <dl className="kv">
      <dt>Mode</dt>
      <dd>{s.mode}</dd>
      <dt>Language</dt>
      <dd>{s.language}</dd>
      <dt>Checks</dt>
      <dd>
        {[s.check_profanity && "bad words", s.check_bias && "bias", s.check_claims && "claims", s.check_bias && s.recheck && "recheck"].filter(Boolean).join(" · ") || "—"}
      </dd>
      <dt>Rules</dt>
      <dd>
        {s.rules.min_disclaimer_seconds}s · {s.rules.min_text_height_pct}% · {s.rules.reading_words_per_sec} wps
      </dd>
      <dt>Models</dt>
      <dd>{report.models.join(", ") || "—"}</dd>
      <dt>Whisper</dt>
      <dd>{report.whisper}</dd>
      <dt>Bad-word check</dt>
      <dd>{report.profanity_method === "vocabulary_and_context" ? "Vocabulary + contextual review" : report.profanity_method === "vocabulary" ? "Vocabulary scan" : "Not recorded"}</dd>
      <dt>Frames</dt>
      <dd>
        {report.video.frames_analyzed} @ {report.video.frame_interval}s · {report.visual_batches} batches ·{" "}
        {report.video.width}×{report.video.height}
      </dd>
      <dt>Dropped</dt>
      <dd>{report.bias_flags_dropped} bias flags after recheck</dd>
      <dt>Elapsed</dt>
      <dd>{report.total_seconds}s</dd>
      {stages.flatMap((st) => [
        <dt key={`${st.key}-k`}>{st.key}</dt>,
        <dd key={`${st.key}-v`}>
          {st.state}
          {st.seconds != null ? ` · ${st.seconds}s` : ""}
        </dd>,
      ])}
    </dl>
  );
}
