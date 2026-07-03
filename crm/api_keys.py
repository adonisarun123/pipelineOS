"""API-1: tenant API keys. The raw key (pk_live_...) is shown exactly once at
creation; only a SHA-256 hash is stored. Scope 'read' blocks all writes."""
import hashlib
import secrets

from django.conf import settings
from django.db import models

from tenants.models import TenantModel

KEY_PREFIX = "pk_live_"


class ApiKey(TenantModel):
    class Scope(models.TextChoices):
        READ = "read"
        WRITE = "write"  # read + write

    name = models.CharField(max_length=100)
    key_hash = models.CharField(max_length=64, unique=True)
    prefix_hint = models.CharField(max_length=16)  # pk_live_ab… for identification
    scope = models.CharField(max_length=5, choices=Scope.choices, default=Scope.READ)
    is_active = models.BooleanField(default=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    acting_user = models.ForeignKey(  # requests attribute to this user (audit, visibility)
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_keys")

    @staticmethod
    def hash_key(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def generate(cls, *, name: str, scope: str, acting_user, created_by) -> tuple["ApiKey", str]:
        raw = KEY_PREFIX + secrets.token_urlsafe(32)
        key = cls(name=name, key_hash=cls.hash_key(raw),
                  prefix_hint=raw[:12] + "…", scope=scope,
                  acting_user=acting_user, created_by=created_by)
        key.save()
        return key, raw
