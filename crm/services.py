"""Business logic (service layer, spec §7): API, automation, imports share this path."""
import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Count, Max, Q, QuerySet
from django.utils import timezone

from accounts.models import User

from .models import Activity, Deal, LostReason, Stage, StageHistory


def normalize_phone(raw: str, default_country: str = "91") -> str:
    """E.164-ish normalization (C-1/L-5). '98765 43210' == '+919876543210'."""
    digits = re.sub(r"\D", "", raw or "")
    if not digits:
        return ""
    if raw.strip().startswith("+"):
        return f"+{digits}"
    if len(digits) == 10:
        return f"+{default_country}{digits}"
    if len(digits) == 12 and digits.startswith(default_country):
        return f"+{digits}"
    if digits.startswith("0") and len(digits) == 11:
        return f"+{default_country}{digits[1:]}"
    return f"+{digits}"


def visible_deals(user: User) -> QuerySet[Deal]:
    """U-1/U-2 visibility: own / team / all."""
    qs = Deal.objects.all()
    if user.is_admin_role:
        return qs
    if user.is_manager_role and user.team_id:
        return qs.filter(Q(owner=user) | Q(owner__team_id=user.team_id))
    return qs.filter(owner=user)


def annotate_flags(qs: QuerySet[Deal]) -> QuerySet[Deal]:
    """Attach data needed for is_rotten / needs_next_activity without N+1."""
    return qs.annotate(
        last_done_at=Max("activities__done_at", filter=Q(activities__done=True)),
        planned_count=Count("activities", filter=Q(activities__done=False)),
    )


def deal_is_rotten(deal: Deal) -> bool:
    """D-4: open deal with no completed activity within stage.rot_days."""
    if deal.status != Deal.Status.OPEN or not deal.stage.rot_days:
        return False
    last_done = getattr(deal, "last_done_at", None)
    reference = max(filter(None, [deal.stage_entered_at, last_done]))
    return (timezone.now() - reference).days >= deal.stage.rot_days


def deal_needs_next_activity(deal: Deal) -> bool:
    """D-5: open deal with no planned activity (prompt, don't block)."""
    if deal.status != Deal.Status.OPEN:
        return False
    planned = getattr(deal, "planned_count", None)
    if planned is None:
        planned = deal.activities.filter(done=False).count()
    return planned == 0


@transaction.atomic
def create_deal(*, user: User, title: str, pipeline, stage: Stage | None = None,
                value: Decimal | int = 0, organization=None, owner: User | None = None,
                expected_close_date=None) -> Deal:
    stage = stage or pipeline.stages.first()
    if stage is None:
        raise ValidationError("Pipeline has no stages.")
    if stage.pipeline_id != pipeline.id:
        raise ValidationError("Stage does not belong to pipeline.")
    deal = Deal(
        title=title, pipeline=pipeline, stage=stage, value=value,
        organization=organization, owner=owner or user, created_by=user,
        expected_close_date=expected_close_date,
    )
    deal.save()
    StageHistory(deal=deal, from_stage=None, to_stage=stage, changed_by=user).save()
    return deal


@transaction.atomic
def change_stage(deal: Deal, stage: Stage, user: User) -> Deal:
    """D-5/D-6: validated move + append-only history + rot clock reset."""
    if stage.pipeline_id != deal.pipeline_id:
        raise ValidationError("Stage does not belong to this deal's pipeline.")
    if deal.status != Deal.Status.OPEN:
        raise ValidationError("Cannot move a closed deal.")
    if stage.id == deal.stage_id:
        return deal
    StageHistory(deal=deal, from_stage=deal.stage, to_stage=stage, changed_by=user).save()
    deal.stage = stage
    deal.stage_entered_at = timezone.now()
    deal.save(update_fields=["stage", "stage_entered_at", "updated_at"])
    return deal


@transaction.atomic
def mark_won(deal: Deal, user: User) -> Deal:
    if deal.status != Deal.Status.OPEN:
        raise ValidationError("Deal is already closed.")
    deal.status = Deal.Status.WON
    deal.closed_at = timezone.now()
    deal.save(update_fields=["status", "closed_at", "updated_at"])
    return deal


@transaction.atomic
def mark_lost(deal: Deal, user: User, lost_reason: LostReason | None) -> Deal:
    """D-2: lost reason is mandatory on loss."""
    if deal.status != Deal.Status.OPEN:
        raise ValidationError("Deal is already closed.")
    if lost_reason is None:
        raise ValidationError("A lost reason is required to mark a deal lost.")
    deal.status = Deal.Status.LOST
    deal.lost_reason = lost_reason
    deal.closed_at = timezone.now()
    deal.save(update_fields=["status", "lost_reason", "closed_at", "updated_at"])
    return deal


@transaction.atomic
def complete_activity(activity: Activity, user: User, outcome: str = "") -> dict:
    """A-4: quick-complete; response tells UI to prompt for the next activity (D-5)."""
    activity.done = True
    activity.done_at = timezone.now()
    if outcome:
        activity.outcome = outcome
    activity.save(update_fields=["done", "done_at", "outcome", "updated_at"])
    prompt_next = bool(activity.deal_id) and deal_needs_next_activity(activity.deal)
    return {"activity": activity, "prompt_next": prompt_next}
