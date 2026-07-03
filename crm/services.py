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
    from . import events

    events.emit("deal.created", {"id": deal.pk, "title": deal.title,
                                 "value": str(deal.value), "stage": stage.name,
                                 "owner": deal.owner.username}, deal.tenant_id)
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
    from . import events

    events.emit("deal.stage_changed", {"id": deal.pk, "title": deal.title,
                                       "stage": stage.name}, deal.tenant_id)
    return deal


@transaction.atomic
def mark_won(deal: Deal, user: User) -> Deal:
    if deal.status != Deal.Status.OPEN:
        raise ValidationError("Deal is already closed.")
    deal.status = Deal.Status.WON
    deal.closed_at = timezone.now()
    deal.save(update_fields=["status", "closed_at", "updated_at"])
    from . import events

    events.emit("deal.won", {"id": deal.pk, "title": deal.title,
                             "value": str(deal.value)}, deal.tenant_id)
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
    from . import events

    events.emit("deal.lost", {"id": deal.pk, "title": deal.title,
                              "reason": lost_reason.label}, deal.tenant_id)
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
    from . import events

    events.emit("activity.completed", {"id": activity.pk, "subject": activity.subject,
                                       "outcome": activity.outcome,
                                       "deal_id": activity.deal_id}, activity.tenant_id)
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
        matches = PersonPhone.objects.filter(normalized=normalized)
        person_ids |= set(matches.values_list("person_id", flat=True))
    if email:
        matches = PersonEmail.objects.filter(email__iexact=email)
        person_ids |= set(matches.values_list("person_id", flat=True))
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
    from . import events

    events.emit("lead.converted", {"id": lead.pk, "name": lead.name,
                                   "deal_id": deal.pk}, lead.tenant_id)
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


# ---------------- My Activities (A-2) & Timeline (C-4/D-9) ----------------

def my_activity_buckets(user: User) -> dict:
    """A-2: Overdue / Today / This week / Planned — a rep's homepage."""
    from datetime import timedelta

    now = timezone.localtime()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    week_end = today_start + timedelta(days=7 - today_start.weekday())
    qs = (Activity.objects.filter(owner=user, done=False)
          .select_related("type", "deal").order_by("due_at"))
    return {
        "overdue": list(qs.filter(due_at__lt=today_start)),
        "today": list(qs.filter(due_at__gte=today_start, due_at__lt=today_end)),
        "this_week": list(qs.filter(due_at__gte=today_end, due_at__lt=week_end)),
        "planned": list(qs.filter(due_at__gte=week_end)),
    }


def deal_timeline(deal: Deal) -> list[dict]:
    """C-4: every event in reverse chronological order — the product's memory."""

    events: list[dict] = [{
        "kind": "created", "at": deal.created_at,
        "by": deal.created_by.username if deal.created_by else None,
        "summary": f"Deal created: {deal.title}",
    }]
    for h in deal.stage_history.select_related("from_stage", "to_stage", "changed_by"):
        if h.from_stage_id is None:
            continue  # creation already shown
        events.append({
            "kind": "stage", "at": h.changed_at,
            "by": h.changed_by.username if h.changed_by else None,
            "summary": f"Stage: {h.from_stage.name} → {h.to_stage.name}",
        })
    for a in deal.activities.select_related("type", "owner"):
        events.append({
            "kind": "activity_done" if a.done else "activity_planned",
            "at": a.done_at if a.done else a.due_at,
            "by": a.owner.username, "activity_id": a.id,
            "summary": f"{a.type.name}: {a.subject}"
                       + (f" — {a.outcome}" if a.outcome else ""),
            "done": a.done, "note": a.note,
        })
    for n in deal.notes.select_related("author"):
        events.append({
            "kind": "note", "at": n.created_at,
            "by": n.author.username if n.author else None,
            "summary": n.body,
        })
    if deal.closed_at:
        events.append({
            "kind": deal.status, "at": deal.closed_at, "by": None,
            "summary": ("Won 🎉" if deal.status == Deal.Status.WON
                        else f"Lost — {deal.lost_reason.label if deal.lost_reason else ''}"),
        })
    return sorted(events, key=lambda e: (e["at"] is None, e["at"]), reverse=True)


# ---------------- Global search (S-1) ----------------

