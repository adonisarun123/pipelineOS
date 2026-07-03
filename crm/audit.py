"""Audit log (U-4) + export logging (I-3): exports are the #1 data-theft vector."""
from django.conf import settings
from django.db import models

from tenants.models import TenantModel


class AuditLog(TenantModel):
    """Append-only. Retained 24 months (retention job lands with Celery, Phase 2)."""

    class Action(models.TextChoices):
        CREATE = "create"
        UPDATE = "update"
        DELETE = "delete"
        EXPORT = "export"
        LOGIN = "login"
        CONVERT = "convert"
        IMPORT = "import"
        TRANSFER = "transfer"

    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True,
                              on_delete=models.SET_NULL, related_name="+")
    action = models.CharField(max_length=10, choices=Action.choices)
    model_name = models.CharField(max_length=40, blank=True)
    object_id = models.BigIntegerField(null=True, blank=True)
    detail = models.JSONField(default=dict, blank=True)  # changes / row_count / filters
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [models.Index(fields=["tenant", "action", "created_at"])]

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("AuditLog is append-only.")
        return super().save(*args, **kwargs)


def client_ip(request) -> str | None:
    fwd = request.META.get("HTTP_X_FORWARDED_FOR")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR")) or None


def log(*, actor, action: str, model_name: str = "", object_id=None,
        detail: dict | None = None, request=None, tenant_id=None) -> None:
    entry = AuditLog(actor=actor, action=action, model_name=model_name,
                     object_id=object_id, detail=detail or {},
                     ip=client_ip(request) if request is not None else None)
    if tenant_id is not None:
        entry.tenant_id = tenant_id
    entry.save()
