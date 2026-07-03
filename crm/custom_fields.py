"""Custom fields (CF-1..CF-4): typed EAV + denormalized JSON cache on the parent.

Never store values as untyped JSON only — filtering and reporting would crawl
(spec CF-4). The `custom` JSONField on Deal/Person/Organization is a read cache,
rebuilt on every write; the typed columns are the source of truth.
"""
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction

from tenants.models import TenantModel

ENTITIES = ("deal", "person", "organization")


class CustomFieldDef(TenantModel):
    class Type(models.TextChoices):
        TEXT = "text"
        LONG_TEXT = "long_text"
        NUMBER = "number"
        CURRENCY = "currency"
        DATE = "date"
        DATETIME = "datetime"
        SINGLE_SELECT = "single_select"
        MULTI_SELECT = "multi_select"
        CHECKBOX = "checkbox"
        PHONE = "phone"
        EMAIL = "email"
        URL = "url"
        USER = "user"

    entity = models.CharField(max_length=15, choices=[(e, e) for e in ENTITIES])
    name = models.CharField(max_length=100)
    key = models.SlugField(max_length=60)
    field_type = models.CharField(max_length=15, choices=Type.choices)
    options = models.JSONField(default=list, blank=True)  # select choices
    is_important = models.BooleanField(default=False)  # CF-2: shown prominently
    nudge_stage_order = models.PositiveIntegerField(  # CF-2: nudge if empty at/after this stage
        null=True, blank=True)
    pipeline = models.ForeignKey(  # CF-2: per-pipeline visibility (null = all)
        "crm.Pipeline", null=True, blank=True, on_delete=models.CASCADE
    )
    order = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["tenant", "entity", "key"],
                                    name="uniq_cf_key_per_entity"),
        ]


class CustomFieldValue(TenantModel):
    """One row per (definition, record). Typed columns per CF-4."""

    definition = models.ForeignKey(CustomFieldDef, on_delete=models.CASCADE, related_name="values")
    record_id = models.BigIntegerField()  # id of deal/person/org (entity on the def)
    value_text = models.TextField(blank=True, default="")
    value_number = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    value_date = models.DateField(null=True, blank=True)
    value_datetime = models.DateTimeField(null=True, blank=True)
    value_bool = models.BooleanField(null=True, blank=True)
    value_json = models.JSONField(null=True, blank=True)  # multi_select
    value_user = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL, related_name="+")

    class Meta(TenantModel.Meta):
        constraints = [
            models.UniqueConstraint(fields=["tenant", "definition", "record_id"],
                                    name="uniq_cf_value_per_record"),
        ]
        indexes = [
            models.Index(fields=["tenant", "definition", "value_text"],
                         name="cfv_text_idx"),
            models.Index(fields=["tenant", "definition", "value_number"],
                         name="cfv_number_idx"),
            models.Index(fields=["tenant", "definition", "value_date"],
                         name="cfv_date_idx"),
        ]


_TEXT_TYPES = {"text", "long_text", "single_select", "phone", "email", "url"}


def coerce(defn: CustomFieldDef, value):
    """Validate + coerce an inbound value; returns (column_name, coerced)."""
    t = defn.field_type
    if value in (None, "", []):
        return None, None  # clears the value
    if t in _TEXT_TYPES:
        value = str(value).strip()
        if t == "email" and "@" not in value:
            raise ValidationError(f"{defn.name}: invalid email")
        if t == "single_select" and defn.options and value not in defn.options:
            raise ValidationError(f"{defn.name}: '{value}' not in options")
        return "value_text", value
    if t in ("number", "currency"):
        try:
            return "value_number", Decimal(str(value))
        except InvalidOperation:
            raise ValidationError(f"{defn.name}: not a number") from None
    if t == "date":
        from django.utils.dateparse import parse_date

        d = parse_date(str(value))
        if d is None:
            raise ValidationError(f"{defn.name}: invalid date (YYYY-MM-DD)")
        return "value_date", d
    if t == "datetime":
        from django.utils.dateparse import parse_datetime

        d = parse_datetime(str(value))
        if d is None:
            raise ValidationError(f"{defn.name}: invalid datetime")
        return "value_datetime", d
    if t == "checkbox":
        return "value_bool", value in (True, "true", "True", "1", 1)
    if t == "multi_select":
        if not isinstance(value, list):
            raise ValidationError(f"{defn.name}: expected a list")
        bad = [v for v in value if defn.options and v not in defn.options]
        if bad:
            raise ValidationError(f"{defn.name}: {bad} not in options")
        return "value_json", value
    if t == "user":
        from accounts.models import User

        u = User.objects.filter(pk=value, tenant_id=defn.tenant_id).first()
        if u is None:
            raise ValidationError(f"{defn.name}: unknown user")
        return "value_user", u
    raise ValidationError(f"Unsupported field type {t}")  # pragma: no cover


def _display(column: str, coerced) -> object:
    if column == "value_number":
        return f"{coerced.normalize():f}"  # "120", not "120.0000"
    if column in ("value_date", "value_datetime"):
        return coerced.isoformat()
    if column == "value_user":
        return coerced.pk
    return coerced


@transaction.atomic
def set_custom_values(record, entity: str, values: dict, user) -> dict:
    """Write typed values + rebuild the JSON cache on the record. Returns cache."""
    defs = {d.key: d for d in CustomFieldDef.objects.filter(entity=entity)}
    unknown = set(values) - set(defs)
    if unknown:
        raise ValidationError(f"Unknown custom field(s): {sorted(unknown)}")
    for key, raw in values.items():
        defn = defs[key]
        column, coerced = coerce(defn, raw)
        existing = CustomFieldValue.objects.filter(
            definition=defn, record_id=record.pk).first()
        if column is None:
            if existing:
                existing.is_deleted = True
                existing.save(update_fields=["is_deleted", "updated_at"])
            continue
        if existing is None:
            existing = CustomFieldValue(definition=defn, record_id=record.pk,
                                        created_by=user)
        for col in ("value_text", "value_number", "value_date", "value_datetime",
                    "value_bool", "value_json", "value_user"):
            setattr(existing, col, "" if col == "value_text" else None)
        setattr(existing, column, coerced)
        existing.is_deleted = False
        existing.save()
    return rebuild_cache(record, entity)


def rebuild_cache(record, entity: str) -> dict:
    """Denormalized read cache (CF-4)."""
    cache: dict = {}
    rows = CustomFieldValue.objects.filter(
        definition__entity=entity, record_id=record.pk).select_related("definition")
    for v in rows:
        for col in ("value_text", "value_number", "value_date", "value_datetime",
                    "value_bool", "value_json", "value_user"):
            val = getattr(v, col)
            if val not in (None, ""):
                cache[v.definition.key] = _display(col, val)
                break
    type(record).objects.filter(pk=record.pk).update(custom=cache)
    record.custom = cache
    return cache