def global_search(user: User, q: str, limit: int = 8) -> dict:
    """Navbar search: deals, people, orgs, leads by name/phone/email/title.
    Phone queries match with or without country code."""
    from .leads import Lead
    from .models import Organization, Person

    q = (q or "").strip()
    if len(q) < 2:
        return {"deals": [], "people": [], "organizations": [], "leads": []}
    phone = normalize_phone(q) if any(c.isdigit() for c in q) else ""

    deals = visible_deals(user).filter(title__icontains=q).select_related(
        "organization", "stage")[:limit]

    person_q = (Q(first_name__icontains=q) | Q(last_name__icontains=q)
                | Q(emails__email__icontains=q))
    if phone:
        person_q |= Q(phones__normalized__contains=phone.lstrip("+"))
    people = Person.objects.filter(person_q).distinct()[:limit]

    orgs = Organization.objects.filter(name__icontains=q)[:limit]

    lead_q = (Q(name__icontains=q) | Q(email__icontains=q)
              | Q(organization_name__icontains=q))
    if phone:
        lead_q |= Q(phone_normalized__contains=phone.lstrip("+"))
    leads = visible_owned(Lead.objects.all(), user).filter(lead_q)[:limit]

    return {"deals": list(deals), "people": list(people),
            "organizations": list(orgs), "leads": list(leads)}


# ---------------- Record transfer (U-3) ----------------

@transaction.atomic
def transfer_records(*, from_user: User, to_user: User, actor: User) -> dict:
    """One-click bulk reassignment when a user leaves. Audit-logged by caller's view."""
    from .leads import Lead
    from .models import Organization, Person

    if from_user.tenant_id != to_user.tenant_id:
        raise ValidationError("Users belong to different tenants.")
    if from_user.pk == to_user.pk:
        raise ValidationError("Source and target user are the same.")
    counts = {}
    for model in (Deal, Lead, Person, Organization, Activity):
        counts[model.__name__.lower()] = (
            model.objects.filter(owner=from_user).update(owner=to_user)
        )
    return counts


def person_timeline(person) -> list[dict]:
    """C-4 for people: activities, notes, deal links, reverse chronological."""
    events: list[dict] = [{
        "kind": "created", "at": person.created_at,
        "by": person.created_by.username if person.created_by else None,
        "summary": f"Contact created: {person.name}",
    }]
    for a in person.activities.select_related("type", "owner"):
        events.append({
            "kind": "activity_done" if a.done else "activity_planned",
            "at": a.done_at if a.done else a.due_at, "by": a.owner.username,
            "summary": f"{a.type.name}: {a.subject}" + (f" — {a.outcome}" if a.outcome else ""),
        })
    for n in person.notes.select_related("author"):
        events.append({"kind": "note", "at": n.created_at,
                       "by": n.author.username if n.author else None, "summary": n.body})
    for d in person.deals.select_related("stage"):
        events.append({"kind": f"deal_{d.status}", "at": d.created_at, "by": None,
                       "deal_id": d.id,
                       "summary": f"Deal: {d.title} ({d.status}, {d.stage.name})"})
    return sorted(events, key=lambda e: (e["at"] is None, e["at"]), reverse=True)


# ---------------- Products & line items (PR-1/PR-2) ----------------

def recompute_deal_value(deal: Deal) -> Deal:
    """PR-2: deal value = Σ line subtotals (pre-tax) when value_auto is on."""
    if not deal.value_auto:
        return deal
    total = sum((li.subtotal for li in deal.line_items.all()), Decimal("0"))
    deal.value = total.quantize(Decimal("0.01"))
    deal.save(update_fields=["value", "updated_at"])
    return deal


def stage_nudges(deal: Deal, target_stage: Stage) -> list[str]:
    """CF-2: important fields empty at/after their nudge stage → prompt, don't block."""
    from .custom_fields import CustomFieldDef

    defs = CustomFieldDef.objects.filter(
        entity="deal", nudge_stage_order__isnull=False,
        nudge_stage_order__lte=target_stage.order,
    ).filter(Q(pipeline__isnull=True) | Q(pipeline_id=deal.pipeline_id))
    return [d.name for d in defs if not deal.custom.get(d.key)]


def pipeline_summary(pipeline, user: User) -> dict:
    """R-1 (Phase 1 basic): open value, weighted forecast, rotting, no-next-step, month W/L."""

    deals = annotate_flags(
        visible_deals(user).filter(pipeline=pipeline).select_related("stage"))
    month_start = timezone.localtime().replace(day=1, hour=0, minute=0, second=0,
                                               microsecond=0)
    open_value = Decimal("0")
    weighted = Decimal("0")
    rotting = no_next = open_count = 0
    for d in deals:
        if d.status == Deal.Status.OPEN:
            open_count += 1
            open_value += d.value
            prob = d.probability if d.probability is not None else (d.stage.probability or 0)
            weighted += d.value * Decimal(prob) / Decimal(100)
            if deal_is_rotten(d):
                rotting += 1
            if deal_needs_next_activity(d):
                no_next += 1
    won = deals.filter(status=Deal.Status.WON, closed_at__gte=month_start)
    lost = deals.filter(status=Deal.Status.LOST, closed_at__gte=month_start)
    added = deals.filter(created_at__gte=month_start).count()
    return {
        "open_count": open_count, "open_value": str(open_value),
        "weighted_forecast": str(weighted.quantize(Decimal("0.01"))),
        "rotting": rotting, "needs_next_activity": no_next,
        "added_this_month": added,
        "won_this_month": {"count": won.count(),
                           "value": str(sum((d.value for d in won), Decimal("0")))},
        "lost_this_month": {"count": lost.count(),
                            "value": str(sum((d.value for d in lost), Decimal("0")))},
    }


