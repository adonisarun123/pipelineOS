from django.conf import settings
from django.db import models

from .context import TenantContextError, get_current_tenant_id
from .managers import TenantManager


class Tenant(models.Model):
    """A customer workspace. Internal ventures are tenants from day 1 (spec §1)."""

    name = models.CharField(max_length=200)
    subdomain = models.SlugField(max_length=63, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.name


class TenantModel(models.Model):
    """Abstract base for all tenant-scoped tables (spec §6 common columns)."""

    tenant = models.ForeignKey(Tenant, on_delete=models.PROTECT, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    is_deleted = models.BooleanField(default=False)

    objects = TenantManager()
    # Unscoped manager: use forbidden outside tenants/, seeds, migrations
    # (enforced by tests/test_no_raw_manager.py).
    unscoped = models.Manager()  # noqa: DJ012 — must follow tenant-scoped default manager

    class Meta:
        abstract = True
        base_manager_name = "unscoped"
        default_manager_name = "objects"

    def save(self, *args, **kwargs):
        if self.tenant_id is None:
            tenant_id = get_current_tenant_id()
            if tenant_id is None:
                raise TenantContextError(
                    f"Cannot save {type(self).__name__} without a tenant in context."
                )
            self.tenant_id = tenant_id
        return super().save(*args, **kwargs)
