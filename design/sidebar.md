# Sidebar organization

2026-09-14 · Approved and implemented in the connected application. The standalone mock remains available for reference.

Preview: [sidebar-preview.html](http://127.0.0.1:5173/sidebar-preview.html).
All content is synthetic. Controls operate in page memory; no API calls or browser storage writes.

## Direction
Keep Explore's blue/sage language, light surfaces and circle-with-dot logo. Use a 272 px desktop
sidebar, consistent icon/label columns, 40–50 px control rows and quieter section dividers.
Avoid adding illustrations, gradients, a new framework or account features to fix navigation.

| Area | Proposed content | Reason |
| --- | --- | --- |
| Header | Logo; workspace card with switcher and actions menu | Workspace ownership and actions have one home |
| Primary action | One labeled New meeting button | Replaces the small, ambiguous plus beside Meetings |
| Navigation | Meetings and Archives together | Both are destinations, rather than scattered settings |
| Meeting list | Integrated search; recent meetings, subtle date, clear selected row | Remove duplicate search labels and improve scanning |
| Bottom tools | Analysis mode and current value; Test mode switch; locked Developer entry | Compact, consistently aligned access to app-wide controls |

On desktop the meeting list alone scrolls when long. Bottom tools stay available; a short list can retain calm
whitespace instead of filling it with settings copy. Long names truncate with a full-name tooltip.
The mock includes one/many/long-name/empty states and a narrow viewport treatment.

## Approved interactions
- Put **Archive all meetings** (currently Clear meetings) and **Archive workspace** inside the
  workspace actions menu. Both retain their existing confirmation, ownership and live-session guards.
  They are reversible archive operations; permanent red Delete remains on the Archives page.
- Move the analysis selector and its global-scope explanation into a small menu. Keep the current
  mode visible on the row; display the full Discussion threads label inside the menu.
- Use an explicit Test mode switch with an amber enabled state; retain its backend gate. Developer
  keeps the existing admin-key screen; the mock does not grant or implement account permissions.
- Remove redundant Local workspace text. Do not infer account, team or user identity from it.
- Dates in the mock are sample display metadata. Connected implementation must use actual existing
  meeting timestamps, never invented last activity or participant identities.

## Connected implementation
Workspace controls, meeting navigation and tools now live in small sidebar components, reusing
existing handlers/API contracts. Selection persistence, archive guards, admin access and error
handling are preserved. Native popovers retain their dismissal behavior; selection fields now use the [shared dropdown](dropdowns.md).
Expanded/selected/switch states are exposed to assistive technology. Menus/dialogs restore focus,
search retains an accessible label, and existing theme contrast/focus tokens remain in use.

Regression checks: switching workspaces and selected meetings; search/empty states; archive scope,
confirmation and live-session rejection; analysis-save conflicts/offline state; Test mode and admin
gates; long-list scrolling, long names, keyboard access and narrow/short viewports. Mock browser checks
exercise its interactions and assert no backend requests. They do not establish connected behavior.

Implementation details: `Sidebar.tsx` owns presentation; `App.tsx` retains API orchestration. The
workspace card uses the shared styled select, with New workspace alongside archive actions in its menu.
`AnalysisSettings` retains its revision-aware polling/conflict recovery inside a native popover.
`SidebarPopover` bounds placement to the viewport without CSS anchor-positioning dependencies;
Escape/outside click dismiss it, resizing closes it, and confirmations restore focus to the trigger.
The Developer badge says Admin rather than incorrectly claiming a logged-in owner is locked.

At narrow widths the sidebar stacks above the meeting, preserving access to the main content.
At very short desktop heights the sidebar itself scrolls rather than clipping tools. Meeting dates
come from existing `created_at` metadata, labeled as creation time by their tooltip. No backend schema,
API, permission or retention changes are needed.

Verification: full Chrome browser regression suite passed (42 tests; one optional real Zoom fixture
skipped), along with lint, type checking and production build. Sidebar-specific tests cover native
menu dismissal, live archive rejection, offline/conflict recovery, scrolling, alignment and narrow
placement. Firefox remains the user testing browser; automated checks used installed Chrome.
