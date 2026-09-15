# Speaker separation and confirmed attribution

2026-09-14 · Local implementation complete; synthetic verification passed. Real diarization quality and Firefox capture rehearsal remain release gates.

## Decision
Use streaming diarization to distinguish voices, then let the interviewer confirm which
meeting participant each voice belongs to. A voice label is not a person's identity or role.
Keep this in the existing provider adapter, SQLite repository and browser UI; no agents,
knowledge graph, voice enrollment or cross-meeting voice recognition are needed.

Capture retains original `microphone` / `system` source identifiers and adds versioned speaker spans.
Participants have stable internal IDs, separate from captured voices. Legacy transcripts remain
unverified source labels; existing transcript text and evidence IDs stay intact.

## Implemented experience
1. Before capture, select **Who is using this microphone?** from the meeting roster, or
   **Shared microphone / not sure**. Never infer this from the account owner or first interviewer.
2. For a confirmed single-person microphone, attribute that source to the selected person.
   Separate voices on mixed system audio; a shared microphone also needs diarization.
3. A compact **Speakers** panel beside the capture controls shows anonymous voices as they
   appear. Each row has its source, a short transcript excerpt, person selector and **Confirm**.
   Choosing a person shows their interview role and job role for review; an incorrect role can
   be edited in the roster. Customers need no Explore login.
4. Example: `Remote speaker 2 → Priya Shah · Customer · Operations manager` (synthetic).
   The transcript shows the name/role after confirmation. Unconfirmed voices retain their label.
5. **Change** / **Clear assignment** correct a whole voice track; each finalized speaker passage also
   supports correcting just that passage when the provider merged or swapped speakers.
   Make the affected scope explicit. Keep the full audit history and an undo path.

A single-person microphone assignment is the interviewer's explicit assertion, not voice recognition.
If someone else starts sharing it, stop and resume capture in shared-microphone mode; earlier speech
can be corrected by passage. Do not silently carry the single-person assertion into a new capture.

No blocking popups for each new voice. Use existing blue/sage controls, readable labels and
keyboard access; color alone never identifies a person or confirmation status. No audio-preview
player: Explore currently retains text, not audio. Capture Stop and End interview remain visible.

Capture setup defaults to shared/unknown and resets on every opening; the operator explicitly chooses
a single-person microphone. Neutral questions continue before confirmation, while person-attributed
claims require exact confirmed spans. This avoids inferring the interviewer from roster order.

