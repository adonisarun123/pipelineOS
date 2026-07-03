"""R-2..R-5 reports."""
from datetime import timedelta

import pytest
from django.utils import timezone

from crm import reports, services
from crm.leads import Lead, LeadSource
from crm.models import Activity
from tenants.context import tenant_context


@pytest.fixture
def ctx(t1):
    with tenant_context(t1["tenant"].id):
        yield t1


def test_funnel_counts_conversion_and_median_days(ctx):
    user = ctx["users"]["manager"]
    rep = ctx["users"]["rep1"]
    s = ctx["stages"]
    # 3 deals enter stage0; 2 progress to stage1; 1 to stage2
    d1 = services.create_deal(user=rep, title="F1", pipeline=ctx["pipeline"])
    d2 = services.create_deal(user=rep, title="F2", pipeline=ctx["pipeline"])
    services.create_deal(user=rep, title="F3", pipeline=ctx["pipeline"])
    services.change_stage(d1, s[1], rep)
    services.change_stage(d2, s[1], rep)
    services.change_stage(d1, s[2], rep)
    rows = reports.funnel(ctx["pipeline"], user)
    assert [r["entered"] for r in rows] == [3, 2, 1]
    assert rows[0]["conversion_pct"] == 66.7
    assert rows[1]["conversion_pct"] == 50.0
    assert rows[2]["conversion_pct"] is None  # last stage
    assert rows[0]["median_days"] is not None  # left stage0 twice


def test_activity_report_connect_rates(ctx):
    rep = ctx["users"]["rep1"]
    for outcome in ("connected", "connected", "no_answer"):
        a = Activity(type=ctx["activity_type"], subject="c", due_at=timezone.now(),
                     owner=rep)
        a.save()
        services.complete_activity(a, rep, outcome=outcome)
    rows = reports.activity_report(ctx["users"]["manager"])
    row = next(r for r in rows if r["rep"] == "alpha_rep1")
    assert row["calls"] == 3 and row["connect_rate_pct"] == 66.7


def test_won_lost_pareto_and_visibility(ctx, t2):
    rep = ctx["users"]["rep1"]
    for i in range(2):
        d = services.create_deal(user=rep, title=f"W{i}", pipeline=ctx["pipeline"],
                                 value=1000)
        services.mark_won(d, rep)
    lost = services.create_deal(user=rep, title="L", pipeline=ctx["pipeline"])
    services.mark_lost(lost, rep, ctx["lost_reason"])
    result = reports.won_lost(ctx["users"]["manager"])
    assert result["by_owner"][0] == {"owner": "alpha_rep1", "won": 2, "lost": 1,
                                     "won_value": "2000.00"}
    assert result["lost_reasons"] == [{"reason": "Budget", "count": 1}]
    # member in another tenant sees nothing of t1
    with tenant_context(t2["tenant"].id):
        assert reports.won_lost(t2["users"]["admin"])["by_owner"] == []


def test_source_roi_lineage(ctx):
    rep = ctx["users"]["rep1"]
    src = LeadSource(name="Chatbot")
    src.save()
    for i in range(3):
        lead = Lead(name=f"L{i}", source=src, owner=rep)
        lead.save()
    lead = Lead.objects.filter(name="L0").get()
    services.convert_lead(lead=lead, user=rep, pipeline=ctx["pipeline"],
                          deal_title="From chatbot", value=7000)
    services.mark_won(lead.converted_deal, rep)
    rows = reports.source_roi(ctx["users"]["manager"])
    row = next(r for r in rows if r["source"] == "Chatbot")
    assert row == {"source": "Chatbot", "leads": 3, "qualified": 1, "won": 1,
                   "won_value": "7000.00", "lead_to_win_pct": 33.3}


def test_reports_api_endpoints(t1, api):
    with tenant_context(t1["tenant"].id):
        d = services.create_deal(user=t1["users"]["rep1"], title="R",
                                 pipeline=t1["pipeline"], value=100)
        services.mark_won(d, t1["users"]["rep1"])
    c = api(t1["users"]["manager"])
    assert c.get(f"/api/v1/reports/funnel/?pipeline={t1['pipeline'].id}").status_code == 200
    assert c.get("/api/v1/reports/activity/").status_code == 200
    wl = c.get("/api/v1/reports/won-lost/").json()
    assert wl["by_owner"][0]["won"] == 1
    assert c.get("/api/v1/reports/sources/").status_code == 200
    assert c.get("/api/v1/reports/nope/").status_code == 404
    # member sees only own numbers
    other = api(t1["users"]["rep2"]).get("/api/v1/reports/won-lost/").json()
    assert other["by_owner"] == []


def test_funnel_respects_days_window(ctx):
    rep = ctx["users"]["rep1"]
    deal = services.create_deal(user=rep, title="Old", pipeline=ctx["pipeline"])
    from crm.models import StageHistory

    StageHistory.unscoped.filter(deal=deal).update(
        changed_at=timezone.now() - timedelta(days=200))
    rows = reports.funnel(ctx["pipeline"], ctx["users"]["manager"], days=30)
    assert rows[0]["entered"] == 0  # outside window
