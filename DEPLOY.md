# Deployment — Vercel (frontend) + Railway/Render (backend)

Architecture: React SPA on Vercel; Django API + MySQL + (Phase 2: Redis/Celery) on Railway
or Render. Vercel cannot run Django/Celery/MySQL — do not try.

## 1. Push to GitHub

```bash
cd pipelineos
git remote add origin git@github.com:<you>/pipelineos.git
git push -u origin main
```

## 2. Backend (Railway shown; Render is equivalent)

1. railway.app → New Project → Deploy from GitHub repo → root = repo root (Dockerfile detected).
2. Add a MySQL database plugin. Then set service env vars:
   - `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DB`, `MYSQL_USER`, `MYSQL_PASSWORD` (from the plugin)
   - `DJANGO_SECRET_KEY` = long random string
   - `DJANGO_DEBUG` = `0`
   - `DJANGO_ALLOWED_HOSTS` = `<your-api-domain>`
   - `CORS_ALLOWED_ORIGINS` = `https://<your-app>.vercel.app`
3. First deploy runs migrations automatically. Seed once via a one-off command:
   `python manage.py seed_trebound` (set `SEED_PASSWORD` first).

## 3. Frontend (Vercel)

1. vercel.com → Add New Project → import the repo → **Root Directory: `frontend`**.
2. Framework preset: Vite (auto-detected). Build `npm run build`, output `dist`.
3. Env var: `VITE_API_BASE` = `https://<your-api-domain>` (no trailing slash).
4. Deploy. `vercel.json` already handles SPA rewrites.

## 4. Single-server alternative (internal deployment, spec §7)

Skip Vercel: build the frontend (`cd frontend && npm run build`) and Django serves it at `/`.
This is the simplest option for the Phase 1 internal pilot.

## Notes

- India data residency (spec §8/DPDPA): Railway/Render have no Mumbai region as of mid-2026 —
  verify before storing production customer PII, or use the spec's own answer (DO/AWS Mumbai
  VM with this same Dockerfile) once the pilot goes live. For pilot/demo data this is fine.
- HTTPS is automatic on both platforms; `SECURE_PROXY_SSL_HEADER` is already configured.
- Backups: enable the DB plugin's automated backups; spec requires PITR + quarterly restore drills.
