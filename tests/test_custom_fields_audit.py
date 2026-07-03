"""CF-1..4 custom fields, U-4 audit log, I-3 export logging."""
import pytest
from django.core.exceptions import ValidationError

from crm import services
from crm.audit import AuditLog
from crm.custom_fields import CustomFieldDef, CustomFieldValue, set_custom_values
from crm.models import Deal
from tenants.context import tenant_context


@pytest.fixture
def ctx(t1):
    with tenant_context(t1["tenant"].id):
        defs = {}
        for name, key, ftype, opts in [
            ("Event Date", "event_date", "date", []),
            ("Headcount", "headcount", "number", []),
            ("Venue Type", "venue_type", "single_select", ["Resort", "Office", "Outdoor"]),
            ("VIP", "vip", "checkbox", []),
        ]:
            d = CustomFieldDef(entity="deal", name=name, key=key, field_type=ftype,
                               options=opts)
            d.save()
            defs[key] = d
        deal = services.create_deal(user=t1["users"]["rep1"], title="CF deal",
                                    pipeline=t1["pipeline"])
        yield {**t1, "defs": defs, "deal": deal}


def test_set_typed_values_and_cache(ctx):
    deal, user = ctx["deal"], ctx["users"]["rep1"]
    cache = set_custom_values(deal, "deal", {
        "event_date": "2026-11-20", "headcount": 120,
        "venue_type": "Resort", "vip": True,
    }, user)
    assert cache == {"event_date": "2026-11-20", "headcount": "120",
                     "venue_type": "Resort", "vip": True}
    deal.refresh_from_db()
    assert deal.custom["venue_type"] == "Resort"  # denormalized cache persisted
    row = CustomFieldValue.objects.get(definition=ctx["defs"]["headcount"], record_id=deal.pk)
    assert row.value_number == 120  # typed column is source of truth


def test_validation_rejects_bad_values(ctx):
    deal, user = ctx["deal"], ctx["users"]["rep1"]
    with pytest.raises(ValidationError):
        set_custom_values(deal, "deal", {"venue_type": "Moon"}, user)
    with pytest.raises(ValidationError):
        set_custom_values(deal, "deal", {"headcount": "not-a-number"}, user)
    with pytest.raises(ValidationError):
        set_custom_values(deal, "deal", {"event_date": "20-11-2026"}, user)
    with pytest.raises(ValidationError):
        set_custom_values(deal, "deal", {"nonexistent": 1}, user)


def test_clear_value(ctx):
    deal, user = ctx["deal"], ctx["users"]["rep1"]
    set_custom_values(deal, "deal", {"headcount": 50}, user)
    cache = set_custom_values(deal, "deal", {"headcount": None}, user)
    assert "headcount" not in cache


def test_set_custom_api_and_cf_filter(t1, ctx, api):
    c = api(ctx["users"]["rep1"])
    deal = ctx["deal"]
    r = c.post(f"/api/v1/deals/{deal.id}/set_custom/",
               {"venue_type": "Resort", "headcount": 80}, format="json")
    assert r.status_code == 200 and r.json()["custom"]["venue_type"] == "Resort"
    # deal payload carries cache
    assert c.get(f"/api/v1/deals/{deal.id}/").json()["custom"]["headcount"] == "80"
    # CF-3: filterable
    hits = c.get("/api/v1/deals/?cf_venue_type=Resort").json()["results"]
    assert [d["id"] for d in hits] == [deal.id]
    assert c.get("/api/v1/deals/?cf_venue_type=Office").json()["results"] == []
    # bad value -> 400
    assert c.post(f"/api/v1/deals/{deal.id}/set_custom/", {"venue_type": "Moon"},
                  format="json").status_code == 400


def test_custom_field_defs_admin_only(t1, api):
    payload = {"entity": "deal", "name": "X", "key": "x", "field_type": "text"}
    assert api(t1["users"]["rep1"]).post("/api/v1/custom-fields/", payload).status_code == 403
    assert api(t1["users"]["admin"]).post("/api/v1/custom-fields/", payload).status_code == 201


def test_audit_append_only_and_login_logged(t1):
    from rest_framework.test import APIClient

    APIClient().post("/api/v1/auth/login/",
                     {"username": "alpha_rep1", "password": "x-test-pass-123"})
    with tenant_context(t1["tenant"].id):
        entry = AuditLog.objects.get(action="login")
        assert entry.actor.username == "alpha_rep1"
        entry.model_name = "tampered"
        with pytest.raises(ValueError):
            entry.save()


def test_export_role_gated_and_logged(t1, api):
    with tenant_context(t1["tenant"].id):
        services.create_deal(user=t1["users"]["rep1"], title="Exp deal",
                             pipeline=t1["pipeline"], value=9000)
    assert api(t1["users"]["rep1"]).get("/api/v1/deals/export/").status_code == 403
    r = api(t1["users"]["manager"]).get("/api/v1/deals/export/?status=open")
    assert r.status_code == 200 and r["Content-Type"] == "text/csv"
    body = r.content.decode()
    assert "Exp deal" in body
    with tenant_context(t1["tenant"].id):
        entry = AuditLog.objects.get(action="export")
        assert entry.detail["row_count"] == 1
        assert entry.detail["filters"] == {"status": "open"}


def test_audit_api_admin_only(t1, api, t2):
    with tenant_context(t1["tenant"].id):
        from crm import audit

        audit.log(actor=t1["users"]["admin"], action="create", model_name="deal", object_id=1)
    assert api(t1["users"]["rep1"]).get("/api/v1/audit/").json()["results"] == []
    rows = api(t1["users"]["admin"]).get("/api/v1/audit/").json()["results"]
    assert len(rows) == 1
    # cross-tenant: t2 admin sees nothing of t1
    assert api(t2["users"]["admin"]).get("/api/v1/audit/").json()["results"] == []


def test_deal_export_respects_visibility(t1, api):
    with tenant_context(t1["tenant"].id):
        services.create_deal(user=t1["users"]["rep1"], title="Mine",
                             pipeline=t1["pipeline"])
        services.create_deal(user=t1["users"]["rep2"], title="Theirs",
                             pipeline=t1["pipeline"])
    # manager sees team, so both; but a second-team manager would not — covered by
    # visible_deals unit tests. Here: admin export contains both rows.
    body = api(t1["users"]["admin"]).get("/api/v1/deals/export/").content.decode()
    assert "Mine" in body and "Theirs" in body
    with tenant_context(t1["tenant"].id):
        assert Deal.objects.count() == 2
