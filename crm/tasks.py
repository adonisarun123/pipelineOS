"""Celery tasks (AU-2). Import-safe without celery installed."""
try:
    from celery import shared_task
except ImportError:  # pragma: no cover
    def shared_task(*a, **k):  # noqa: D103
        def wrap(fn):
            return fn
        return wrap(a[0]) if a and callable(a[0]) else wrap


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def dispatch_event_task(self, event_type: str, payload: dict, tenant_id: int):
    """Queued event dispatch: consumers + webhooks, retried on transient failure."""
    from crm import events

    try:
        events.dispatch_now(event_type, payload, tenant_id)
    except Exception as exc:  # pragma: no cover - retry path needs a broker
        raise self.retry(exc=exc) from exc


@shared_task
def send_digest_task():
    from django.core.management import call_command

    call_command("send_daily_digest")


@shared_task
def time_automations_task():
    from django.core.management import call_command

    call_command("run_time_automations")
