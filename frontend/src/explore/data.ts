import type { Segment, Session } from "../types";
export type Workspace = { id: string; name: string };
export type Meeting = {
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
  id: string;
  text: string;
  rationale: string;
  status: "queued" | "asked" | "answered" | "discarded";
  revision: number;
  evidence: Evidence[];
};
export type Finding = {
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
export type Detail = {
  meeting: Meeting;
  session: Session;
  brief: Partial<Brief>;
  brief_revision: number;
  questions: Question[];
  findings: Finding[];
  overview: string;
  overview_input_version: number | null;
  overview_context_version: number | null;
  notes: Note[];
};
export type Experiment = {
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
  result: { latency_ms: number } | null;
};
export type Bundle = {
  detail: Detail;
  segments: Segment[];
  experiment: Experiment;
};
