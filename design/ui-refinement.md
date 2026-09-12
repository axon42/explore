# UI refinement — blue + sage

2026-09-12. **Approved blue + sage styling is implemented in Explore.** The isolated
[interactive mock](../frontend/public/ui-preview.html) remains at `/ui-preview.html` on port 5173 for reference.
All data is synthetic. The preview makes no API requests and cannot record or delete anything.

## Direction
Keep the existing light layout and navigation. Introduce color through selected controls,
small status labels, section icons, thread accents and restrained surface tints. Keep reading
surfaces white. No gradients, remote fonts, component framework or animation dependency.

| Role | Blue + sage | Usage |
| --- | --- | --- |
| Primary | `#315BD3` / `#EDF2FF` tint | Main action, selection, focus, evidence links, workflows |
| Live / observed | `#22684E` / `#EAF5EE` | Capture state, accepted observations, active thread |
| AI-derived | `#7150A6` / `#F2EEF9` | Suggestions and automation hypotheses |
| Gap / uncertainty | `#8A5918` / `#FFF4DF` | Unknown ownership, incomplete information, warning |
| Destructive / failure | `#AD3444` / `#FFF0F1` | Reset/delete and actionable failures |
| Neutral | `#1C2940` text, `#5E6D83` secondary | Body copy; white cards on `#F5F7FB` |

The preview's second palette is **indigo + warm sand**. Both use the same hierarchy and
interactions so comparison stays focused on color. Labels always accompany color. Topic
identity colors remain consistent across summaries and reports; they do not establish causality.

## Component audit

| Surface / controls | Repair or assessment | Visual treatment |
| --- | --- | --- |
| Sidebar, workspaces, meeting list, analysis mode | Named controls; persisted mode and concurrent-tab guards; desktop/mobile flows checked | Tinted selected item; quiet settings area |
| Meeting header, tabs, archive/reset | Existing status and scope preserved; reset dialog now explicitly named | Clear primary action; restrained destructive treatment |
| Capture consent popup | Fixed centering and checkbox sizing; viewport height bound; errors inside popup; Escape restores focus; consent resets on reopen | Shared modal anatomy with title, explanation, consent and action footer |
| Workspace/create/reset dialogs | Shared centering, height/scroll behavior and accessible names; pending inputs disabled | Same spacing, radii, focus and buttons as capture |
| Transcript, source highlight, playback/injection | Grouping and stable source IDs retained; existing duplicate/reset and keyboard flows covered | Blue source links, amber selected quote, subtle speaker colors |
| Discussion threads | Active/paused/tentative labels and exact evidence links remain; first-topic routing bug repaired separately | Stable thread accent plus development state |
| Questions, frequency, status, discard/restore | Retained history and cooldown behavior preserved; no invented completion percentage | Violet suggestions; status labels; quiet discard, clear next action |
| Overview findings | Current cards do not encode explicit workflow-to-gap relationships | Mock groups gaps/hypotheses under workflows; implementation requires explicit evidence-backed associations |
| Brief / participants / human notes | Inputs cannot change during saves; role mappings and optimistic revisions retained | Consistent labels, input height, action rows; human and AI authorship clear |
| Generated notes / report / diagrams / exports | Safe text, revision selection, evidence panel, empty sections and narrow layout checked | Matching section colors and topic accents; preserve unknown-edge labels |
| Errors / loading / disabled controls | Specific allowlisted analysis diagnostics added; existing source data retained on failure | Shared inline notices, readable disabled controls and meaningful next action |
| Legacy Zoom proof | Existing isolated styles, cancellation and host-ending tests retained | Broader redesign deferred with the integration; no third-party toolkit restyling |

These checks are code review plus synthetic browser flows, not a claim that every browser,
OS permission state or real-model output is covered. Automated UI checks run in Chrome here;
Firefox remains the user's primary manual test browser.

## Implementation
- `frontend/src/explore/theme.css` owns semantic colors, surfaces, borders and radii. Existing
  component styles consume those tokens; no new dependency, remote font or request was added.
- The main canvas, sidebar, tabs, forms, question states, source links, discussion threads,
  generated notes, reports and dialogs use the approved palette. Topic colors continue to
  follow stable IDs; question status colors match the saved report chart.
- Question frequency and progress now sit beside the questions. The capture ribbon is green
  only while this meeting is capturing. Existing API calls, storage, budgets and consent gates
  are unchanged. Disabled controls remain readable and keyboard outlines remain visible.
- Workflow relationships and an explicit live-analysis retry action remain separate functional
  work with data contracts and budget checks. The mock's example associations are not inferred
  from adjacency, topic color or title in the live app.
- The legacy Zoom proof remains isolated. Main-app changes do not restyle its third-party toolkit.

## Verification
Synthetic browser checks cover all five meeting views at desktop, tablet and 320px widths,
zoomed layout, reduced motion, actual text/background contrast, modal consent/errors/focus,
and existing evidence, question, note and report flows. Chrome automation is available here;
Firefox remains the user's manual testing browser on `http://127.0.0.1:5173`.

Rollout checks: 30 browser tests passed; one optional real Zoom toolkit test was skipped.
Frontend lint, TypeScript and the production build passed. No real provider or capture calls
were made. Production JavaScript is 83.73 kB gzip and CSS is 7.99 kB gzip.