# ---------------- Notifications (N-1/N-2) ----------------

def notify(*, user: User, kind: str, title: str, body: str = "",
           link_entity: str = "", link_id=None, tenant_id=None) -> None:
    from .models import Notification

    n = Notification(user=user, kind=kind, title=title, body=body,
                     link_entity=link_entity, link_id=link_id)
    if tenant_id is not None:
        n.tenant_id = tenant_id
    n.save()


def notify_assignment(record, *, entity: str, owner: User | None, actor: User) -> None:
    """N-2: record assigned to you — skip self-assignment."""
    if owner is None or owner.pk == actor.pk:
        return
    title_attr = getattr(record, "title", None) or getattr(record, "name", None) or entity
    notify(user=owner, kind="assigned",
           title=f"{entity.title()} assigned to you: {title_attr}",
           body=f"by {actor.username}", link_entity=entity, link_id=record.pk,
           tenant_id=record.tenant_id)


# ---------------- Merge duplicates (C-5) ----------------

def _fill_blanks(primary, duplicate, fields: list[str]) -> list[str]:
    filled = []
    for f in fields:
        if not getattr(primary, f) and getattr(duplicate, f):
            setattr(primary, f, getattr(duplicate, f))
            filled.append(f)
    return filled


@transaction.atomic
def merge_people(primary, duplicate, user: User) -> dict:
    """C-5: field-level fill from duplicate, children reassigned, merge audited
    (audit detail carries everything needed to reverse within retention)."""
    from . import audit
    from .models import DealPerson, Person

    if primary.pk == duplicate.pk:
        raise ValidationError("Cannot merge a person into themselves.")
    if not isinstance(duplicate, Person):  # pragma: no cover - defensive
        raise ValidationError("Invalid duplicate.")
    filled = _fill_blanks(primary, duplicate,
                          ["last_name", "job_title", "organization_id", "owner_id"])
    primary.save()
    moved = {
        "phones": 0, "emails": 0, "activities": 0, "notes": 0, "deal_links": 0,
    }
    existing_phones = set(primary.phones.values_list("normalized", flat=True))
    for ph in duplicate.phones.all():
        if ph.normalized in existing_phones:
            continue
        ph.person = primary
        ph.save(update_fields=["person", "updated_at"])
        moved["phones"] += 1
    existing_emails = {e.lower() for e in primary.emails.values_list("email", flat=True)}
    for em in duplicate.emails.all():
        if em.email.lower() in existing_emails:
            continue
        em.person = primary
        em.save(update_fields=["person", "updated_at"])
        moved["emails"] += 1
    moved["activities"] = duplicate.activities.update(person=primary)
    moved["notes"] = duplicate.notes.update(person=primary)
    already_linked = set(DealPerson.objects.filter(person=primary)
                         .values_list("deal_id", flat=True))
    for link in DealPerson.objects.filter(person=duplicate):
        if link.deal_id in already_linked:
            link.is_deleted = True
            link.save(update_fields=["is_deleted", "updated_at"])
        else:
            link.person = primary
            link.save(update_fields=["person", "updated_at"])
            moved["deal_links"] += 1
    duplicate.is_deleted = True
    duplicate.save(update_fields=["is_deleted", "updated_at"])
    audit.log(actor=user, action="update", model_name="person", object_id=primary.pk,
              detail={"merged_from": duplicate.pk, "filled": filled, "moved": moved},
              tenant_id=primary.tenant_id)
    return {"filled": filled, "moved": moved}


@transaction.atomic
def merge_organizations(primary, duplicate, user: User) -> dict:
    from . import audit

    if primary.pk == duplicate.pk:
        raise ValidationError("Cannot merge an organization into itself.")
    filled = _fill_blanks(primary, duplicate, ["industry", "website", "gstin", "owner_id"])
    primary.save()
    moved = {
        "people": duplicate.people.update(organization=primary),
        "deals": duplicate.deals.update(organization=primary),
    }
    duplicate.is_deleted = True
    duplicate.save(update_fields=["is_deleted", "updated_at"])
    audit.log(actor=user, action="update", model_name="organization",
              object_id=primary.pk,
              detail={"merged_from": duplicate.pk, "filled": filled, "moved": moved},
              tenant_id=primary.tenant_id)
    return {"filled": filled, "moved": moved}
