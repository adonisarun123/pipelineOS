# Changelog

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
