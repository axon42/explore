export interface Session {
  id: string;
  title: string;
  status: "live" | "stopped";
  created_at: string;
  stopped_at: string | null;
  version: number;
}

export interface Segment {
  event_id: string;
  segment_id: string;
  revision: number;
  speaker_id: string;
  speaker_name: string | null;
  start_ms: number;
  end_ms: number;
  text: string;
  is_final: boolean;
}

export type Update =
  | { type: "snapshot"; version: number; session: Session; segments: Segment[] }
  | { type: "segment"; version: number; segment: Segment }
  | { type: "status"; version: number; session: Session }
  | { type: "demo_error"; message: string }
  | { type: "error"; message: string };

export async function api<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(error.message || `Request failed (${response.status})`);
  }
  return response.json();
}

export function timestamp(ms: number) {
  const seconds = Math.floor(ms / 1000);
  return `${Math.floor(seconds / 60)
    .toString()
    .padStart(2, "0")}:${(seconds % 60).toString().padStart(2, "0")}`;
}
