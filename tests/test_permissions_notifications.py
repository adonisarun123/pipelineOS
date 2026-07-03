"""Increment 8: permission matrix hardening, notifications, digest, email account."""
import pytest
from django.core import mail

from crm import services
from crm.models import Deal, Notification
from tenants.context import tenant_context


@pytest.fixture
def deal(t1):
    with tenant_context(t1["tenant"].id):
        return services.create_deal(user=t1["users"]["rep1"], title="P8",
                                    pipeline=t1["pipeline"], value=100)


# ---- U-1 matrix hardening ----

def test_member_cannot_delete_manager_can_soft_delete(t1, api, deal):
    assert api(t1["users"]["rep1"]).delete(f"/api/v1/deals/{deal.id}/").status_code == 403
    assert api(t1["users"]["manager"]).delete(f"/api/v1/deals/{deal.id}/").status_code == 204
    with tenant_context(t1["tenant"].id):
        assert Deal.objects.count() == 0                      # hidden
        assert Deal.unscoped.filter(pk=deal.pk).exists()      # soft, not hard


def test_pipeline_config_admin_only(t1, api):
    body = {"name": "New Pipe", "order": 9}
    assert api(t1["users"]["manager"]).post("/api/v1/pipelines/", body).status_code == 403
    r = api(t1["users"]["admin"]).post("/api/v1/pipelines/", body)
    assert r.status_code == 201
    s = api(t1["users"]["admin"]).post("/api/v1/stages/", {
        "pipeline": r.json()["id"], "name": "S1", "order": 0, "rot_days": 5})
    assert s.status_code == 201
    assert api(t1["users"]["rep1"]).post("/api/v1/stages/", {
        "pipeline": r.json()["id"], "name": "X", "order": 1}).status_code == 403


def test_user_creation_admin_only_with_password_validation(t1, api):
    body = {"username": "newrep", "password": "ok-pass-12345", "role": "member",
            "team": t1["team"].id, "email": "n@x.in"}
    assert api(t1["users"]["manager"]).post("/api/v1/users/", body).status_code == 403
    r = api(t1["users"]["admin"]).post("/api/v1/users/", body)
    assert r.status_code == 201 and r.json()["role"] == "member"
    weak = {**body, "username": "weak", "password": "short"}
    assert api(t1["users"]["admin"]).post("/api/v1/users/", weak).status_code == 400


def test_bulk_edit_role_gated_and_reassigns(t1, api):
    with tenant_context(t1["tenant"].id):
        d1 = services.create_deal(user=t1["users"]["rep1"], title="B1", pipeline=t1["pipeline"])
        d2 = services.create_deal(user=t1["users"]["rep1"], title="B2", pipeline=t1["pipeline"])
    body = {"ids": [d1.id, d2.id], "set": {"owner": t1["users"]["rep2"].id}}
    assert api(t1["users"]["rep1"]).post("/api/v1/deals/bulk/", body,
                                         format="json").status_code == 403
    r = api(t1["users"]["manager"]).post("/api/v1/deals/bulk/", body, format="json")
    assert r.status_code == 200 and r.json()["updated"] == 2
    with tenant_context(t1["tenant"].id):
        assert Deal.objects.filter(owner=t1["users"]["rep2"]).count() == 2
        # N-2: assignment notifications created for the new owner
        assert Notification.objects.filter(user=t1["users"]["rep2"],
                                           kind="assigned").count() == 2


# ---- N-1/N-2 notifications ----

def test_assignment_notification_on_create_not_self(t1, api):
    c = api(t1["users"]["manager"])
    c.post("/api/v1/deals/", {"title": "For rep1", "pipeline": t1["pipeline"].id,
                              "owner": t1["users"]["rep1"].id})
    c.post("/api/v1/deals/", {"title": "For self", "pipeline": t1["pipeline"].id})
    with tenant_context(t1["tenant"].id):
        assert Notification.objects.filter(user=t1["users"]["rep1"]).count() == 1
        assert Notification.objects.filter(user=t1["users"]["manager"]).count() == 0


def test_notifications_api_own_only_and_mark_read(t1, api):
    with tenant_context(t1["tenant"].id):
        services.notify(user=t1["users"]["rep1"], kind="system", title="T1")
        services.notify(user=t1["users"]["rep2"], kind="system", title="T2")
    c = api(t1["users"]["rep1"])
    rows = c.get("/api/v1/notifications/").json()["results"]
    assert [n["title"] for n in rows] == ["T1"]
    assert c.get("/api/v1/notifications/unread_count/").json()["count"] == 1
    c.post(f"/api/v1/notifications/{rows[0]['id']}/read/", {})
    assert c.get("/api/v1/notifications/unread_count/").json()["count"] == 0


# ---- N-3 digest ----

def test_digest_sends_only_when_content(t1):
    from datetime import timedelta

    from django.core.management import call_command
    from django.utils import timezone

    from crm.models import Activity

    with tenant_context(t1["tenant"].id):
        Activity(type=t1["activity_type"], subject="Overdue call",
                 due_at=timezone.now() - timedelta(days=1),
                 owner=t1["users"]["rep1"]).save()
    mail.outbox.clear()
    call_command("send_daily_digest")
    recipients = [m.to[0] for m in mail.outbox]
    assert t1["users"]["rep1"].email in recipients
    body = next(m.body for m in mail.outbox if m.to == [t1["users"]["rep1"].email])
    assert "Overdue call" in body
    # users with nothing to report get no mail
    assert t1["users"]["ro"].email not in recipients


# ---- E-1 groundwork ----

def test_email_account_connect_flow(t1, api):
    c = api(t1["users"]["rep1"])
    assert c.get("/api/v1/email-account/").json()["status"] == "not_connected"
    r = c.post("/api/v1/email-account/", {"address": "rep1@trebound.in"})
    assert r.status_code == 201
    assert r.json()["status"] == "pending"
    assert "GOOGLE_OAUTH_CLIENT_ID" in r.json()["next_step"]
    assert "oauth_credentials" not in r.json()  # never exposed
    assert c.get("/api/v1/email-account/").json()["address"] == "rep1@trebound.in"
    assert c.delete("/api/v1/email-account/").status_code == 204
    assert c.get("/api/v1/email-account/").json()["status"] == "disabled"
