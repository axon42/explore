import type { Brief, Evidence } from "./data";
import type { Segment } from "../types";

export type Topic = {
  id: string;
  session_id: string;
  title: string;
  summary: string;
  summary_sources: Record<string, number>;
  revision: number;
  status: "active" | "paused";
  provisional: boolean;
  needs_review: boolean;
  evidence: { segment_id: string; revision: number; superseded: boolean; assignment: string }[];
};
export type RecordItem = {
  text?: string;
  body?: string;
  basis?: string;
  status?: string;
  name?: string;
  speaker_id?: string;
  interview_role?: string;
  job_role?: string;
  brief?: Partial<Brief>;
  sources?: Record<string, number>;
  evidence?: Evidence[];
};
export type Section = {
  key: string;
  title: string;
  items: RecordItem[];
  topic_groups?: { topic_id: string; title: string; items: RecordItem[] }[];
};
export type LiveAnalysis = {
  simulated: boolean;
  topics: Topic[];
  state: { topic_state?: { focus_id?: string; readiness?: string; action?: string } };
  notes: Section[];
};
export type SavedWorkflow = {
  key: string;
  title: string;
  topic_id?: string;
  steps: { label: string; source_ids: string[] }[];
  transitions: string[][];
  sources: Record<string, number>;
};
export type MeetingReport = {
  schema_version: number;
  revision: number;
  meeting: { id: string; title: string };
  session: { id: string; created_at: string };
  generated_at: string;
  duration_ms: number;
  simulated: boolean;
  provider: string;
  topics?: Topic[];
  sections: Section[];
  workflows: SavedWorkflow[];
  evidence: Segment[];
  coverage: { final_segments: number; processed_segments: number; provisional_segments: number };
};

export function referencedEvidence(sources: Record<string, number> = {}, segments: Segment[]): Evidence[] {
  return segments.filter(s => sources[s.segment_id] === s.revision)
    .map(s => ({ ...s, superseded: false }));
}

// Stable color follows identity through title changes, sorting and topic resumption.
export function topicTone(id: string) {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return `ex-topic-tone-${hash % 5}`;
}
