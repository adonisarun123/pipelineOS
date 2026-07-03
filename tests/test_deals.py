"""S4/S5/S6: deal lifecycle, history, rotting, next-activity (D-2..D-6, A-4)."""
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from crm import services
from crm.models import Activity, Deal
from tenants.context import tenant_context


@pytest.fixture
def ctx(t1):
    with tenant_context(t1["tenant"].id):
        yield t1


def _deal(ctx, **kw):
    return services.create_deal(user=ctx["users"]["rep1"], title="D", pipeline=ctx["pipeline"], **kw)


def test_create_deal_defaults_first_stage_and_logs_history(ctx):
    deal = _deal(ctx)
    assert deal.stage == ctx["stages"][0]
    h = deal.stage_history.get()
    assert h.from_stage is None and h.to_stage == ctx["stages"][0]


def test_change_stage_appends_history_and_resets_rot_clock(ctx):
    deal = _deal(ctx)
    before = deal.stage_entered_at
    services.change_stage(deal, ctx["stages"][1], ctx["users"]["rep1"])
    assert deal.stage == ctx["stages"][1]
    assert deal.stage_entered_at > before
    moves = list(deal.stage_history.order_by("id"))
    assert [m.to_stage_id for m in moves] == [ctx["stages"][0].id, ctx["stages"][1].id]


def test_change_stage_rejects_foreign_pipeline_stage(ctx, t2):
    deal = _deal(ctx)
    with pytest.raises(ValidationError):
        services.change_stage(deal, t2["stages"][0], ctx["users"]["rep1"])


def test_stage_history_is_append_only(ctx):
    deal = _deal(ctx)
    h = deal.stage_history.get()
    h.changed_by = None
    with pytest.raises(ValueError):
        h.save()


def test_lost_requires_reason(ctx):
    deal = _deal(ctx)
    with pytest.raises(ValidationError):
        services.mark_lost(deal, ctx["users"]["rep1"], None)
    services.mark_lost(deal, ctx["users"]["rep1"], ctx["lost_reason"])
    assert deal.status == Deal.Status.LOST and deal.closed_at is not None


def test_won_and_closed_deals_immutable(ctx):
    deal = _deal(ctx)
    services.mark_won(deal, ctx["users"]["rep1"])
    with pytest.raises(ValidationError):
        services.mark_won(deal, ctx["users"]["rep1"])
    with pytest.raises(ValidationError):
        services.change_stage(deal, ctx["stages"][1], ctx["users"]["rep1"])


def test_rotting(ctx):
    deal = _deal(ctx)  # stage rot_days=7
    assert services.deal_is_rotten(deal) is False
    deal.stage_entered_at = timezone.now() - timedelta(days=8)
    deal.save(update_fields=["stage_entered_at"])
    assert services.deal_is_rotten(deal) is True
    # a recent completed activity un-rots it
    a = Activity(type=ctx["activity_type"], subject="call", due_at=timezone.now(),
                 owner=ctx["users"]["rep1"], deal=deal)
    a.save()
    services.complete_activity(a, ctx["users"]["rep1"], outcome="connected")
    deal = services.annotate_flags(Deal.objects.filter(pk=deal.pk)).get()
    assert services.deal_is_rotten(deal) is False


def test_needs_next_activity_and_prompt(ctx):
    deal = _deal(ctx)
    assert services.deal_needs_next_activity(deal) is True
    a = Activity(type=ctx["activity_type"], subject="call", due_at=timezone.now(),
                 owner=ctx["users"]["rep1"], deal=deal)
    a.save()
    assert services.deal_needs_next_activity(deal) is False
    result = services.complete_activity(a, ctx["users"]["rep1"])
    assert result["prompt_next"] is True  # D-5: prompt after completing last activity


def test_phone_normalization():
    f = services.normalize_phone
    assert f("98765 43210") == "+919876543210"
    assert f("+91 98765-43210") == "+919876543210"
    assert f("09876543210") == "+919876543210"
    assert f("919876543210") == "+919876543210"
    assert f("") == ""
    assert f("+1 (415) 555-0100") == "+14155550100"
