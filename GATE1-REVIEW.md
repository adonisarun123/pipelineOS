# Gate 1 Readiness Review — vs spec §4 Phase 1 scope

Date: 2026-07-03 · Suite: 88 tests green · Coverage ~91% · Stack: Django 5.2 + DRF, React 18 + TS strict

## Phase 1 scope checklist

| Spec item | Status | Notes |
|---|---|---|
| Contacts (People/Organizations) | ✅ | Lists, search, person timeline, phones/emails (C-1..C-4) |
| Merge duplicates (C-5) | ✅ backend | Field-fill + child reassignment + audit breadcrumb; UI is API-only for now |
| Bulk edit (C-6) | ✅ | Owner/stage, admin+manager, notifies assignees |
| Leads inbox + qualify/convert (L-1..L-6) | ✅ | Dedupe, convert with lineage, disqualify reasons; L-7 webhook capture = Phase 2; L-8 SLA timer deferred |
| Deals kanban, multiple pipelines (D-1..D-3) | ✅ | Drag-drop, counts/totals, admin-configurable stages |
| Rotting (D-4) | ✅ | Red edge, rot-clock reset on stage change |
| Mandatory next activity (D-5) | ✅ | Prompt-not-block on create + last-activity-complete |
| Stage history (D-6) / Won-Lost (D-7) | ✅ | Append-only history; lost reason mandatory; won handoff action = Phase 2 automation |
| Deal list + inline filters (D-8) / detail (D-9) | ✅ | Detail slide-over: timeline, notes, products, files, custom fields |
| Activities + My Activities (A-1..A-5) | ✅ | Buckets, outcomes, quick-complete → schedule-next; calendar view deferred; digest = email (A-5) |
| Notes, files | ✅ | Notes in timeline; attachments with authenticated tenant-scoped download |
| Custom fields (CF-1..CF-4) | ✅ | Typed EAV + JSON cache, filters, importance + stage nudges |
| Products + line items (PR-1, PR-2) | ✅ | Auto-sum (pre-tax) or manual value |
| Search / filters / saved views (S-1..S-3) | ✅ partial | Global search + param filters + saved views; AND/OR filter-builder groups deferred |
| CSV import/export (I-1, I-3) | ✅ | Auto-map, dedupe, dry-run; exports audit-logged. I-2 migration mode (Pipedrive/Zoho) deferred |
| Users/teams/permissions (U-1..U-3) | ✅ | Matrix in PERMISSIONS.md, all rows tested; transfer + instant deactivation |
| Audit log (U-4) | ✅ | Append-only; login/export/import/transfer/merge; 24-mo retention job needs Celery |
| Multi-tenant foundation + REST API + event bus (§7) | ✅ | Fail-closed manager, CI isolation tests, HMAC webhooks live from Phase 1 |
| Notifications (N-1..N-3, Phase 1 portion) | ✅ | In-app center + assignment events + email digest |

## Gate 1 criteria (measured in production, not buildable)

≥90% new deals in-tool · ≥80% deals with next activity · deal creation ≤60s · zero data loss.
**These require 30 days of real usage post-deployment.** The tool-side prerequisites all exist.

## Before pilot go-live (ops, not code)

1. Deploy (DEPLOY.md) with `DJANGO_DEBUG=0`, strong `DJANGO_SECRET_KEY`, MySQL backups on.
2. Cron: `send_daily_digest` at 08:00 IST.
3. Import Trebound's real contacts (Import tab) + open deals; create real users; change seed passwords.
4. Manager runs weekly reviews only from the tool (spec §11 adoption mitigation).

## Known deferrals (all Phase 2+ per spec)

Email/WhatsApp sync, automation engine, dashboards beyond summary, webforms/chatbot capture (L-7),
SLA timers (L-8), calendar sync (A-3), Celery (async import/export, audit retention, digest via queue),
2FA for admins, merge UI, AND/OR filter builder, I-2 migration mode.
