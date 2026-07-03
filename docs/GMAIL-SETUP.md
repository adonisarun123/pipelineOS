# Gmail sync (E-1) — activation steps

The EmailAccount model, connect/disconnect API, and Settings UI ship now.
Live two-way sync (Phase 2, spec E-1) activates once you provide OAuth credentials:

1. Google Cloud Console → create project "PipelineOS" → enable **Gmail API**.
2. OAuth consent screen: Internal (Workspace) or External; scopes:
   `gmail.readonly`, `gmail.send`, `gmail.modify`.
3. Credentials → OAuth Client ID (Web application). Authorized redirect URI:
   `https://<api-domain>/api/v1/email-account/callback/`.
4. Set backend env vars: `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`.
5. The Phase 2 sync worker (Celery) then handles: token exchange + refresh,
   history-id incremental sync, thread→deal matching (E-1), send-from-deal (E-2),
   linked-only privacy scope (E-3, already the stored default).

Until then, "Connect mailbox" stores the address with status `pending` and the UI
shows what's missing. Tokens are stored encrypted per tenant in production (spec §8) —
never returned by any API response.

## Digest email (works today)

`python manage.py send_daily_digest` — schedule via cron at 08:00 IST.
Dev prints to console; production needs `EMAIL_HOST/PORT/USER/PASSWORD` env
(any SMTP: Google Workspace, SES Mumbai, Zoho).
