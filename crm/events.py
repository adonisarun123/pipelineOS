"""Internal event bus (§7): post-commit signals → consumers.

Phase 1: synchronous consumers (in-process registry + outbound webhooks with a
short timeout). Phase 2 swaps delivery to Celery without changing emit() calls —
"emitting events nobody consumes yet is cheap; retrofitting eventing is painful".
"""
import hashlib
import hmac
import json
import logging
import urllib.request
from typing import Callable

from django.db import transaction
from django.utils import timezone

logger = logging.getLogger("pipelineos.events")

_consumers: list[Callable[[str, dict, int], None]] = []
WEBHOOK_TIMEOUT_S = 3


def register(consumer: Callable[[str, dict, int], None]) -> None:
    _consumers.append(consumer)


def dispatch_now(event_type: str, payload: dict, tenant_id: int) -> None:
    """Synchronous dispatch: consumers + webhooks. Celery task calls this too."""
    for consumer in list(_consumers):
        try:
            consumer(event_type, payload, tenant_id)
        except Exception:  # consumers must never break the request
            logger.exception("Event consumer failed for %s", event_type)
    _deliver_webhooks(event_type, payload, tenant_id)


def emit(event_type: str, payload: dict, tenant_id: int) -> None:
    """Fire after the surrounding transaction commits (never on rollback).
    AU-2: routed through Celery when a broker is configured; sync otherwise."""
    from django.conf import settings

    def _dispatch():
        if getattr(settings, "USE_CELERY", False):
            from .tasks import dispatch_event_task

            dispatch_event_task.delay(event_type, payload, tenant_id)
        else:
            dispatch_now(event_type, payload, tenant_id)

    transaction.on_commit(_dispatch)


def _deliver_webhooks(event_type: str, payload: dict, tenant_id: int) -> None:
    from tenants.context import tenant_context

    from .models import WebhookSubscription

    with tenant_context(tenant_id):
        subs = list(WebhookSubscription.objects.filter(is_active=True))
        for sub in subs:
            if sub.events and event_type not in sub.events:
                continue
            body = json.dumps({"event": event_type, "data": payload,
                               "ts": timezone.now().isoformat()}).encode()
            signature = hmac.new(sub.secret.encode(), body, hashlib.sha256).hexdigest()
            try:
                _post(sub.url, body, signature)
                WebhookSubscription.objects.filter(pk=sub.pk).update(
                    last_delivery_at=timezone.now(), last_error="")
            except Exception as exc:  # log + record, never raise (fire-and-forget P1)
                logger.warning("Webhook delivery to %s failed: %s", sub.url, exc)
                WebhookSubscription.objects.filter(pk=sub.pk).update(
                    last_error=str(exc)[:255])


def _post(url: str, body: bytes, signature: str) -> None:
    """Isolated for test monkeypatching."""
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Content-Type": "application/json",
                 "X-PipelineOS-Signature": f"sha256={signature}"})
    urllib.request.urlopen(req, timeout=WEBHOOK_TIMEOUT_S)  # noqa: S310 - subscriber URLs are admin-configured
