"""Reporting (R-2..R-5). All queries visibility-scoped through visible_deals /
visible_owned — a member's reports show their own numbers, a manager's their
team's. Funnels derive from append-only StageHistory, never current state (§6).
"""
import statistics
from datetime import timedelta
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from accounts.models import User

from .leads import Lead
from .models import Activity, Deal, StageHistory
from .services import visible_deals, visible_owned


def _since(days: int | None):
    return timezone.now() - timedelta(days=days or 90)


def funnel(pipeline, user: User, days: int | None = None) -> list[dict]:
    """R-2: entered-count, stage→next conversion %, median days-in-stage."""
    since = _since(days)
    deal_ids = set(visible_deals(user).filter(pipeline=pipeline)
                   .values_list("id", flat=True))
    history = list(StageHistory.objects.filter(
        deal_id__in=deal_ids, changed_at__gte=since,
    ).select_related("to_stage", "from_stage").order_by("deal_id", "changed_at"))

    stages = list(pipeline.stages.all())
    entered: dict[int, set] = {s.id: set() for s in stages}
    durations: dict[int, list[float]] = {s.id: [] for s in stages}
    entered_at: dict[tuple, object] = {}
    for h in history:
        if h.to_stage_id in entered:
            entered[h.to_stage_id].add(h.deal_id)
            entered_at[(h.deal_id, h.to_stage_id)] = h.changed_at
        if h.from_stage_id in entered:
            start = entered_at.get((h.deal_id, h.from_stage_id))
            if start:
                durations[h.from_stage_id].append(
                    (h.changed_at - start).total_seconds() / 86400)

    rows = []
    for i, stage in enumerate(stages):
        count = len(entered[stage.id])
        nxt = len(entered[stages[i + 1].id]) if i + 1 < len(stages) else None
        rows.append({
            "stage": stage.name,
            "stage_id": stage.id,
            "entered": count,
            "conversion_pct": (round(100 * nxt / count, 1)
                               if nxt is not None and count else None),
            "median_days": (round(statistics.median(durations[stage.id]), 1)
                            if durations[stage.id] else None),
        })
    return rows


def activity_report(user: User, days: int | None = None) -> list[dict]:
    """R-3: completed activities per rep + call outcome breakdown (connect rates)."""
    since = _since(days)
    qs = Activity.objects.filter(done=True, done_at__gte=since).select_related(
        "owner", "type")
    if not user.is_admin_role:
        if user.is_manager_role and user.team_id:
            qs = qs.filter(Q(owner=user) | Q(owner__team_id=user.team_id))
        else:
            qs = qs.filter(owner=user)
    per_rep: dict[str, dict] = {}
    for a in qs:
        row = per_rep.setdefault(a.owner.username, {
            "rep": a.owner.username, "total": 0, "by_type": {}, "calls": 0,
            "connected": 0})
        row["total"] += 1
        row["by_type"][a.type.name] = row["by_type"].get(a.type.name, 0) + 1
        if a.type.name == "Call":
            row["calls"] += 1
            if a.outcome == "connected":
                row["connected"] += 1
    for row in per_rep.values():
        row["connect_rate_pct"] = (round(100 * row["connected"] / row["calls"], 1)
                                   if row["calls"] else None)
    return sorted(per_rep.values(), key=lambda r: -r["total"])


def won_lost(user: User, days: int | None = None) -> dict:
    """R-4: revenue by month + by owner; lost reasons Pareto."""
    since = _since(days)
    deals = (visible_deals(user).filter(closed_at__gte=since)
             .exclude(status=Deal.Status.OPEN)
             .select_related("owner", "lost_reason"))
    by_month: dict[str, dict] = {}
    by_owner: dict[str, dict] = {}
    lost_reasons: dict[str, int] = {}
    for d in deals:
        month = d.closed_at.strftime("%Y-%m")
        m = by_month.setdefault(month, {"month": month, "won": 0, "lost": 0,
                                        "won_value": Decimal("0")})
        o = by_owner.setdefault(d.owner.username, {"owner": d.owner.username,
                                                   "won": 0, "lost": 0,
                                                   "won_value": Decimal("0")})
        if d.status == Deal.Status.WON:
            m["won"] += 1
            o["won"] += 1
            m["won_value"] += d.value
            o["won_value"] += d.value
        else:
            m["lost"] += 1
            o["lost"] += 1
            if d.lost_reason:
                lost_reasons[d.lost_reason.label] = \
                    lost_reasons.get(d.lost_reason.label, 0) + 1
    for row in list(by_month.values()) + list(by_owner.values()):
        row["won_value"] = str(row["won_value"])
    pareto = sorted(({"reason": k, "count": v} for k, v in lost_reasons.items()),
                    key=lambda r: -r["count"])
    return {"by_month": sorted(by_month.values(), key=lambda r: r["month"]),
            "by_owner": sorted(by_owner.values(), key=lambda r: -r["won"]),
            "lost_reasons": pareto}


def source_roi(user: User, days: int | None = None) -> list[dict]:
    """R-5: leads → qualified → won + revenue, by source (UTM lineage via L-3)."""
    since = _since(days)
    leads = (visible_owned(Lead.objects.all(), user)
             .filter(created_at__gte=since).select_related("source", "converted_deal"))
    rows: dict[str, dict] = {}
    for lead in leads:
        key = lead.source.name if lead.source else "(none)"
        row = rows.setdefault(key, {"source": key, "leads": 0, "qualified": 0,
                                    "won": 0, "won_value": Decimal("0")})
        row["leads"] += 1
        if lead.status == "qualified":
            row["qualified"] += 1
            deal = lead.converted_deal
            if deal and deal.status == Deal.Status.WON:
                row["won"] += 1
                row["won_value"] += deal.value
    out = []
    for row in rows.values():
        row["won_value"] = str(row["won_value"])
        row["lead_to_win_pct"] = (round(100 * row["won"] / row["leads"], 1)
                                  if row["leads"] else 0)
        out.append(row)
    return sorted(out, key=lambda r: -r["leads"])
