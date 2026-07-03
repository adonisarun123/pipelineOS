# PipelineOS — Phase 1 Backlog (Increment 1: Foundation + Deals Kanban)

Pilot config: Trebound. Dev DB: SQLite (MySQL 8-ready — no SQLite-only features). Spec refs in parens.

## Increment 1 stories (this increment)

### S1 — Tenant isolation foundation (§7, §8)
As an ops/admin, all data is isolated per tenant so a future SaaS launch is safe from day 1.
- Given two tenants with data, when any model query runs via `Model.objects`, then only the current tenant's rows return.
- Given no tenant in context, when `Model.objects` is used on a tenant-scoped model, then it raises (fail closed).
- Given tenant A's auth token, when any API endpoint is called for tenant B's record id, then 404 (not 403 — no existence leak).
- CI test scans code for raw unscoped manager usage on tenant models.

### S2 — Users, teams, roles (U-1, U-2)
As an admin, I manage users with roles Admin/Manager/Member/ReadOnly on teams.
- Given a Member, when they list deals, then only own deals return; Manager sees team's; Admin sees all.
- Given a ReadOnly user, when they POST/PATCH/DELETE, then 403.

### S3 — Pipelines and stages (D-1)
As an admin, I configure pipelines with ordered stages, rot_days, win probability.
- Given Trebound seed, when I list pipelines, then "Corporate Events IN" exists with ordered stages incl. rot thresholds.
- Stages are ordered; reordering persists.

### S4 — Deal lifecycle (D-2, D-5, D-6)
As a rep, I create deals and move them through stages; every stage change is history-logged.
- Given a deal, when stage changes, then a STAGE_HISTORY row (from, to, actor, ts) is appended; history is never updated.
- Given mark-Lost without lost_reason, then validation error; Won/Lost set status + closed date.
- Deal without a planned activity is flagged `needs_next_activity=true` in API payload (prompt, don't block).

### S5 — Kanban board API (D-3, D-4)
As a rep, I see my pipeline as a kanban with counts, totals, rotting.
- Given deals in stages, when GET kanban, then per-stage: deal cards (title, org, value, owner, rotten flag, next-activity flag), count, total value.
- Given a deal with no completed activity within stage.rot_days, then `is_rotten=true`.
- Stage-move endpoint validates stage belongs to deal's pipeline.

### S6 — Activities minimal (A-1 subset)
As a rep, I schedule/complete activities on deals so rotting and next-activity logic work.
- Given completing an activity, then response includes `prompt_next=true` for the deal (D-5).
- Activity types seeded: Call, Meeting, Task, Deadline, WhatsApp follow-up.

### S7 — Org/Person minimal (C-1..C-3 subset)
As a rep, deals link to an Organization and People (primary contact flag).
- Person: name, phones (E.164 normalized + raw), emails, org link, owner.
- Phone normalization: "+91 98765 43210" and "9876543210" match.

### S8 — React kanban UI (D-3, D-4, D-5)
As a rep, I log in and drag deals across stages.
- Board renders columns with count + Σ value; drag-drop calls stage-move; rotten deals show red edge; deals without next activity flagged.

## Deferred to next increments (Phase 1 remainder)
Leads inbox + convert (L-1..L-6, L-8) · custom fields typed EAV (CF-1..4) · notes/files · products/line items (PR-1..2) · search/filters/saved views (S-1..3) · CSV import/export (I-1..3) · audit log full (U-4) · record transfer (U-3) · email digest (N-3) · event bus consumers · merge duplicates (C-5) · bulk edit (C-6).

## Out of scope (per spec)
Phase 2/3 items; marketing automation; ticketing; invoicing; native apps; AI scoring.
