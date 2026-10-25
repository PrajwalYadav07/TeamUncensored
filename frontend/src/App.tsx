import { useEffect, useMemo, useRef, useState } from "react";
import type { BiasFlag, Claim, DisclaimerSpan, Finding, Report } from "./types";

const LANGS = [
  { id: "auto", label: "Auto-detect" },
  { id: "hi", label: "Hindi" },
  { id: "en", label: "English" },
  { id: "gu", label: "Gujarati" },
];

const fmt = (s: number) => `${Math.floor(s / 60)}:${(s % 60).toFixed(1).padStart(4, "0")}`;

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [videoUrl, setVideoUrl] = useState<string | null>(null);
  const [language, setLanguage] = useState("auto");
  const [script, setScript] = useState("");
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [report, setReport] = useState<Report | null>(null);

  useEffect(() => {
    if (!file) return;
    const url = URL.createObjectURL(file);
    setVideoUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [file]);

  useEffect(() => {
    if (!busy) return;
    const started = Date.now();
    const id = setInterval(() => setElapsed((Date.now() - started) / 1000), 250);
    return () => clearInterval(id);
  }, [busy]);

  async function run() {
    if (!file) return;
    setBusy(true);
    setError(null);
    setReport(null);
    setElapsed(0);
    const body = new FormData();
    body.append("video", file);
    body.append("language", language);
    body.append("script", script);
    try {
      const res = await fetch("/api/analyze", { method: "POST", body });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || `Request failed (${res.status})`);
      setReport(data as Report);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page">
      <header>
        <h1>adlint</h1>
        <p>Pre-release check for Indian ads: stereotypes, claims, and disclaimers, powered by Gemma 4.</p>
      </header>

      <section className="panel upload">
        <label className="file">
          <input type="file" accept="video/*" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
          <span>{file ? file.name : "Choose an ad video (up to ~60 seconds)"}</span>
        </label>
        <div className="row">
          <label>
            Audio language
            <select value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGS.map((l) => (
                <option key={l.id} value={l.id}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>
          <button disabled={!file || busy} onClick={run}>
            {busy ? `Analysing… ${elapsed.toFixed(0)}s` : "Check this ad"}
          </button>
        </div>
        <textarea
          placeholder="Optional: paste the script or voiceover text to help with unclear audio"
          value={script}
          onChange={(e) => setScript(e.target.value)}
          rows={2}
        />
        {busy && (
          <p className="muted">
            Extracting frames and transcribing audio, then Gemma reviews the ad and a second pass re-checks
            each bias flag. The first run also downloads the Whisper model.
          </p>
        )}
        {error && <p className="error">{error}</p>}
      </section>

      {report && videoUrl && <Results report={report} videoUrl={videoUrl} />}
    </div>
  );
}

function Results({ report, videoUrl }: { report: Report; videoUrl: string }) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const [now, setNow] = useState(0);
  const [selected, setSelected] = useState<string | null>(null);
  const duration = report.video.duration || 1;

  const seek = (t: number, id?: string) => {
    if (videoRef.current) {
      videoRef.current.currentTime = t;
      videoRef.current.pause();
    }
    if (id) setSelected(id);
  };

  const visibleDisclaimers = report.disclaimers.filter((d) => now >= d.start && now <= d.end);
  const claimTimes = useMemo(() => report.claims.filter((c) => c.source === "speech"), [report]);

  return (
    <>
      <section className="panel summary">
        <div className={`score ${report.verdict === "ready" ? "good" : report.verdict === "high risk" ? "bad" : "warn"}`}>
          <strong>{report.score}</strong>
          <span>{report.verdict}</span>
        </div>
        <div className="stats">
          <Stat n={report.bias_flags.length} label="bias flags" />
          <Stat n={report.claims.filter((c) => !c.supported).length} label="unsupported claims" />
          <Stat n={report.disclaimers.filter((d) => d.issues.length).length} label="weak disclaimers" />
          <Stat n={report.bias_flags_dropped} label="flags dropped by re-check" />
        </div>
        <p className="muted small">
          {report.model} · {report.video.frames_analyzed} frames every {report.video.frame_interval}s ·
          speech: {report.transcript.language ?? "none"} · extract {report.timings.extract_s}s, review{" "}
          {report.timings.analyze_s}s, re-check {report.timings.verify_s}s
        </p>
      </section>

      <section className="panel player">
        <div className="video-wrap" style={{ aspectRatio: `${report.video.width} / ${report.video.height}` }}>
          <video ref={videoRef} src={videoUrl} controls onTimeUpdate={(e) => setNow(e.currentTarget.currentTime)} />
          {visibleDisclaimers.map((d, i) => {
            const [ymin, xmin, ymax, xmax] = d.box_2d;
            return (
              <div
                key={i}
                className={`box ${d.issues.length ? "bad" : "ok"}`}
                style={{
                  top: `${ymin / 10}%`,
                  left: `${xmin / 10}%`,
                  height: `${(ymax - ymin) / 10}%`,
                  width: `${(xmax - xmin) / 10}%`,
                }}
              >
                <span>
                  {d.duration}s / {d.text_height_pct}% tall
                </span>
              </div>
            );
          })}
        </div>

        <div className="timeline">
          {report.disclaimers.map((d, i) => (
            <div
              key={`d${i}`}
              className={`band ${d.issues.length ? "bad" : "ok"}`}
              style={{ left: `${(d.start / duration) * 100}%`, width: `${(d.duration / duration) * 100}%` }}
              title={`Disclaimer ${fmt(d.start)}–${fmt(d.end)}`}
            />
          ))}
          {report.findings.map((f) => (
            <button
              key={f.id}
              className={`marker ${f.kind} ${f.severity} ${selected === f.id ? "sel" : ""}`}
              style={{ left: `${(f.start / duration) * 100}%` }}
              onClick={() => seek(f.start, f.id)}
              title={`${fmt(f.start)} ${f.title}`}
            />
          ))}
          <div className="playhead" style={{ left: `${(now / duration) * 100}%` }} />
        </div>
        <div className="legend">
          <span className="dot bias" /> bias <span className="dot claim" /> unsupported claim
          <span className="dot disclaimer" /> weak disclaimer <span className="band-key" /> disclaimer on screen
        </div>
      </section>

      <section className="panel findings">
        <h2>Findings</h2>
        {report.findings.length === 0 && <p className="muted">No issues found.</p>}
        {report.findings.map((f) => (
          <FindingCard key={f.id} f={f} selected={selected === f.id} onSeek={() => seek(f.start, f.id)} />
        ))}
      </section>

      <section className="panel">
        <h2>Transcript</h2>
        {report.transcript.segments.length === 0 && <p className="muted">No speech detected.</p>}
        {report.transcript.segments.map((s, i) => {
          const hasClaim = claimTimes.some((c) => c.time >= s.start - 0.5 && c.time <= s.end + 0.5);
          return (
            <p key={i} className={`seg ${hasClaim ? "claim" : ""} ${now >= s.start && now <= s.end ? "live" : ""}`}>
              <button className="ts" onClick={() => seek(s.start)}>
                {fmt(s.start)}
              </button>
              {s.text}
            </p>
          );
        })}
      </section>

      <section className="panel">
        <h2>All claims</h2>
        <table>
          <thead>
            <tr>
              <th>Time</th>
              <th>Source</th>
              <th>Claim</th>
              <th>Disclaimer nearby</th>
            </tr>
          </thead>
          <tbody>
            {report.claims.map((c, i) => (
              <tr key={i} className={c.supported ? "" : "bad"}>
                <td>
                  <button className="ts" onClick={() => seek(c.time)}>
                    {fmt(c.time)}
                  </button>
                </td>
                <td>{c.source.replace(/_/g, " ")}</td>
                <td>{c.text}</td>
                <td>{c.needs_disclaimer ? (c.supported ? "yes" : "no") : "not needed"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  );
}

function Stat({ n, label }: { n: number; label: string }) {
  return (
    <div className="stat">
      <strong>{n}</strong>
      <span>{label}</span>
    </div>
  );
}

function FindingCard({ f, selected, onSeek }: { f: Finding; selected: boolean; onSeek: () => void }) {
  return (
    <article className={`card ${f.kind} ${f.severity} ${selected ? "sel" : ""}`}>
      <header>
        <button className="ts" onClick={onSeek}>
          {fmt(f.start)}
          {f.end > f.start ? `–${fmt(f.end)}` : ""}
        </button>
        <strong>{f.title}</strong>
        <span className={`pill ${f.severity}`}>{f.severity}</span>
      </header>
      {f.kind === "bias" && <BiasBody d={f.detail as BiasFlag} />}
      {f.kind === "claim" && <ClaimBody d={f.detail as Claim} />}
      {f.kind === "disclaimer" && <DisclaimerBody d={f.detail as DisclaimerSpan} />}
    </article>
  );
}

function BiasBody({ d }: { d: BiasFlag }) {
  return (
    <>
      <p>
        <b>Seen:</b> {d.evidence}
      </p>
      <p>
        <b>Why it matters:</b> {d.why}
      </p>
      <p>
        <b>Suggested fix:</b> {d.suggested_fix}
      </p>
      <p className="muted small">
        source: {d.source?.replace(/_/g, " ")} · confidence {Math.round((d.confidence ?? 0) * 100)}%
        {d.verified ? ` · re-check: ${d.verify_reason}` : " · not re-checked"}
      </p>
    </>
  );
}

function ClaimBody({ d }: { d: Claim }) {
  return (
    <>
      <p>
        <b>Claim:</b> “{d.text}” ({d.source.replace(/_/g, " ")}, {d.claim_type})
      </p>
      <p>No disclaimer was visible on screen around this moment.</p>
    </>
  );
}

function DisclaimerBody({ d }: { d: DisclaimerSpan }) {
  return (
    <>
      <p>
        <b>Text:</b> “{d.text}”
      </p>
      <p>
        On screen for <b>{d.duration}s</b>; {d.word_count} words need about <b>{d.required_duration}s</b> to read.
        Text height <b>{d.text_height_pct}%</b> of the frame (minimum {d.min_text_height_pct}%).
      </p>
    </>
  );
}
