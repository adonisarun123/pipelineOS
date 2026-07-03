"""Automation engine (AU-1..AU-4): Trigger → Conditions → Actions.

Runs synchronously as an event-bus consumer in this increment; AU-2's Celery
queueing swaps the dispatch layer without touching rules, conditions, or actions.
Loop protection (AU-3): automation-caused events carry a depth counter via
contextvar; chains stop at MAX_DEPTH.
"""
import contextvars
import logging
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.utils import timezone

from tenants.models import TenantModel

logger = logging.getLogger("pipelineos.automation")

MAX_DEPTH = 3
_depth: contextvars.ContextVar[int] = contextvars.ContextVar("automation_depth", default=0)

TRIGGERS = [
    "deal.created", "deal.stage_changed", "deal.won", "deal.lost",
    "lead.created", "lead.converted", "activity.completed",
]
OPS = ("eq", "ne", "gt", "gte", "lt", "lte", "contains", "in")


class AutomationRule(TenantModel):
    """AU-1. conditions = {"all": [...], "any": [...]}; each {field, op, value}.
    `field` may be a standard field or "custom.<key>". actions = [{type, ...params}]."""

    name = models.CharField(max_length=200)
    trigger = models.CharField(max_length=40, choices=[(t, t) for t in TRIGGERS])
    pipeline = models.ForeignKey("crm.Pipeline", null=True, blank=True,
                                 on_delete=models.CASCADE)  # null = global
    conditions = models.JSONField(default=dict, blank=True)
    actions = models.JSONField(default=list)
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        ordering = ["order", "id"]


