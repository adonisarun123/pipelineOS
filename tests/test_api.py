"""S2/S3/S5: API contract — auth, roles, visibility, kanban (spec 3.3 contract tests)."""
import pytest
from rest_framework.test import APIClient

from crm import services
from tenants.context import tenant_context


@pytest.fixture
def deals(t1):
    with tenant_context(t1["tenant"].id):
        d1 = services.create_deal(user=t1["users"]["rep1"], title="Rep1 deal",
                                  pipeline=t1["pipeline"], value=1000)
        d2 = services.create_deal(user=t1["users"]["rep2"], title="Rep2 deal",
                                  pipeline=t1["pipeline"], value=2000,
                                  stage=t1["stages"][1])
    return {"d1": d1, "d2": d2}


def test_unauthenticated_401(db):
    assert APIClient().get("/api/v1/deals/").status_code == 401


def test_login_returns_token_and_role(t1):
    r = APIClient().post("/api/v1/auth/login/",
                         {"username": "alpha_rep1", "password": "x-test-pass-123"})
    assert r.status_code == 200
    assert r.json()["role"] == "member" and r.json()["token"]


def test_readonly_role_cannot_write(t1, api, deals):
    c = api(t1["users"]["ro"])
    assert c.get("/api/v1/deals/").status_code == 200
    r = c.post("/api/v1/deals/", {"title": "x", "pipeline": t1["pipeline"].id})
    assert r.status_code == 403


def test_member_sees_own_only(t1, api, deals):
    titles = {d["title"] for d in api(t1["users"]["rep1"]).get("/api/v1/deals/").json()["results"]}
    assert titles == {"Rep1 deal"}


def test_manager_sees_team(t1, api, deals):
    titles = {d["title"] for d in api(t1["users"]["manager"]).get("/api/v1/deals/").json()["results"]}
    assert titles == {"Rep1 deal", "Rep2 deal"}


def test_create_deal_via_api(t1, api):
    r = api(t1["users"]["rep1"]).post("/api/v1/deals/", {
        "title": "API deal", "pipeline": t1["pipeline"].id, "value": "50000.00",
    })
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["stage"] == t1["stages"][0].id
    assert body["needs_next_activity"] is True


def test_create_deal_rejects_foreign_stage(t1, t2, api):
    r = api(t1["users"]["rep1"]).post("/api/v1/deals/", {
        "title": "x", "pipeline": t1["pipeline"].id, "stage": t2["stages"][0].id,
    })
    assert r.status_code == 400


def test_move_endpoint(t1, api, deals):
    c = api(t1["users"]["rep1"])
    r = c.post(f"/api/v1/deals/{deals['d1'].id}/move/", {"stage_id": t1["stages"][1].id})
    assert r.status_code == 200 and r.json()["stage"] == t1["stages"][1].id
    # invalid stage id -> 404
    assert c.post(f"/api/v1/deals/{deals['d1'].id}/move/", {"stage_id": 999999}).status_code == 404


def test_lost_without_reason_400(t1, api, deals):
    c = api(t1["users"]["rep1"])
    assert c.post(f"/api/v1/deals/{deals['d1'].id}/lost/", {}).status_code == 400
    r = c.post(f"/api/v1/deals/{deals['d1'].id}/lost/",
               {"lost_reason_id": t1["lost_reason"].id})
    assert r.status_code == 200 and r.json()["status"] == "lost"


def test_kanban_shape(t1, api, deals):
    r = api(t1["users"]["manager"]).get(f"/api/v1/pipelines/{t1['pipeline'].id}/kanban/")
    assert r.status_code == 200
    cols = r.json()["columns"]
    assert [c["stage"]["name"] for c in cols] == ["Qualified", "Proposal", "Won-ready"]
    assert cols[0]["count"] == 1 and cols[0]["total_value"] == "1000.00"
    card = cols[0]["deals"][0]
    assert {"title", "is_rotten", "needs_next_activity", "owner_name"} <= set(card)


def test_activity_complete_prompts_next(t1, api, deals):
    c = api(t1["users"]["rep1"])
    r = c.post("/api/v1/activities/", {
        "type": t1["activity_type"].id, "subject": "Call client",
        "due_at": "2026-07-04T10:00:00+05:30", "deal": deals["d1"].id,
    })
    assert r.status_code == 201, r.content
    aid = r.json()["id"]
    r = c.post(f"/api/v1/activities/{aid}/complete/", {"outcome": "connected"})
    assert r.status_code == 200
    assert r.json()["prompt_next"] is True
    assert r.json()["activity"]["outcome"] == "connected"


def test_deactivation_kills_token(t1, api, deals):
    user = t1["users"]["rep1"]
    c = api(user)
    assert c.get("/api/v1/deals/").status_code == 200
    user.deactivate()
    assert c.get("/api/v1/deals/").status_code == 401
