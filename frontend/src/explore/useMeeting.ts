import { useEffect, useState } from "react";
import { api } from "../types";
import type { Segment } from "../types";
import type { Bundle, Detail, Experiment } from "./data";
export function useMeeting(id: string, refresh: number) {
  const [bundle, setBundle] = useState<Bundle>();
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const abort = new AbortController();
    async function load() {
      try {
        const options = { signal: abort.signal };
        const detail = await api<Detail>(`/meetings/${id}`, options);
        const [snapshot, experiment] = await Promise.all([
          api<{ segments: Segment[] }>(
            `/sessions/${detail.session.id}`,
            options,
          ),
          api<Experiment>(`/sessions/${detail.session.id}/experiment`, options),
        ]);
        if (active) {
          setBundle({ detail, segments: snapshot.segments, experiment });
          setError("");
        }
      } catch (e) {
        if (active) setError((e as Error).message);
      }
      if (active) timer = setTimeout(() => void load(), 800);
    }
    void load();
    return () => {
      active = false;
      clearTimeout(timer);
      abort.abort();
    };
  }, [id, refresh]);
  return { bundle, error };
}
