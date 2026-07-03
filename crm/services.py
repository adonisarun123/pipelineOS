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


# ---------------- Leads (L-1..L-6) ----------------

def visible_owned(qs: QuerySet, user: User) -> QuerySet:
    """Generic own/team/all visibility (U-2) for models with an `owner` FK."""
    if user.is_admin_role:
        return qs
    if user.is_manager_role and user.team_id:
        return qs.filter(Q(owner=user) | Q(owner__team_id=user.team_id))
    return qs.filter(owner=user)


def find_lead_duplicates(*, phone: str = "", email: str = "", org_name: str = ""):
    """L-5: fuzzy dupe check on normalized phone, email, org name before save."""
    from .leads import Lead
    from .models import Person, PersonEmail, PersonPhone

    dupes: dict[str, list] = {"leads": [], "people": []}
    normalized = normalize_phone(phone) if phone else ""
    lead_q = Q()
    if normalized:
        lead_q |= Q(phone_normalized=normalized)
    if email:
        lead_q |= Q(email__iexact=email)
    if org_name:
        lead_q |= Q(organization_name__icontains=org_name)
    if lead_q:
        dupes["leads"] = list(Lead.objects.filter(lead_q, status__in=["new", "attempted", "contacted"]))
    person_ids = set()
    if normalized:
        person_ids |= set(PersonPhone.objects.filter(normalized=normalized).values_list("person_id", flat=True))
    if email:
        person_ids |= set(PersonEmail.objects.filter(email__iexact=email).values_list("person_id", flat=True))
    if person_ids:
        dupes["people"] = list(Person.objects.filter(id__in=person_ids))
    return dupes


@transaction.atomic
def convert_lead(*, lead, user: User, pipeline, stage=None, deal_title: str = "",
                 value: Decimal | int = 0):
    """L-3: one-click convert. Creates/links Person + Organization + Deal,
    carries activities across, keeps lineage for source→revenue attribution."""
    from django.utils import timezone as tz

    from .leads import Lead
    from .models import Organization, Person, PersonEmail, PersonPhone

    if lead.status in (Lead.Status.QUALIFIED, Lead.Status.DISQUALIFIED):
        raise ValidationError("Lead is already closed.")

    org = None
    if lead.organization_name:
        org = Organization.objects.filter(name__iexact=lead.organization_name).first()
        if org is None:
            org = Organization(name=lead.organization_name, owner=lead.owner or user, created_by=user)
            org.save()

    parts = lead.name.split(" ", 1)
    person = Person(first_name=parts[0], last_name=parts[1] if len(parts) > 1 else "",
                    organization=org, owner=lead.owner or user, created_by=user)
    person.save()
    if lead.phone_raw:
        PersonPhone(person=person, raw=lead.phone_raw,
                    normalized=lead.phone_normalized or normalize_phone(lead.phone_raw)).save()
    if lead.email:
        PersonEmail(person=person, email=lead.email).save()

    deal = create_deal(
        user=user, title=deal_title or f"{lead.organization_name or lead.name} — new deal",
        pipeline=pipeline, stage=stage, value=value, organization=org,
        owner=lead.owner or user,
    )
    deal.people.add(person, through_defaults={"is_primary": True, "tenant_id": lead.tenant_id,
                                              "created_by": user})
    # Carry activities and notes across (L-3)
    lead.activities.update(deal=deal, person=person)
    if lead.note:
        deal_note = f"[From lead] {lead.note}"
        Activity(type=_note_activity_type(lead.tenant_id), subject=deal_note[:255],
                 due_at=tz.now(), owner=lead.owner or user, deal=deal, person=person,
                 note=lead.note, done=True, done_at=tz.now(), created_by=user).save()

    lead.status = Lead.Status.QUALIFIED
    lead.converted_person = person
    lead.converted_organization = org
    lead.converted_deal = deal
    lead.converted_at = tz.now()
    lead.save(update_fields=["status", "converted_person", "converted_organization",
                             "converted_deal", "converted_at", "updated_at"])
    return lead


def _note_activity_type(tenant_id: int):
    from .models import ActivityType

    t = ActivityType.objects.filter(name="Task").first() or ActivityType.objects.first()
    if t is None:
        t = ActivityType(name="Task")
        t.save()
    return t


@transaction.atomic
def disqualify_lead(lead, user: User, reason) -> None:
    """L-4: reason mandatory; feeds reports."""
    from .leads import Lead

    if lead.status in (Lead.Status.QUALIFIED, Lead.Status.DISQUALIFIED):
        raise ValidationError("Lead is already closed.")
    if reason is None:
        raise ValidationError("A disqualification reason is required.")
    lead.status = Lead.Status.DISQUALIFIED
    lead.disqualify_reason = reason
    lead.save(update_fields=["status", "disqualify_reason", "updated_at"])
