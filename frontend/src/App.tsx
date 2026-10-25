import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import type {
  BiasFlag,
  Claim,
  DisclaimerSpan,
  Finding,
  Job,
  Mode,
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

function rescore(findings: Finding[], marks: Record<string, ReviewMark>) {
  let score = 100;
  let hasHigh = false;
  for (const f of findings) {
    if (marks[f.id] === "false_positive") continue;
    if (f.severity === "high") hasHigh = true;
    if (f.kind === "bias") score -= SEV_PENALTY[f.severity] ?? 12;
    else if (f.kind === "claim") score -= 10;
    else if (f.kind === "disclaimer") {
      const issues = (f.detail as DisclaimerSpan).issues ?? [];
      if (issues.includes("too_short")) score -= 10;
      if (issues.includes("too_small")) score -= 8;
    }
  }
  score = Math.max(0, score);
  const verdict = score >= 85 && !hasHigh ? "ready" : score >= 60 ? "fix before release" : "high risk";
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
  const [recheck, setRecheck] = useState(true);
  const [minSec, setMinSec] = useState(2);
  const [minH, setMinH] = useState(2.5);
  const [wps, setWps] = useState(3);
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [posting, setPosting] = useState(false);
  const [marks, setMarks] = useState<Record<string, ReviewMark>>({});

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
        const res = await fetch(`/api/jobs/${job.id}`);
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
    if (!checkBias && !checkClaims) {
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
    body.append("recheck", String(recheck));
    body.append("min_disclaimer_seconds", String(minSec));
    body.append("min_text_height_pct", String(minH));
    body.append("reading_words_per_sec", String(wps));
    try {
      const res = await fetch("/api/jobs", { method: "POST", body });
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

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="wordmark">adlint</span>
          <span className="tag">ad compliance</span>
        </div>
        <div className="top-meta">
          {job && (
            <>
              <span className="mono">{job.id}</span>
              <span className={`st st-${job.status}`}>{job.status}</span>
            </>
          )}
          {file && <span className="file-name">{file.name}</span>}
          {report && (
            <button type="button" className="ghost" onClick={() => exportJson(report, marks, job)}>
              Export JSON
            </button>
          )}
          {(job || error) && (
            <button type="button" className="ghost" onClick={reset}>
              New check
            </button>
          )}
        </div>
      </header>

      {reviewing ? (
        <Review report={report!} videoUrl={videoUrl!} marks={marks} setMarks={setMarks} stages={job?.stages ?? []} />
      ) : (
        <div className="workspace setup">
          <UploadPane file={file} videoUrl={videoUrl} onFile={setFile} />
          <aside className="side-form">
            {running || job?.status === "error" ? (
              <StageList stages={job?.stages ?? []} error={job?.error || error} />
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
          </aside>
        </div>
      )}
    </div>
  );
}

function exportJson(report: Report, marks: Record<string, ReviewMark>, job: Job | null) {
  const scored = rescore(report.findings, marks);
  const blob = new Blob(
    [
      JSON.stringify(
        {
          job_id: job?.id,
          ...report,
          review: marks,
          score_adjusted: scored.score,
          verdict_adjusted: scored.verdict,
        },
        null,
        2,
      ),
    ],
    { type: "application/json" },
  );
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `adlint-${job?.id ?? "report"}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function UploadPane({
  file,
  videoUrl,
  onFile,
}: {
  file: File | null;
  videoUrl: string | null;
  onFile: (f: File | null) => void;
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
          <label className="drop-lab">
            <input type="file" accept="video/*" onChange={(e) => take(e.target.files)} />
            <span className="drop-kicker">Video</span>
            <span>Drop an ad file here, or click to choose.</span>
            <span className="muted">mp4 / mov · up to 200 MB</span>
          </label>
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
        <p className="hint">{props.mode === "fast" ? "26B · quicker pass" : "31B · higher thinking"}</p>
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
      </label>

      <fieldset>
        <legend>Checks</legend>
        <label className="chk">
          <input type="checkbox" checked={props.checkBias} onChange={(e) => props.setCheckBias(e.target.checked)} />
          Bias
        </label>
        <label className="chk">
          <input type="checkbox" checked={props.checkClaims} onChange={(e) => props.setCheckClaims(e.target.checked)} />
          Claims
        </label>
        <label className="chk">
          <input type="checkbox" checked={props.recheck} onChange={(e) => props.setRecheck(e.target.checked)} />
          Recheck bias flags
        </label>
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

function StageList({ stages, error }: { stages: Stage[]; error: string | null }) {
  return (
    <div className="stages">
      <h1>Running</h1>
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

function Review({
  report,
  videoUrl,
  marks,
  setMarks,
  stages,
}: {
  report: Report;
  videoUrl: string;
  marks: Record<string, ReviewMark>;
  setMarks: (m: Record<string, ReviewMark>) => void;
  stages: Stage[];
}) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [now, setNow] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const [tab, setTab] = useState<"transcript" | "claims" | "run">("transcript");
  const duration = report.video.duration || 1;
  const scored = useMemo(() => rescore(report.findings, marks), [report.findings, marks]);

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
      <div className="col-main">
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

        <section className="pane tabs">
          <nav>
            {(["transcript", "claims", "run"] as const).map((t) => (
              <button key={t} type="button" className={tab === t ? "on" : ""} onClick={() => setTab(t)}>
                {t === "run" ? "Run details" : t[0].toUpperCase() + t.slice(1)}
              </button>
            ))}
          </nav>
          {tab === "transcript" && <TranscriptPane report={report} now={now} onSeek={seek} />}
          {tab === "claims" && <ClaimsPane report={report} onSeek={seek} />}
          {tab === "run" && <RunPane report={report} stages={stages} />}
        </section>
      </div>

      <aside className="sidebar">
        <div className={`scoreboard v-${scored.verdict.replace(/\s+/g, "-")}`}>
          <strong>{scored.score}</strong>
          <span>{scored.verdict}</span>
          {scored.score !== report.score && <em>was {report.score}</em>}
        </div>
        <div className="tally">
          <span>{counts.open} open</span>
          <span>{counts.approved} approved</span>
          <span>{counts.fp} false pos.</span>
        </div>
        <div className="finding-list">
          {report.findings.length === 0 && <p className="muted empty">No issues in this run.</p>}
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
      </aside>
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
        {BIAS_LANES.map((l) => (
          <div key={l.key} className="lab">
            <i className={`cdot c-${l.key}`} />
            {l.label}
          </div>
        ))}
        <div className="lab">
          <i className="cdot c-claim" />
          claims
        </div>
        <div className="lab">
          <i className="cdot c-disc" />
          disclaimers
        </div>
        <div className="lab dens">risk density</div>
      </div>
      <div className="lane-tracks" ref={tracksRef} onClick={clickTrack}>
        {BIAS_LANES.map((l) => (
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
  if (!report.transcript.segments.length) {
    return <p className="muted empty">{report.transcript.error || "No speech detected."}</p>;
  }
  return (
    <div className="transcript">
      {report.transcript.language && <p className="meta">lang {report.transcript.language}</p>}
      {report.transcript.segments.map((s, i) => {
        const hit = speechClaims.some((c) => c.time >= s.start - 0.5 && c.time <= s.end + 0.5);
        const live = now >= s.start && now <= s.end;
        return (
          <p key={i} className={`seg ${hit ? "hit" : ""} ${live ? "live" : ""}`}>
            <button type="button" className="ts" onClick={() => onSeek(s.start)}>
              {fmt(s.start)}
            </button>
            {s.text}
          </p>
        );
      })}
    </div>
  );
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
        {[s.check_bias && "bias", s.check_claims && "claims", s.recheck && "recheck"].filter(Boolean).join(" · ") || "—"}
      </dd>
      <dt>Rules</dt>
      <dd>
        {s.rules.min_disclaimer_seconds}s · {s.rules.min_text_height_pct}% · {s.rules.reading_words_per_sec} wps
      </dd>
      <dt>Models</dt>
      <dd>{report.models.join(", ") || "—"}</dd>
      <dt>Whisper</dt>
      <dd>{report.whisper}</dd>
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
