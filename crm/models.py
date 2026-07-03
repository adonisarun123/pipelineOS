from django.conf import settings
from django.db import models
from django.utils import timezone

from tenants.models import TenantModel


class Organization(TenantModel):
    """C-2 (Phase 1 subset)."""

    name = models.CharField(max_length=255)
    industry = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    gstin = models.CharField(max_length=15, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    custom = models.JSONField(default=dict, blank=True)  # CF-4 read cache

    class Meta(TenantModel.Meta):
        indexes = [models.Index(fields=["tenant", "name"])]

    def __str__(self) -> str:
        return self.name


class Person(TenantModel):
    """C-1 (Phase 1 subset). Phones/emails in child tables (multiple, labeled)."""

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    job_title = models.CharField(max_length=100, blank=True)
    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.SET_NULL, related_name="people"
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    marketing_consent = models.BooleanField(default=False)  # DPDPA
    custom = models.JSONField(default=dict, blank=True)  # CF-4 read cache

    @property
    def name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class PersonPhone(TenantModel):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="phones")
    label = models.CharField(max_length=20, default="mobile")
    raw = models.CharField(max_length=30)
    normalized = models.CharField(max_length=20)  # E.164

    class Meta(TenantModel.Meta):
        indexes = [models.Index(fields=["tenant", "normalized"])]


class PersonEmail(TenantModel):
    person = models.ForeignKey(Person, on_delete=models.CASCADE, related_name="emails")
    label = models.CharField(max_length=20, default="work")
    email = models.EmailField()

    class Meta(TenantModel.Meta):
        indexes = [models.Index(fields=["tenant", "email"])]


class Pipeline(TenantModel):
    """D-1."""

    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return self.name


class Stage(TenantModel):
    """D-1: ordered, rotting threshold, win probability."""

    pipeline = models.ForeignKey(Pipeline, on_delete=models.CASCADE, related_name="stages")
    name = models.CharField(max_length=100)
    order = models.PositiveIntegerField()
    rot_days = models.PositiveIntegerField(null=True, blank=True)
    probability = models.PositiveIntegerField(null=True, blank=True)  # 0-100

    class Meta(TenantModel.Meta):
        ordering = ["order", "id"]


class LostReason(TenantModel):
    """D-2/L-4: configurable, mandatory on loss."""

    label = models.CharField(max_length=100)


class Deal(TenantModel):
    """D-2 (Phase 1 subset)."""

    class Status(models.TextChoices):
        OPEN = "open"
        WON = "won"
        LOST = "lost"

    title = models.CharField(max_length=255)
    value = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    currency = models.CharField(max_length=3, default="INR")
    pipeline = models.ForeignKey(Pipeline, on_delete=models.PROTECT, related_name="deals")
    stage = models.ForeignKey(Stage, on_delete=models.PROTECT, related_name="deals")
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="deals"
    )
    organization = models.ForeignKey(
        Organization, null=True, blank=True, on_delete=models.SET_NULL, related_name="deals"
    )
    people = models.ManyToManyField(Person, through="DealPerson", related_name="deals")
    expected_close_date = models.DateField(null=True, blank=True)
    probability = models.PositiveIntegerField(null=True, blank=True)  # per-deal override
    status = models.CharField(max_length=5, choices=Status.choices, default=Status.OPEN)
    lost_reason = models.ForeignKey(LostReason, null=True, blank=True, on_delete=models.PROTECT)
    closed_at = models.DateTimeField(null=True, blank=True)
    stage_entered_at = models.DateTimeField(default=timezone.now)
    custom = models.JSONField(default=dict, blank=True)  # CF-4 read cache
    value_auto = models.BooleanField(default=False)  # PR-2: auto-sum line items

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=["tenant", "owner", "status"]),
            models.Index(fields=["tenant", "pipeline", "stage"]),
        ]

    def __str__(self) -> str:
        return self.title


class DealPerson(TenantModel):
    deal = models.ForeignKey(Deal, on_delete=models.CASCADE)
    person = models.ForeignKey(Person, on_delete=models.CASCADE)
    is_primary = models.BooleanField(default=False)