## Streaming behavior and limits
Keep the two current mono streams. Enable diarization for shared microphones and mixed system audio.
Deepgram's current documentation supports `diarize_model=v1` for streaming; pin that version for
the first evaluation. It returns word-level speaker labels, but live results have no
`speaker_confidence`. Word confidence is not identity confidence. Validate the chosen parameter
in an explicitly authorized synthetic provider smoke test before rollout.
[Official diarization reference](https://developers.deepgram.com/docs/diarization) (checked 2026-09-14).

Namespace a voice by **session + capture/stream instance + channel + provider speaker label**.
Speaker 0 on two connections is not the same person. A resumed/reconnected stream needs new
confirmation; several confirmed tracks may map to the same participant. Do not automatically
merge voices across microphone/system channels or across meetings.

Show interim text promptly; only accepted final speaker spans enter analysis. Group adjacent
same-speaker spans for readability, while retaining their exact evidence references. A speaker
change does not prove a topic is finished or bypass question pacing. Missing/invalid labels,
unusable word alignment and inseparable overlapping speech remain **Unassigned**; preserve text.
A confirmed track remains a fallible provider grouping, not verified identity for every word.
Headphones remain the simplest echo precaution; automatic duplicate-speech removal is deferred.

## Data and module boundaries

| Record | Responsibility |
| --- | --- |
| Meeting participant | Stable `participant_id`, name, interview role (`interviewer/customer/observer/unknown`) and separate job role; revisioned roster history. Independent of an app user or provider speaker ID. |
| Speaker track | Session-owned source identity, capture/stream instance, channel, provider label and separation method (`single_person_source`, `diarized`, later `provider_participant`). |
| Speaker span | Exact transcript revision plus Unicode character range; parent segment retains source times, linked to a track or unassigned. Covers only the words actually supported by provider alignment. |
| Attribution revision | Track-to-participant confirmation or passage override, scope, prior revision, actor/time and method. A clear assignment is recorded, not deleted. |

- Preserve the strict existing `TranscriptEvent` for existing producers. Add a versioned,
  validated speaker-metadata envelope for capable adapters; ingestion stores text and spans
  atomically. Speaker-only provider corrections participate in deduplication/revision identity.
- Keep original segment IDs/text/revisions. Diarization creates referenced spans rather than
  replacing one provider result with unstable split segment IDs. Unaligned words stay unassigned;
  never drop, duplicate or rewrite accepted text to fit speaker boundaries.
- User identity corrections append attribution revisions; they do not edit raw transcript text.
  A deterministic resolver applies passage override, then confirmed track mapping, otherwise unknown.
  Passage overrides attach to exact revisions; a provider correction cannot silently move them onto
  different words. Keep the original override in history and flag the changed passage for review.
- The provider normalizes observations; the repository validates ownership and writes transactions;
  the resolver supplies attributed dialogue to context builders, transcript views and exports.
  Analysis receives provider-independent person/role/status fields and exact source/span references.
- Enforce session/meeting ownership, revision conflicts and bounded metadata before commit.
  Bind confirmations to the current roster revision; stale choices cannot confirm a changed role.
  The current local operator is recorded honestly; future team members use authenticated actor IDs.

Use an additive transactional migration, not a database rewrite. Add stable participant IDs to
existing rosters without changing their names, legacy IDs or immutable session snapshots.
Preserve legacy associations as legacy/unverified; never promote `system → customer` automatically.
Replay fixtures keep their explicit synthetic provenance. Old exports/evidence links remain readable;
new versioned JSON includes speaker spans, attribution history and roster revisions.

## Analysis, corrections and reports
- Supply confirmed person/role separately from transcript text. Self-introductions can help a
  human recognize a voice; the LLM cannot confirm identity or change the roster.
- Until confirmation, summarize as **Unidentified speaker described…**. Recommended policy allows
  neutral questions such as “What happened during that six-hour wait?” but not invented personal
  attribution or customer-validation claims. Founder observations stay distinct from customer statements.
- Extend structured attribution/evidence validation: a customer-attributed claim must cite spans
  assigned to a confirmed customer. Mixed-speaker parent segments alone cannot establish who said it.
  Supporting words still need semantic evaluation; a confirmed role does not prove a claim is true.
- Stamp analysis inputs with roster/attribution revisions. On correction, mark dependent AI artifacts
  stale immediately and reject in-flight results with older attribution. Reconcile affected evidence
  through the existing bounded coordinator; metadata-only changes must work without new speech.
  Revisit affected older evidence in bounded batches, not just the most recent transcript window.
  Preserve human notes, asked/discarded states and prior AI revisions. Coalesce changes; no model call
  per detected voice, word or dropdown change. Budget exhaustion leaves an explicit stale state.
- Reports list people/roles and unresolved voices. Saved reports retain their attribution snapshot;
  corrections mark them outdated and regeneration creates a new revision. Full transcript exports
  retain original evidence plus the selected attribution version; remaining unknowns do not block export.

## Implementation boundaries and acceptance
Migration 7 and the provider, capture, confirmation UI, analysis and report paths now share the
same resolver. The feature applies to new captures; old evidence is not automatically reattributed.
Verify synthetic regression fixtures, then an authorized Firefox rehearsal with local interviewer,
remote cofounder and remote customer; test switches, interruptions, stop/resume and corrections.

Required checks: distinct speaker-0 tracks across channels/runs; multiple speakers in one result;
duplicates and speaker-only corrections; bad/missing word labels; no cross-person transcript grouping;
unknown/confirmed roles; single-mic setup changes; passage overrides; stale roster edits; migration and
foreign keys; wrong-workspace assignments; reset/stop races; stale model results; report/export history.
Test a founder proposing a pain that the customer denies, and verify it never becomes confirmed
customer evidence. Measure turn attribution and end-of-speech-to-question latency on held-out dialogue.
Measure 40–60 minute drift in the real rehearsal; do not promise perfect diarization or lower latency.

The capture adapter stays replaceable for browser/Zoom participant streams later. Preserve current
timeouts, queue limits and provider budgets. No paid calls, retained audio or additional services are
authorized by this planning document. See [capture](macos-audio-capture.md), [analysis](live-analysis.md),
[reports](meeting-reports.md) and [account/participant distinction](accounts-and-workspaces.md).

## Implemented data contracts
- `AttributedTranscriptEvent` extends the unchanged legacy event with `speaker_metadata.version=1`.
  Character spans partition the accepted text; no spans may overlap, leave gaps or exceed it.
  Missing/bad word alignment becomes unassigned text. No diarization-derived names or confidence.
- `speakers.py` owns participant IDs, observations, confirmation/correction transactions and resolution.
  IDs use session + capture + channel + provider label. There is no automatic reconnect or identity carryover.
- Whole-voice confirmations and exact-revision passage overrides append audit rows. Clearing a passage
  explicitly makes it unassigned; it does not fall back to a track. Selecting an earlier person records
  an undo as a new revision. Provider corrections require passage review instead of moving old overrides.
- Every roster edit conservatively requires reconfirmation. Session attribution/context versions change;
  existing AI memory is reconciled from the oldest uncovered text in bounded batches. Old questions retain
  human status and show a review label; obsolete topic summaries are withheld. Saved reports stay immutable.
- `attributed_to` plus `speaker_evidence` on claims/findings must resolve to confirmed source spans.
  Free-form summary/question semantics still require evaluation; reference validation alone cannot prove
  that Gemini interpreted a denial or role correctly. Unknown voices do not block neutral follow-ups.
- Archive context schema 2 snapshots roster + current assignment revisions on every human correction,
  even after meeting stop. Raw transcript events retain metadata. All prior archive contexts remain
  immutable. JSON exports add roster/assignment history; no archive table rewrite is required.
- Mapping API paths carry both meeting and session IDs, validate roster/attribution revisions and reject
  foreign participants. The current local operator is the actor; hosted authorization remains P3/P4.

Still pending: real streaming diarization evaluation (three people, headphones, overlap and 40–60 minute
drift), macOS permission recovery rehearsal, speaker-attributed semantic evals against Gemini, and
future browser-native participant sources. No biometric identification or retained audio is introduced.

## Verification — 2026-09-14
187 backend tests and 36 browser checks pass (one optional Zoom-toolkit fixture smoke test skipped).
New checks cover exact multi-voice spans, malformed/missing labels, speaker-only revisions, capture
restart identity, stale roster/assignment writes, foreign meeting access, archive rollback/reset,
metadata-only reprocessing, in-flight stale rejection, report history and migration/backfill.
Browser checks cover confirmation, per-passage correction, Unicode text preservation, explicit
microphone choice, keyboard/dialog behavior and narrow layouts. Lint, types and production build pass.
All provider fixtures are synthetic/mocked. No live paid transcription or LLM call was made for
verification. Native permission delivery and real voice-separation quality remain manual checks.

## One operator, multiple interview participants
Only the interviewer needs access to Explore. The operator saves everyone's name/role, explicitly
selects their own microphone identity, and confirms remote voice tracks in the Speakers panel.
Diarization separates voices; it does not establish names or founder/customer roles. Unknown tracks
stay unassigned until confirmation. A repeated provider label after reconnection is not an identity.
No automatic role inference, voice enrollment or new account requirement is added by diagnostics work.
