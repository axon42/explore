> Historical mock decisions. Superseded by the connected [Explore interface](architecture.md).

# Interview workspace — UI mock

Preview: `http://127.0.0.1:5173/?preview=workspace`. Synthetic content and React state only; refresh restores the sample. The existing application remains at `/`.

- **Interview:** transcript beside an accumulating question backlog. Queued → Asked → Answered, with manual status controls and reopen. New suggestions never replace history. Answered/total and awaiting-answer counts communicate progress without implying all topics are understood.
- **Meeting overview:** discussion so far, observed workflows (blue), unknowns/gaps (amber), automation hypotheses (purple). Labels and icons accompany color; evidence links return to the transcript. Inference remains distinct from observation.
- **Brief:** customer, vertical, objective, background, hypotheses and assistant guidance. Keep available during the call; preparation should not disappear after starting.
- **Reset:** current test clears transcript/questions/findings while retaining the brief; the original mock clears all meetings from browser memory. The implemented Clear meetings action now archives records; see [archive design](archives-and-question-history.md). Scope and consequences are explicit. This mock changes browser memory only.
- **Responsive:** questions precede the transcript on narrow screens. Brief and overview remain separate views to avoid crowding the live interview.

Functionality pass: persist question history/status and answer evidence; generate incremental overview from delivered dialogue; save the brief; implement transactional scoped deletion and cancel active replay/LLM work before reset. No backend changes in this mock.

## Workspace → meetings
A workspace groups interviews for a customer segment or discovery initiative. The mock supports workspace creation, multiple meetings, breadcrumbs and switching while retaining each meeting’s in-memory brief/questions/transcript. Resetting all meetings affects only the selected workspace. Backend workspace IDs and persistence remain future work.

Suggested next additions (not implemented): shared hypotheses with supporting/contradicting evidence, comparable discovery fields across calls, source-linked quotations, follow-up commitments and a lightweight question usefulness rating.
