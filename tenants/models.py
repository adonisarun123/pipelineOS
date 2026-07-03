from django.conf import settings
from django.db import models

from .context import TenantContextError, get_current_tenant_id
from .managers import TenantManager

PLANS = {
    # Phase 3 pricing thesis: don't punish headcount (spec §2.2)
    "trial": {"seats": 5, "trial_days": 14, "price_inr": 0},
    "starter": {"seats": 10, "trial_days": None, "price_inr": 4999},
    "growth": {"seats": 25, "trial_days": None, "price_inr": 9999},
    "internal": {"seats": 999, "trial_days": None, "price_inr": 0},  # own ventures
}


class Tenant(models.Model):
    """A customer workspace. Internal ventures are tenants from day 1 (spec §1)."""

    name = models.CharField(max_length=200)
    subdomain = models.SlugField(max_length=63, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    plan = models.CharField(max_length=10, default="internal",
                            choices=[(p, p) for p in PLANS])
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    billing = models.JSONField(default=dict, blank=True)  # razorpay ids; never exposed raw

    def __str__(self) -> str:
        return self.name

    @property
    def seats_limit(self) -> int:
        return PLANS[self.plan]["seats"]

    @property
    def is_writable(self) -> bool:
        """Trial expiry → read-only, never data loss (DPDPA export still works)."""
        from django.utils import timezone

        if self.plan != "trial" or self.trial_ends_at is None:
            return True
        return timezone.now() <= self.trial_ends_at


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