class StageHistory(TenantModel):
    """D-6: append-only; powers funnel analytics. Never derive funnels from state."""

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="stage_history")
    from_stage = models.ForeignKey(Stage, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    to_stage = models.ForeignKey(Stage, on_delete=models.PROTECT, related_name="+")
    changed_at = models.DateTimeField(auto_now_add=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValueError("StageHistory is append-only.")
        return super().save(*args, **kwargs)


class ActivityType(TenantModel):
    """A-1: configurable types."""

    name = models.CharField(max_length=50)
    icon = models.CharField(max_length=30, blank=True)


class Activity(TenantModel):
    """A-1 (Phase 1 subset: linked to deal and/or person)."""

    class Outcome(models.TextChoices):
        CONNECTED = "connected"
        NO_ANSWER = "no_answer"
        BUSY = "busy"
        WRONG_NUMBER = "wrong_number"

    type = models.ForeignKey(ActivityType, on_delete=models.PROTECT, related_name="+")
    subject = models.CharField(max_length=255)
    due_at = models.DateTimeField()
    duration_min = models.PositiveIntegerField(null=True, blank=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="activities"
    )
    deal = models.ForeignKey(
        Deal, null=True, blank=True, on_delete=models.CASCADE, related_name="activities"
    )
    person = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.CASCADE, related_name="activities"
    )
    lead = models.ForeignKey(
        "crm.Lead", null=True, blank=True, on_delete=models.CASCADE, related_name="activities"
    )
    note = models.TextField(blank=True)
    done = models.BooleanField(default=False)
    done_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=12, choices=Outcome.choices, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [models.Index(fields=["tenant", "owner", "done", "due_at"])]

class Note(TenantModel):
    """Phase 1 notes; rendered in the timeline (C-4). Body is plain text."""

    body = models.TextField()
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    deal = models.ForeignKey(
        Deal, null=True, blank=True, on_delete=models.CASCADE, related_name="notes"
    )
    person = models.ForeignKey(
        Person, null=True, blank=True, on_delete=models.CASCADE, related_name="notes"
    )
    lead = models.ForeignKey(
        "crm.Lead", null=True, blank=True, on_delete=models.CASCADE, related_name="notes"
    )

    class Meta(TenantModel.Meta):
        indexes = [models.Index(fields=["tenant", "deal", "created_at"])]


# Sibling modules; imports register models with the app registry.
from .audit import AuditLog  # noqa: E402,F401
from .custom_fields import CustomFieldDef, CustomFieldValue  # noqa: E402,F401
from .leads import Lead, LeadSource  # noqa: E402,F401


class SavedView(TenantModel):
    """S-3: a view = filters + columns + sort; private or shared with team."""

    name = models.CharField(max_length=100)
    entity = models.CharField(max_length=15)  # deal / lead / person / organization
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_views"
    )
    params = models.JSONField(default=dict, blank=True)   # filter query params
    columns = models.JSONField(default=list, blank=True)
    sort = models.CharField(max_length=50, blank=True)
    is_shared = models.BooleanField(default=False)
    is_pinned = models.BooleanField(default=False)  # admins pin defaults per team

    class Meta(TenantModel.Meta):
        ordering = ["name"]


class Product(TenantModel):
    """PR-1: catalogue (Trebound: activities/venues/packages)."""

    name = models.CharField(max_length=255)
    sku = models.CharField(max_length=60, blank=True)
    category = models.CharField(max_length=100, blank=True)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18)  # GST %
    is_active = models.BooleanField(default=True)

    class Meta(TenantModel.Meta):
        indexes = [models.Index(fields=["tenant", "name"])]

    def __str__(self) -> str:
        return self.name


class DealLineItem(TenantModel):
    """PR-2: per-deal line items; unit price editable per deal."""

    deal = models.ForeignKey(Deal, on_delete=models.CASCADE, related_name="line_items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=1)
    unit_price = models.DecimalField(max_digits=14, decimal_places=2)
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2, default=18)

    @property
    def subtotal(self):
        """Pre-tax, post-discount. Deal value auto-sum uses this (pipeline value excl. GST)."""
        from decimal import Decimal

        gross = self.quantity * self.unit_price
        return (gross * (Decimal("100") - self.discount_pct) / Decimal("100")).quantize(
            Decimal("0.01"))