class AutomationRun(TenantModel):
    """AU-2: every execution logged — rule, record, matched, actions, errors."""

    class Status(models.TextChoices):
        SUCCESS = "success"
        FAILED = "failed"
        SKIPPED = "skipped"  # conditions not met

    rule = models.ForeignKey(AutomationRule, on_delete=models.CASCADE, related_name="runs")
    event_type = models.CharField(max_length=40)
    record_id = models.BigIntegerField(null=True)
    status = models.CharField(max_length=8, choices=Status.choices)
    depth = models.PositiveIntegerField(default=0)
    detail = models.JSONField(default=dict, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [models.Index(fields=["tenant", "rule", "created_at"])]


# ---------------- condition evaluation ----------------

def _record_value(record, field: str):
    if field.startswith("custom."):
        return (record.custom or {}).get(field[7:])
    value = record
    for part in field.split("__"):
        value = getattr(value, part, None)
        if value is None:
            return None
    return value


def _compare(actual, op: str, expected) -> bool:
    try:
        if op == "eq":
            return str(actual) == str(expected)
        if op == "ne":
            return str(actual) != str(expected)
        if op == "contains":
            return expected.lower() in str(actual or "").lower()
        if op == "in":
            return str(actual) in [str(x) for x in expected]
        from decimal import Decimal

        a, e = Decimal(str(actual)), Decimal(str(expected))
        return {"gt": a > e, "gte": a >= e, "lt": a < e, "lte": a <= e}[op]
    except Exception:
        return False


def conditions_met(rule: AutomationRule, record) -> bool:
    cond = rule.conditions or {}
    all_c, any_c = cond.get("all", []), cond.get("any", [])
    ok_all = all(_compare(_record_value(record, c["field"]), c["op"], c["value"])
                 for c in all_c)
    ok_any = (not any_c) or any(
        _compare(_record_value(record, c["field"]), c["op"], c["value"]) for c in any_c)
    return ok_all and ok_any


# ---------------- actions ----------------

def _system_user(tenant_id: int):
    from accounts.models import User

    return (User.objects.filter(tenant_id=tenant_id, role="admin", is_active=True)
            .order_by("id").first())


def _round_robin_owner(record):
    """Least open deals among active members of the record owner's team."""
    from accounts.models import User

    from .models import Deal

    candidates = User.objects.filter(tenant_id=record.tenant_id, is_active=True,
                                     role="member")  # L-6: rotate among reps only
    team_id = getattr(record.owner, "team_id", None) if record.owner_id else None
    if team_id:
        candidates = candidates.filter(team_id=team_id)
    best, best_count = None, None
    for u in candidates.order_by("id"):
        count = Deal.objects.filter(owner=u, status="open").count()
        if best_count is None or count < best_count:
            best, best_count = u, count
    return best


def execute_action(action: dict, record, event_type: str, actor) -> str:
    from . import services
    from .models import Activity, ActivityType, Stage

    kind = action.get("type")
    if kind == "create_activity":
        atype = (ActivityType.objects.filter(name=action.get("type_name", "Task")).first()
                 or ActivityType.objects.first())
        deal = record if event_type.startswith("deal.") else None
        Activity(type=atype, subject=action.get("subject", "Automated task"),
                 due_at=timezone.now() + timedelta(days=int(action.get("due_in_days", 1))),
                 owner=record.owner or actor, deal=deal,
                 lead=record if event_type.startswith("lead.") else None,
                 note=action.get("note", ""), created_by=actor).save()
        return f"activity '{action.get('subject')}' created"
    if kind == "move_stage":
        stage = Stage.objects.filter(pipeline_id=record.pipeline_id,
                                     name=action["stage_name"]).first()
        if stage is None:
            raise ValueError(f"Stage '{action['stage_name']}' not found")
        services.change_stage(record, stage, actor)
        return f"moved to {stage.name}"
    if kind == "update_field":
        field = action["field"]
        if field.startswith("custom."):
            from . import custom_fields

            custom_fields.set_custom_values(record, "deal",
                                            {field[7:]: action["value"]}, actor)
        else:
            if field not in ("title", "value", "probability", "expected_close_date"):
                raise ValueError(f"Field '{field}' not writable by automation")
            setattr(record, field, action["value"])
            record.save(update_fields=[field, "updated_at"])
        return f"{field} updated"
    if kind == "change_owner":
        from accounts.models import User

        if action.get("username") == "round_robin" or action.get("round_robin"):
            new_owner = _round_robin_owner(record)
        else:
            new_owner = User.objects.filter(tenant_id=record.tenant_id,
                                            username=action.get("username")).first()
        if new_owner is None:
            raise ValueError("No owner candidate found")
        record.owner = new_owner
        record.save(update_fields=["owner", "updated_at"])
        services.notify_assignment(record, entity=event_type.split(".")[0],
                                   owner=new_owner, actor=actor)
        return f"owner → {new_owner.username}"
    if kind == "notify":
        target = record.owner or actor
        services.notify(user=target, kind="system",
                        title=action.get("title", f"Automation: {event_type}"),
                        body=action.get("body", ""),
                        link_entity=event_type.split(".")[0], link_id=record.pk,
                        tenant_id=record.tenant_id)
        return f"notified {target.username}"
    raise ValueError(f"Unknown action type '{kind}'")


# ---------------- engine consumer ----------------

def _load_record(event_type: str, payload: dict, tenant_id: int):
    from .leads import Lead
    from .models import Activity, Deal

    model = {"deal": Deal, "lead": Lead, "activity": Activity}[event_type.split(".")[0]]
    return model.objects.filter(pk=payload.get("id")).select_related("owner").first()


def handle_event(event_type: str, payload: dict, tenant_id: int) -> None:
    """Event-bus consumer. Never raises (a broken rule must not break a sale)."""
    from tenants.context import tenant_context

    depth = _depth.get()
    if depth >= MAX_DEPTH:
        logger.warning("Automation chain depth %s reached; stopping (AU-3).", depth)
        return
    with tenant_context(tenant_id):
        rules = list(AutomationRule.objects.filter(trigger=event_type, is_active=True))
        if not rules:
            return
        record = _load_record(event_type, payload, tenant_id)
        if record is None:
            return
        actor = _system_user(tenant_id) or record.owner
        for rule in rules:
            if rule.pipeline_id and getattr(record, "pipeline_id", None) != rule.pipeline_id:
                continue
            run = AutomationRun(rule=rule, event_type=event_type, record_id=record.pk,
                                depth=depth, created_by=actor)
            if not conditions_met(rule, record):
                run.status = AutomationRun.Status.SKIPPED
                run.save()
                continue
            results, errors = [], []
            token = _depth.set(depth + 1)
            try:
                for action in rule.actions:
                    try:
                        results.append(execute_action(action, record, event_type, actor))
                    except Exception as exc:  # isolate per action
                        errors.append(f"{action.get('type')}: {exc}")
                        logger.exception("Automation action failed (rule=%s)", rule.pk)
            finally:
                _depth.reset(token)
            run.status = (AutomationRun.Status.FAILED if errors
                          else AutomationRun.Status.SUCCESS)
            run.detail = {"results": results, "errors": errors}
            run.save()


def register() -> None:
    from . import events

    events.register(handle_event)


AUTOMATION_SETTINGS = getattr(settings, "AUTOMATION", {})  # future: per-tenant rate limits
