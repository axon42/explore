# Shared dropdowns

2026-09-15 · Implemented for the connected Explore application.

## Problem and scope
Native option popups follow browser/OS styling, so styling only the closed select left Firefox's
workspace menu inconsistent. One shared component now covers workspace selection, analysis mode,
archive/developer/spoken-question filters, interview roles, microphone/voice attribution, report
revisions, playback speed, injected speaker and question frequency. Historical standalone design
previews and the third-party Zoom toolkit are outside this connected-app change.

## Implementation decisions
- `frontend/src/explore/Select.tsx` wraps `@radix-ui/react-select` 2.3.7 (MIT; React 19 compatible).
  Use its focus management, keyboard navigation, typeahead and collision positioning instead of
  maintaining a custom combobox. Install only the select package, not a full UI framework.
  [Official API](https://www.radix-ui.com/primitives/docs/components/select).
- Plain option children retain readable values/labels at each call site. The wrapper maps them to
  Radix items and emits the original string through `onValueChange`; numeric settings explicitly
  convert at their existing boundary. Empty filter/assignment choices use an internal prefix so
  they remain real selectable values. No API, database, role or identity inference changes.
- `select.css` owns trigger/menu spacing, borders, blue focus/selection state, disabled styling and
  checkmarks. Its stylesheet loads after surface/sidebar rules so those rules cannot silently
  override a selector. Workspace/playback controls have compact sizing within the same visual system.
  Long labels wrap in menus; long lists scroll and menus stay within viewport bounds.
- Portal into the nearest native dialog/popover, otherwise the Explore root. This retains theme
  tokens and keeps options above capture/speaker dialogs rather than behind the native top layer.
  Escape closes one layer at a time. A save temporarily disabling the trigger must not lose focus;
  restore it after save only when focus has not moved elsewhere. Outer popovers restore their
  trigger on keyboard dismissal; outside clicks retain the user's intended focus target.
- Menus render text only. Existing disabled fields, save/conflict handling, ownership checks,
  archive guards and speaker confirmation stay in their original owners.

## Verification
Browser coverage exercises visible menus instead of changing hidden native selects: workspace
persistence, keyboard/typeahead, Escape/outside dismissal, long labels/lists, mobile bounds,
nested capture/speaker dialogs, analysis polling/conflicts/offline state and save focus.
All fixtures use disposable storage and mocked providers. No microphone or paid model calls.
Automated Firefox installation is unavailable on this machine (`mac13-arm64` unsupported by the
installed Playwright); use Chrome automation and retain Firefox at localhost:5173 for user testing.
Production bundle measurement: approximately 121 kB gzip JavaScript, versus 92 kB before the
shared primitive. This is the cost of maintained accessible menu behavior; no new runtime service.

Verified: lint, TypeScript and production build pass. Across the full regression run and final
focused rerun, 45 distinct browser tests pass; one optional real Zoom toolkit fixture is skipped.
Desktop/mobile workspace, analysis and participant menus were visually inspected using synthetic data.
