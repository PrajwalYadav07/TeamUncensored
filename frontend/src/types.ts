export type Severity = "low" | "medium" | "high";

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
  kind: "bias" | "claim" | "disclaimer";
  start: number;
  end: number;
  severity: Severity;
  title: string;
  detail: BiasFlag | Claim | DisclaimerSpan;
}

export interface Report {
  video: {
    duration: number;
    width: number;
    height: number;
    frame_interval: number;
    frames_analyzed: number;
  };
  transcript: { language: string | null; segments: Segment[]; error?: string };
  bias_flags: BiasFlag[];
  bias_flags_dropped: number;
  claims: Claim[];
  disclaimers: DisclaimerSpan[];
  score: number;
  verdict: string;
  findings: Finding[];
  model: string;
  timings: Record<string, number>;
}
