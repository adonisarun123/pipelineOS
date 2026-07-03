# Changelog

## [0.4.0] — 2026-07-03 (Increments 3–5)

### Added
- My Activities buckets + call outcomes (A-2/A-4); deal detail slide-over with timeline
  and notes (C-4/D-9); schedule-next prompts on create/complete (D-5).
- Global search with `/` shortcut and country-code-agnostic phone match (S-1);
  deal list filters + kanban owner toggle (S-2 subset).
- CSV contact import: auto-map, dedupe (skip/update/create), dry-run, per-row errors,
  wizard UI (I-1).
- Custom fields: typed EAV + denormalized JSON cache, `cf_<key>` filters, deal detail
  editor, important-field flags, Trebound seeds (CF-1..4).
- Append-only audit log (login/export/import) + role-gated, audit-logged CSV export
  (U-4/I-3).

### Evidence
59 tests, ~92% coverage, ruff + tsc strict clean, live smoke per increment report.

## [0.2.0] — 2026-07-03 (Increment 2: Leads + TypeScript frontend + deploy)

### Added
- Leads module (L-1..L-6): queue with status dispositions, configurable sources + UTM capture,
  duplicate detection on normalized phone/email/org, one-click convert-to-deal carrying
  activities/notes with full lineage, disqualify with mandatory reason.
- Frontend migrated to Vite + React 18 + TypeScript strict: kanban port + new leads inbox
  (dupe warnings, convert dialog, status pills). Django serves the built SPA for
  single-server deploys.
- Deployment: Dockerfile (gunicorn, auto-migrate), Vercel config + `VITE_API_BASE`,
  CORS via django-cors-headers, DEPLOY.md runbook. Git repo with conventional commits.

### Evidence
38/38 tests, 90% coverage, ruff clean, tsc strict clean, Vite build 49 kB gz, live smoke:
seeded leads listed, dupe hit on reformatted phone, convert produced deal + person found
as duplicate post-conversion, built SPA + assets served 200.

## [0.1.0] — 2026-07-03 (Increment 1: Foundation + Deals Kanban)

### Added
- Multi-tenant foundation: fail-closed `TenantManager`, tenant-binding token auth,
  context middleware, cross-tenant isolation test suite (spec §7/§8).
- Users/teams/roles (Admin/Manager/Member/ReadOnly) with own/team/all visibility (U-1, U-2);
  instant deactivation kills API tokens (U-3).
- Pipelines with ordered stages, rot thresholds, probabilities (D-1).
- Deals: lifecycle services, append-only StageHistory (D-6), mandatory lost reason (D-2),
  rotting (D-4), needs-next-activity flag (D-5).
- Activities with outcomes and complete-→-prompt-next flow (A-1, A-4).
- Organizations/People minimal with E.164 phone normalization (C-1..C-3 subset).
- REST API `/api/v1/` with cursor pagination, role permissions, kanban endpoint (D-3).
- React kanban SPA: login, board, drag-drop stage move, quick-add, won/lost, rot/next-activity flags.
- Trebound seed command (3 pipelines, demo deals incl. one rotten).

### Evidence
30/30 tests green, 90% coverage (services 95%), ruff clean, E2E smoke against live server.
