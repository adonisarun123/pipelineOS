"""L-7 capture, L-8 SLA, time triggers, AU-2 celery-eager dispatch."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from crm import services
from crm.automation import AutomationRule, AutomationRun
from crm.leads import Lead, LeadSource
from crm.models import Notification
from tenants.context import tenant_context


@pytest.fixture
def src(t1):
    with tenant_context(t1["tenant"].id):
        s = LeadSource(name="Chatbot", token="tok_" + "x" * 28, sla_minutes=15,
                       field_mapping={"full_name": "name", "mobile": "phone_raw"})
        s.save()
        return s


# ---- L-7 capture ----

def test_capture_creates_lead_with_mapping_and_utm(
        t1, src, django_capture_on_commit_callbacks):
    with tenant_context(t1["tenant"].id):
        AutomationRule(name="rr", trigger="lead.created",
                       actions=[{"type": "change_owner", "username": "round_robin"}]).save()
    with django_capture_on_commit_callbacks(execute=True):
        r = APIClient().post(f"/api/v1/capture/{src.token}/", {
            "full_name": "Asha Enquiry", "mobile": "98222 33444",
            "utm_source": "google", "utm_campaign": "offsites",
            "ignored_field": "junk",
        }, format="json")
    assert r.status_code == 201, r.content
    with tenant_context(t1["tenant"].id):
        lead = Lead.objects.get(pk=r.json()["id"])
        assert lead.name == "Asha Enquiry"
        assert lead.phone_normalized == "+919822233444"
        assert lead.utm == {"utm_source": "google", "utm_campaign": "offsites"}
        assert lead.source_id == src.id
        assert lead.owner is not None  # recipe assigned via round robin
        assert AutomationRun.objects.filter(status="success").exists()


def test_capture_bad_token_404_and_missing_name_400(t1, src):
    assert APIClient().post("/api/v1/capture/tok_wrongwrongwrongwrong/", {
        "full_name": "X"}, format="json").status_code == 404
    assert APIClient().post("/api/v1/capture/short/", {}, format="json").status_code == 404
    r = APIClient().post(f"/api/v1/capture/{src.token}/", {"mobile": "9%s" % ("1" * 9)},
                         format="json")
    assert r.status_code == 400


# ---- L-8 SLA ----

def test_sla_overdue_flag_and_first_response_stamp(t1, src, api):
    with tenant_context(t1["tenant"].id):
        lead = Lead(name="Slow", source=src, owner=t1["users"]["rep1"])
        lead.save()
        Lead.unscoped.filter(pk=lead.pk).update(
            created_at=timezone.now() - timedelta(minutes=30))
        lead.refresh_from_db()
        assert services.lead_is_sla_overdue(lead) is True
    c = api(t1["users"]["rep1"])
    row = next(x for x in c.get("/api/v1/leads/?status=new").json()["results"]
               if x["id"] == lead.pk)
    assert row["sla_overdue"] is True
    c.post(f"/api/v1/leads/{lead.pk}/set_status/", {"status": "attempted"})
    lead.refresh_from_db()
    assert lead.first_response_at is not None
    assert services.lead_is_sla_overdue(lead) is False


def test_time_command_notifies_sla_breach_once(t1, src):
    from django.core.management import call_command

    with tenant_context(t1["tenant"].id):
        lead = Lead(name="Breach", source=src, owner=t1["users"]["rep1"])
        lead.save()
        Lead.unscoped.filter(pk=lead.pk).update(
            created_at=timezone.now() - timedelta(hours=2))
    call_command("run_time_automations")
    call_command("run_time_automations")  # second run must not duplicate
    with tenant_context(t1["tenant"].id):
        assert Notification.objects.filter(kind="overdue", link_id=lead.pk).count() == 1


# ---- time-based triggers ----

def test_stage_idle_trigger_with_attrs(t1, django_capture_on_commit_callbacks):
    from django.core.management import call_command

    with tenant_context(t1["tenant"].id):
        AutomationRule(
            name="idle nudge", trigger="deal.stage_idle",
            conditions={"all": [{"field": "days_idle", "op": "gte", "value": 3}]},
            actions=[{"type": "notify", "title": "Deal idle too long"}]).save()
        fresh = services.create_deal(user=t1["users"]["rep1"], title="Fresh",
                                     pipeline=t1["pipeline"])
        stale = services.create_deal(user=t1["users"]["rep1"], title="Stale",
                                     pipeline=t1["pipeline"])
        from crm.models import Deal

        Deal.unscoped.filter(pk=stale.pk).update(
            stage_entered_at=timezone.now() - timedelta(days=5))
    with django_capture_on_commit_callbacks(execute=True):
        call_command("run_time_automations")
    with tenant_context(t1["tenant"].id):
        notes = Notification.objects.filter(title="Deal idle too long")
        assert notes.count() == 1  # stale only; fresh (<1 day) never even emits
        run = AutomationRun.objects.get(event_type="deal.stage_idle")
        assert run.status == "success" and run.record_id == stale.pk
        assert fresh.pk  # fresh deal untouched


# ---- AU-2 eager celery ----

def test_celery_eager_dispatch_path(t1, settings, django_capture_on_commit_callbacks):
    settings.USE_CELERY = True
    settings.CELERY_TASK_ALWAYS_EAGER = True
    settings.CELERY_BROKER_URL = "memory://"
    with tenant_context(t1["tenant"].id):
        AutomationRule(name="won note", trigger="deal.won",
                       actions=[{"type": "notify", "title": "via celery"}]).save()
        with django_capture_on_commit_callbacks(execute=True):
            deal = services.create_deal(user=t1["users"]["rep1"], title="C",
                                        pipeline=t1["pipeline"])
            services.mark_won(deal, t1["users"]["rep1"])
        assert Notification.objects.filter(title="via celery").count() == 1
