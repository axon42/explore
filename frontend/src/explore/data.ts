import type { Segment, Session } from "../types";
export type Workspace = { id: string; name: string; archived: number; revision: number };
export type Meeting = {
  created_at?: string;
  id: string;
  workspace_id: string;
  title: string;
  context_version: number;
  archived: number;
  question_interval: 0 | 30 | 60 | 120;
};
export type Brief = {
  title: string;
  customer: string;
  vertical: string;
  objective: string;
  background: string;
  hypotheses: string;
  guidance: string;
};
export const emptyBrief: Brief = {
  title: "",
  customer: "",
  vertical: "",
  objective: "",
  background: "",
  hypotheses: "",
  guidance: "",
};
export const briefLabels: Record<keyof Brief, string> = {
  title: "Title",
  customer: "Customer",
  vertical: "Customer segment",
  objective: "Objective",
  background: "Background",
  hypotheses: "Hypotheses to test",
  guidance: "Interview guidance",
};
export type Evidence = Segment & { superseded: boolean };
export type Question = {
  needs_review?: boolean;
  id: string;
  text: string;
  rationale: string;
  status: "queued" | "asked" | "answered" | "discarded";
  revision: number;
  evidence: Evidence[];
};
export type Finding = {
  topic_id: string;
  workflow_key: string;
  id: string;
  kind: "workflow" | "gap" | "opportunity";
  title: string;
  body: string;
  basis: "observed" | "inferred";
  evidence: Evidence[];
};
export type Note = {
  id: string;
  body: string;
  revision: number;
  updated_at: string;
};
export type SpokenQuestion = {
  id: string; text: string; speaker_name: string; interview_role: string;
  participant_id: string | null; start_ms: number; superseded: boolean; evidence: Evidence[];
};
export type Detail = {
  meeting: Meeting;
  session: (Session & { mode?: "real" | "test" | "legacy" }) | null;
  brief: Partial<Brief>;
  brief_revision: number;
  questions: Question[];
  spoken_questions?: SpokenQuestion[];
  findings: Finding[];
  workflows: { key: string; topic_id: string; title: string }[];
  overview: string;
  overview_input_version: number | null;
  overview_context_version: number | null;
  notes: Note[];
};
export type Experiment = {
  scheduling?: {
    mode: "manual" | "automatic"; revision: number; changed: boolean;
    pending_segments: number; final_segments: number; analyzed_through_ms: number; remaining_calls: number;
    job: { id: string; status: string; error: string } | null;
  };
  strategy?: string;
  cursor: number;
  total: number;
  playing: boolean;
  speed: number;
  provider: string;
  model: string;
  analysis_status: string;
  error: string;
  calls: number;
  result: { latency_ms: number; model?: string; review?: { empty: boolean; reason: string } } | null;
};
export type Bundle = {
  detail: Detail;
  segments: Segment[];
  experiment: Experiment | null;
};
