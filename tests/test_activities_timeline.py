"""A-2 my-activities buckets, C-4/D-9 timeline, notes."""
from datetime import timedelta

import pytest
from django.utils import timezone

from crm import services
from crm.models import Activity, Note
from tenants.context import tenant_context


@pytest.fixture
def ctx(t1):
    with tenant_context(t1["tenant"].id):
        yield t1


def _act(ctx, due, owner=None, **kw):
    a = Activity(type=ctx["activity_type"], subject=kw.pop("subject", "call"),
                 due_at=due, owner=owner or ctx["users"]["rep1"], **kw)
    a.save()
    return a


def test_my_activity_buckets(ctx):
    now = timezone.localtime()
    _act(ctx, now - timedelta(days=2), subject="old")           # overdue
    _act(ctx, now, subject="today")                             # today
    done = _act(ctx, now, subject="done already")
    services.complete_activity(done, ctx["users"]["rep1"])      # excluded (done)
    _act(ctx, now + timedelta(days=30), subject="future")       # planned
    _act(ctx, now, owner=ctx["users"]["rep2"], subject="not mine")  # excluded (other owner)
    b = services.my_activity_buckets(ctx["users"]["rep1"])
    assert [a.subject for a in b["overdue"]] == ["old"]
    assert [a.subject for a in b["today"]] == ["today"]
    assert [a.subject for a in b["planned"]] == ["future"]


def test_my_endpoint_shape(t1, api):
    with tenant_context(t1["tenant"].id):
        _act({"activity_type": t1["activity_type"], "users": t1["users"]},
             timezone.localtime() - timedelta(days=1))
    r = api(t1["users"]["rep1"]).get("/api/v1/activities/my/")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"overdue", "today", "this_week", "planned"}
    assert len(body["overdue"]) == 1 and body["overdue"][0]["type_name"] == "Call"


def test_timeline_orders_and_merges_events(ctx):
    user = ctx["users"]["rep1"]
    deal = services.create_deal(user=user, title="TL", pipeline=ctx["pipeline"])
    services.change_stage(deal, ctx["stages"][1], user)
    a = _act(ctx, timezone.now(), deal=deal, subject="intro call")
    services.complete_activity(a, user, outcome="connected")
    Note(body="Client wants Goa", deal=deal, author=user).save()
    services.mark_won(deal, user)
    events = services.deal_timeline(deal)
    kinds = [e["kind"] for e in events]
    assert kinds[0] == "won" and kinds[-1] == "created"
    assert "stage" in kinds and "activity_done" in kinds and "note" in kinds
    stage_ev = next(e for e in events if e["kind"] == "stage")
    assert "Qualified → Proposal" in stage_ev["summary"]


def test_timeline_and_notes_api(t1, api):
    with tenant_context(t1["tenant"].id):
        deal = services.create_deal(user=t1["users"]["rep1"], title="API TL",
                                    pipeline=t1["pipeline"])
    c = api(t1["users"]["rep1"])
    r = c.post(f"/api/v1/deals/{deal.id}/add_note/", {"body": "note via api"})
    assert r.status_code == 201 and r.json()["author_name"] == "alpha_rep1"
    assert c.post(f"/api/v1/deals/{deal.id}/add_note/", {"body": "  "}).status_code == 400
    r = c.get(f"/api/v1/deals/{deal.id}/timeline/")
    assert r.status_code == 200
    kinds = [e["kind"] for e in r.json()["events"]]
    assert kinds == ["note", "created"]


def test_activity_types_endpoint(t1, api):
    r = api(t1["users"]["rep1"]).get("/api/v1/activity-types/")
    assert r.status_code == 200 and r.json()[0]["name"] == "Call"
