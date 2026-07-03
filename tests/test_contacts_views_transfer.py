"""Person timeline (C-4), saved views (S-3), record transfer + deactivation (U-3)."""
import pytest
from django.core.exceptions import ValidationError

from crm import services
from crm.audit import AuditLog
from crm.models import Note, Person, SavedView
from tenants.context import tenant_context


@pytest.fixture
def ctx(t1):
    with tenant_context(t1["tenant"].id):
        yield t1


def test_person_create_with_phone_and_timeline(t1, api):
    c = api(t1["users"]["rep1"])
    r = c.post("/api/v1/people/", {"first_name": "Asha", "last_name": "Nair",
                                   "phone": "98123 45678", "email": "asha@x.in"})
    assert r.status_code == 201
    pid = r.json()["id"]
    detail = c.get(f"/api/v1/people/{pid}/").json()
    assert detail["phones"][0]["normalized"] == "+919812345678"
    assert detail["emails"][0]["email"] == "asha@x.in"
    r = c.get(f"/api/v1/people/{pid}/timeline/")
    assert r.status_code == 200
    assert [e["kind"] for e in r.json()["events"]] == ["created"]


def test_person_timeline_merges_deal_note_activity(ctx):
    user = ctx["users"]["rep1"]
    person = Person(first_name="Vik", owner=user)
    person.save()
    deal = services.create_deal(user=user, title="Vik deal", pipeline=ctx["pipeline"])
    deal.people.add(person, through_defaults={"is_primary": True,
                                              "tenant_id": ctx["tenant"].id})
    Note(body="met at expo", person=person, author=user).save()
    events = services.person_timeline(person)
    kinds = {e["kind"] for e in events}
    assert {"created", "note", "deal_open"} <= kinds


def test_person_search_param(t1, api):
    c = api(t1["users"]["rep1"])
    c.post("/api/v1/people/", {"first_name": "Meena", "last_name": "Iyer"})
    c.post("/api/v1/people/", {"first_name": "Rahul"})
    names = [p["first_name"] for p in c.get("/api/v1/people/?q=meen").json()["results"]]
    assert names == ["Meena"]


def test_saved_views_private_vs_shared(t1, api):
    rep1, rep2 = api(t1["users"]["rep1"]), api(t1["users"]["rep2"])
    rep1.post("/api/v1/saved-views/", {"name": "My hot leads", "entity": "lead",
                                       "params": {"status": "new"}}, format="json")
    rep1.post("/api/v1/saved-views/", {"name": "Team board", "entity": "lead",
                                       "params": {}, "is_shared": True}, format="json")
    mine = {v["name"] for v in rep1.get("/api/v1/saved-views/").json()}
    others = {v["name"] for v in rep2.get("/api/v1/saved-views/").json()}
    assert mine == {"My hot leads", "Team board"}
    assert others == {"Team board"}  # private views stay private
    # rep2 cannot edit rep1's shared view
    vid = next(v["id"] for v in rep2.get("/api/v1/saved-views/").json())
    assert rep2.patch(f"/api/v1/saved-views/{vid}/", {"name": "hijack"}).status_code == 403


def test_transfer_records_and_audit(t1, api):
    with tenant_context(t1["tenant"].id):
        services.create_deal(user=t1["users"]["rep1"], title="T1", pipeline=t1["pipeline"])
        services.create_deal(user=t1["users"]["rep1"], title="T2", pipeline=t1["pipeline"])
    admin = api(t1["users"]["admin"])
    r = admin.post(f"/api/v1/users/{t1['users']['rep1'].id}/transfer/",
                   {"to_user_id": t1["users"]["rep2"].id})
    assert r.status_code == 200 and r.json()["transferred"]["deal"] == 2
    with tenant_context(t1["tenant"].id):
        from crm.models import Deal

        assert Deal.objects.filter(owner=t1["users"]["rep2"]).count() == 2
        entry = AuditLog.objects.get(action="transfer")
        assert entry.detail["counts"]["deal"] == 2
    # non-admin blocked
    assert api(t1["users"]["manager"]).post(
        f"/api/v1/users/{t1['users']['rep1'].id}/transfer/",
        {"to_user_id": t1["users"]["rep2"].id}).status_code == 403


def test_transfer_validations(ctx):
    with pytest.raises(ValidationError):
        services.transfer_records(from_user=ctx["users"]["rep1"],
                                  to_user=ctx["users"]["rep1"], actor=ctx["users"]["admin"])


def test_deactivate_endpoint(t1, api):
    admin = api(t1["users"]["admin"])
    rep_client = api(t1["users"]["rep1"])
    assert rep_client.get("/api/v1/deals/").status_code == 200
    r = admin.post(f"/api/v1/users/{t1['users']['rep1'].id}/deactivate/", {})
    assert r.status_code == 200
    assert rep_client.get("/api/v1/deals/").status_code == 401  # token killed
    # self-deactivation blocked
    assert admin.post(f"/api/v1/users/{t1['users']['admin'].id}/deactivate/",
                      {}).status_code == 400


def test_users_list_tenant_scoped(t1, t2, api):
    names = {u["username"] for u in api(t1["users"]["rep1"]).get("/api/v1/users/").json()}
    assert all(n.startswith("alpha_") for n in names)


def test_saved_view_delete_soft(t1, api):
    c = api(t1["users"]["rep1"])
    vid = c.post("/api/v1/saved-views/", {"name": "Temp", "entity": "lead"},
                 format="json").json()["id"]
    assert c.delete(f"/api/v1/saved-views/{vid}/").status_code == 204
    assert c.get("/api/v1/saved-views/").json() == []
    with tenant_context(t1["tenant"].id):
        assert SavedView.unscoped.filter(pk=vid, is_deleted=True).exists()
