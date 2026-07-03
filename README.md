# PipelineOS

Pipeline-first CRM (spec: `PipelineOS-Product-Spec-v1.md`). Django 5.2 + DRF backend,
React SPA frontend, multi-tenant from day 1.

## Run locally

```bash
pip install -r requirements.txt
python manage.py migrate            # SQLite by default; set MYSQL_* env for MySQL 8
python manage.py seed_trebound      # idempotent; SEED_PASSWORD env overrides default
python manage.py runserver
```

Open http://127.0.0.1:8000 — sign in as `rep1` / `trebound@2026!` (or admin/manager/rep2).
If your filesystem doesn't support SQLite locking, set `DJANGO_DB_PATH=/tmp/pipelineos.sqlite3`.

## Verify

```bash
pytest --cov=.        # full suite + coverage
ruff check .          # lint
```

## Architecture notes (spec §7)

- **Tenancy:** `tenants.TenantModel` base + mandatory `TenantManager` — `Model.objects`
  always filters by the tenant bound at authentication and fails closed without one.
  The unscoped manager (`Model.unscoped`) is forbidden outside `tenants/`, migrations,
  and tests — enforced by `tests/test_no_raw_manager.py`.
- **Service layer:** business logic in `crm/services.py`; views are thin. Imports,
  automation (Phase 2), and the API share this one code path.
- **Append-only `StageHistory`** powers funnel analytics — never derive funnels from state.
- **Frontend:** build-free React 18 (ESM CDN + htm) in `frontend/index.html`, served raw
  at `/`. Migrate to Vite + TypeScript strict when the repo moves to a dev machine with
  a normal node toolchain; the API contract is the stable boundary.

## API (Phase 1, internal)

`POST /api/v1/auth/login/` · `GET /api/v1/pipelines/` · `GET /api/v1/pipelines/{id}/kanban/`
· CRUD `/api/v1/deals/` + `POST {id}/move|won|lost/` · CRUD `/api/v1/activities/` +
`POST {id}/complete/` · CRUD `/api/v1/organizations/`, `/api/v1/people/` · `GET /api/v1/lost-reasons/`

Status: see `BACKLOG.md` for increment plan and `CHANGELOG.md` for history.
