import type { Segment } from "../types";

export type TranscriptLine = Segment & { span_index?: number; interview_role?: string; attribution_status?: string; anchor?: boolean };

// Exact Unicode character ranges from the backend; never overwrite stored text or IDs.
export function transcriptLines(segments: Segment[]): TranscriptLine[] {
  return segments.flatMap(segment => !segment.attributions?.length ? [segment] : segment.attributions.map((span, index) => ({
    ...segment, text: Array.from(segment.text).slice(span.start, span.end).join(""),
    speaker_id: span.participant_id || span.track_id || `${segment.segment_id}:unknown:${index}`,
    speaker_name: span.name, span_index: span.index, anchor: index === 0,
    interview_role: span.interview_role, attribution_status: span.status,
  })));
}

// Presentation only: every original segment retains its evidence anchor and revision.
export function groupTranscript(segments: Segment[]): TranscriptLine[][] {
  const groups: TranscriptLine[][] = [];
  for (const segment of transcriptLines(segments)) {
    const group = groups.at(-1);
    const previous = group?.at(-1);
    if (group && previous && previous.speaker_id === segment.speaker_id &&
        previous.attribution_status === segment.attribution_status &&
        segment.start_ms - previous.end_ms <= 8000 &&
        segment.start_ms - group[0].start_ms < 60000) {
      group.push(segment);
    } else groups.push([segment]);
  }
  return groups;
}
