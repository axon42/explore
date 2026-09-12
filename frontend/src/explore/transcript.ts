import type { Segment } from "../types";

// Presentation only: every original segment retains its evidence anchor and revision.
export function groupTranscript(segments: Segment[]): Segment[][] {
  const groups: Segment[][] = [];
  for (const segment of segments) {
    const group = groups.at(-1);
    const previous = group?.at(-1);
    if (group && previous && previous.speaker_id === segment.speaker_id &&
        segment.start_ms - previous.end_ms <= 8000 &&
        segment.start_ms - group[0].start_ms < 60000) {
      group.push(segment);
    } else groups.push([segment]);
  }
  return groups;
}
