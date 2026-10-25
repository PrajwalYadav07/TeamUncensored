export type Severity = "low" | "medium" | "high";
export type FindingKind = "bias" | "claim" | "disclaimer";
export type JobStatus = "running" | "done" | "error";
export type StageState = "pending" | "running" | "done" | "error" | "skipped";
export type Mode = "fast" | "accurate";
export type ReviewMark = "open" | "approved" | "false_positive";

export interface Word {
  start: number;
  end: number;
  word: string;
}

export interface Segment {
  start: number;
  end: number;
  text: string;
  words: Word[];
}

export interface Transcript {
  language: string | null;
  segments: Segment[];
  note?: string | null;
  error?: string;
}

export interface BiasFlag {
  start: number;
  end: number;
  category: string;
  source: string;
  evidence: string;
  why: string;
  suggested_fix: string;
  severity: Severity;
  confidence: number;
  verified?: boolean;
  verify_reason?: string;
}

export interface Claim {
  time: number;
  source: string;
  text: string;
  claim_type: string;
  needs_disclaimer: boolean;
  disclaimer_ids: number[];
  supported: boolean;
}

export interface DisclaimerSpan {
  text: string;
  start: number;
  end: number;
  duration: number;
  required_duration: number;
  word_count: number;
  text_height_pct: number;
  min_text_height_pct: number;
  box_2d: [number, number, number, number];
  issues: string[];
}

export interface Finding {
  id: string;
  kind: FindingKind;
  start: number;
  end: number;
  severity: Severity;
  title: string;
  detail: BiasFlag | Claim | DisclaimerSpan;
}

export interface Rules {
  min_disclaimer_seconds: number;
  min_text_height_pct: number;
  reading_words_per_sec: number;
  claim_window_before?: number;
  claim_window_after?: number;
}

export interface ReportSettings {
  mode: Mode;
  check_bias: boolean;
  check_claims: boolean;
  recheck: boolean;
  language: string;
  rules: Rules;
}

export interface VideoInfo {
  duration: number;
  width: number;
  height: number;
  frame_interval: number;
  frames_analyzed: number;
}

export interface Report {
  video: VideoInfo;
  transcript: Transcript;
  bias_flags: BiasFlag[];
  bias_flags_dropped: number;
  claims: Claim[];
  disclaimers: DisclaimerSpan[];
  score: number;
  verdict: string;
  findings: Finding[];
  settings: ReportSettings;
  models: string[];
  visual_batches: number;
  whisper: string;
  total_seconds: number;
}

export interface Stage {
  key: string;
  label: string;
  state: StageState;
  seconds: number | null;
}

export interface Job {
  id: string;
  status: JobStatus;
  stages: Stage[];
  result: Report | null;
  error: string | null;
}
