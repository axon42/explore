# Profiles, personal spaces and teams

2026-09-12. Proposed architecture, not implemented. Team invitations are admin-only, as confirmed.

## Product decision
One human profile/sign-in can have a private personal account and memberships in multiple team
accounts. The sidebar switches account, then workspace, then meeting. Do not create two login
systems or shared team passwords. Personal and team describe ownership containers, not people.

For the first release, all members of a team account can access its shared workspaces and
meetings, questions, notes and reports. Team admins administer that access. Private subspaces
inside a team and per-meeting guest permissions are deferred; this inheritance must be visible
when creating a workspace or accepting an invitation.

Interview participants are separate from app users. Customers need no account to be named in
an interview. A roster entry grants no access to the workspace.

## Small data model
| Entity | Purpose / invariants |
| --- | --- |
| users | App ID, unique managed-auth subject, verified email, display name; optional avatar later |
| accounts | ID, `personal` or `team`, name; personal owner user ID unique, team owner represented through admin memberships |
| memberships | Account + user unique; `admin` or `member`; removal revokes access |
| workspaces | Existing ID/name plus required account ID; inherits membership |
| invitations | Account, normalized email, intended role, inviter, expiry, token hash, accepted/revoked timestamps |
| audit_events | Actor, account, operation, target and time; no transcript bodies or raw invite tokens |

Meetings remain workspace-owned; sessions, transcript revisions, artifacts and evidence inherit
that ownership. Avoid copying account IDs to every child without a demonstrated query need.
All repositories authorize by joining the owning workspace/account, including exports and streams.
Personal accounts admit only their owner; invitations target team accounts only.

## Permission defaults
| Action | Personal owner | Team admin | Team member |
| --- | --- | --- | --- |
| Read shared content and download reports | Yes | Yes | Yes |
| Create/edit meetings, questions and notes; capture own local audio | Yes | Yes | Yes |
| Archive/restore meetings | Yes | Yes | Yes |
| Invite/remove members, change roles, create/delete shared workspaces | N/A | Yes | No |
| Configure provider keys/budgets, bulk delete | Yes | Yes | No |

Never remove/demote the last team admin; transfer administration transactionally. Concurrent
role changes and membership removal must not leave stale access. Human notes preserve authorship
and version checks. Member content is shared by design, not silently private.

## Invitation and sign-in flow
Admin invites a specific email → recipient signs in/verifies that email → accepts the invitation
→ membership is inserted atomically. Use expiring single-use random tokens stored hashed;
acceptance requires matching verified identity. Replays are idempotent. Revocation/expiry and
already-member states are explicit. No self-join or domain-wide automatic membership.

Use a maintained managed-auth solution; choose the provider before implementation after checking
current pricing, session/email flows and deployment fit. Do not build password storage, reset
emails or OAuth security from scratch. Invite delivery is product functionality planned for later;
this task sends no messages. Billing/subscription plans remain undecided.

## Migration and hosting dependencies
- Before auth rollout, back up the local DB and rehearse transactional migration on a copy.
  Existing workspaces must be explicitly claimed into the owner's personal account after sign-in;
  do not guess an owner from the first arbitrary visitor or infer a team from participant names.
- Keep public routing off until every read/write/WebSocket/export checks membership. Test
  cross-team/personal isolation, revoked membership, CSRF/session expiry, duplicate invitations,
  stale optimistic revisions, last-admin races and provider-budget ownership.
- Browser-local mode preferences must not become permissions. Production keys stay server-side.
  Add per-account limits/reservations before shared provider use; retain existing hard caps.
- Cloud hosting cannot launch a helper on the user's Mac. Design explicit short-lived, authenticated
  capture pairing and revocation; the hosted app must never assume localhost helper ownership.
- Keep SQLite for local prototype work. Decide hosted DB/worker topology with concurrency and
  backups before migration; no speculative database rewrite in the capture repair.

See [roadmap](../docs/roadmap.md) and [interview lifecycle](interview-readiness.md).

## Local developer exception — implemented 2026-09-14
The local owner can unlock Developer diagnostics with a private bootstrap key. This grants access
only to diagnostic endpoints and is not a user profile, team account or membership system. The normal
app remains loopback-only. Before hosting, replace this gate with managed authentication and an
account-scoped admin check, and disable key bootstrap. See [observability](observability.md).
