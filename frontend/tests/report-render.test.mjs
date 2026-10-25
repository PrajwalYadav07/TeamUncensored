import assert from "node:assert/strict";
import { after, test } from "node:test";
import { createElement } from "react";
import { renderToString } from "react-dom/server";
import { createServer } from "vite";

const server = await createServer({
  configFile: false,
  server: { middlewareMode: true, hmr: false, watch: null },
  appType: "custom",
  optimizeDeps: { noDiscovery: true, include: [] },
});
after(() => server.close());
const { Review, SpeechPreview } = await server.ssrLoadModule("/src/App.tsx");

// This is the report shape returned by a backend started before bad-word support.
const legacyReport = {
  video: { duration: 10, width: 320, height: 240, frame_interval: 1, frames_analyzed: 10 },
  transcript: { language: "en", segments: [{ start: 0, end: 2, text: "Hello everyone", words: [] }] },
  bias_flags: [], bias_flags_dropped: 0, claims: [], disclaimers: [],
  score: 100, verdict: "ready", findings: [],
  settings: {
    mode: "fast", check_bias: true, check_claims: true, recheck: true, language: "auto",
    rules: { min_disclaimer_seconds: 2, min_text_height_pct: 2.5, reading_words_per_sec: 3 },
  },
  models: ["test"], visual_batches: 1, whisper: "small", total_seconds: 1,
};

function renderReport(report) {
  return renderToString(createElement(Review, {
    report, videoUrl: "blob:test-video", marks: {}, stages: [],
    setMarks() {}, onNew() {}, onExport() {}, onHome() {},
  }));
}

test("a completed legacy report with speech stays visible", () => {
  const html = renderReport(legacyReport);
  assert.match(html, /Hello everyone/);
  assert.match(html, /Export JSON/);
  assert.match(html, /Bad-word results were not included/);
  assert.match(html, /review incomplete/);
  assert.doesNotMatch(html, /<strong>100<\/strong>/);
});

test("null bad-word results do not hide the report", () => {
  const html = renderReport({ ...legacyReport, profanity_flags: null });
  assert.match(html, /Hello everyone/);
  assert.match(html, /New check/);
});

test("current reports still render bad-word findings and their timestamps", () => {
  const flag = {
    start: 0.5, end: 1, text: "idiot", language: "en", severity: "medium", source: "speech",
    timing_precision: "word", why: "Known insult", suggested_fix: "Replace this wording",
  };
  const html = renderReport({
    ...legacyReport,
    settings: { ...legacyReport.settings, check_profanity: true },
    profanity_flags: [flag],
    findings: [{ id: "profanity-0", kind: "profanity", start: 0.5, end: 1, severity: "medium", title: "bad language", detail: flag }],
  });
  assert.match(html, /bad language/);
  assert.match(html, /<mark>idiot<\/mark>/);
  assert.match(html, /00:00.5/);
  assert.doesNotMatch(html, /Bad-word results were not included/);
});

test("a report without detected speech still shows its output", () => {
  const html = renderReport({ ...legacyReport, transcript: { language: null, segments: [] } });
  assert.match(html, /No clear speech/);
  assert.match(html, /Export JSON/);
  assert.match(html, /review incomplete/);
  assert.doesNotMatch(html, /<strong>100<\/strong>/);
});

test("a filtered transcript never renders a misleading perfect result", () => {
  const html = renderReport({
    ...legacyReport, profanity_flags: [],
    settings: { ...legacyReport.settings, check_profanity: true },
    transcript: { ...legacyReport.transcript, discarded_segments: 4 },
  });
  assert.match(html, /review incomplete/);
  assert.match(html, /Some speech was discarded/);
  assert.doesNotMatch(html, /<strong>100<\/strong>/);
});

test("a complete transcript with no matches describes findings rather than accuracy", () => {
  const html = renderReport({
    ...legacyReport, profanity_flags: [],
    settings: { ...legacyReport.settings, check_profanity: true },
    speech_assessment: { status: "complete", reasons: [] },
  });
  assert.match(html, /no flags detected/);
  assert.match(html, /not an accuracy percentage/);
  assert.doesNotMatch(html, />ready</);
});

test("a backend incomplete result cannot become 100 during frontend rescoring", () => {
  const html = renderReport({
    ...legacyReport, score: null, profanity_flags: [],
    speech_assessment: { status: "needs_review", reasons: ["Transcript is incomplete"] },
  });
  assert.match(html, /review incomplete/);
  assert.doesNotMatch(html, /<strong>100<\/strong>/);
});

test("uncertain words remain visible in the transcript instead of disappearing", () => {
  const html = renderReport({
    ...legacyReport, profanity_flags: [],
    transcript: { language: "hi", segments: [], uncertain_segments: [{ start: 1, end: 2, text: "bhenchod", words: [] }] },
  });
  assert.match(html, /bhenchod/);
  assert.match(html, /Uncertain speech/);
  assert.match(html, /review incomplete/);
});

test("profanity is highlighted verbatim within the transcript", () => {
  const flag = { start: 0.5, end: 1.5, text: "f**k you", language: "en", severity: "high", source: "speech", timing_precision: "word", why: "Profanity", suggested_fix: "Bleep" };
  const html = renderReport({
    ...legacyReport, profanity_flags: [flag],
    settings: { ...legacyReport.settings, check_profanity: true },
    transcript: { language: "en", segments: [{ start: 0, end: 2, text: "He said f**k you here", words: [] }] },
  });
  assert.match(html, /He said <mark>f\*\*k you<\/mark> here/);
});

test("an incomplete speech preview stays visible without claiming a clean result", () => {
  const html = renderToString(createElement(SpeechPreview, { preview: {} }));
  assert.match(html, /Bad-word results are not available yet/);
  assert.doesNotMatch(html, /No known bad words/);
});

test("a completed empty bad-word preview explains its result", () => {
  const html = renderToString(createElement(SpeechPreview, { preview: {
    transcript: legacyReport.transcript, profanity_flags: [],
  } }));
  assert.match(html, /No known bad words found/);
});
