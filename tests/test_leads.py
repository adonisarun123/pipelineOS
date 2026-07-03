"""L-1..L-6: leads queue, dedupe, convert, disqualify."""
import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from crm import services
from crm.leads import Lead, LeadSource
from crm.models import Activity, Deal, Organization, Person
from tenants.context import tenant_context


@pytest.fixture
def ctx(t1):
    with tenant_context(t1["tenant"].id):
        src = LeadSource(name="Chatbot")
        src.save()
        yield {**t1, "source": src}


def _lead(ctx, **kw):
    defaults = dict(name="Ravi Kumar", organization_name="Acme Corp",
                    phone_raw="98765 43210", email="ravi@acme.in",
                    source=ctx["source"], owner=ctx["users"]["rep1"], note="Wants Goa offsite")
    defaults.update(kw)
    lead = Lead(**defaults)
    lead.phone_normalized = services.normalize_phone(lead.phone_raw)
    lead.save()
    return lead


def test_duplicate_detection_by_phone_email_org(ctx):
    _lead(ctx)
    d = services.find_lead_duplicates(phone="+91 98765-43210")  # different format, same number
    assert len(d["leads"]) == 1
    d = services.find_lead_duplicates(email="RAVI@acme.in")
    assert len(d["leads"]) == 1
    d = services.find_lead_duplicates(org_name="acme")
    assert len(d["leads"]) == 1
    d = services.find_lead_duplicates(phone="9000000000")
    assert d["leads"] == [] and d["people"] == []


def test_duplicate_detection_finds_existing_person(ctx):
    lead = _lead(ctx)
    services.convert_lead(lead=lead, user=ctx["users"]["rep1"], pipeline=ctx["pipeline"])
    d = services.find_lead_duplicates(phone="9876543210")
    assert len(d["people"]) == 1  # converted person found by normalized phone


def test_convert_creates_person_org_deal_with_lineage(ctx):
    lead = _lead(ctx)
    act = Activity(type=ctx["activity_type"], subject="Intro call", due_at=timezone.now(),
                   owner=ctx["users"]["rep1"], lead=lead)
    act.save()
    services.convert_lead(lead=lead, user=ctx["users"]["rep1"], pipeline=ctx["pipeline"],
                          deal_title="Acme offsite", value=200000)
    lead.refresh_from_db()
    assert lead.status == Lead.Status.QUALIFIED
    person = lead.converted_person
    assert person.first_name == "Ravi" and person.phones.get().normalized == "+919876543210"
    assert lead.converted_organization.name == "Acme Corp"
    deal = lead.converted_deal
    assert deal.title == "Acme offsite" and deal.owner == ctx["users"]["rep1"]
    act.refresh_from_db()
    assert act.deal_id == deal.id and act.person_id == person.id  # carried across
    assert deal.people.filter(pk=person.pk).exists()


def test_convert_reuses_existing_org_and_blocks_double_convert(ctx):
    existing = Organization(name="Acme Corp")
    existing.save()
    lead = _lead(ctx)
    services.convert_lead(lead=lead, user=ctx["users"]["rep1"], pipeline=ctx["pipeline"])
    assert lead.converted_organization_id == existing.id
    assert Organization.objects.filter(name__iexact="Acme Corp").count() == 1
    with pytest.raises(ValidationError):
        services.convert_lead(lead=lead, user=ctx["users"]["rep1"], pipeline=ctx["pipeline"])


def test_disqualify_requires_reason(ctx):
    lead = _lead(ctx)
    with pytest.raises(ValidationError):
        services.disqualify_lead(lead, ctx["users"]["rep1"], None)
    services.disqualify_lead(lead, ctx["users"]["rep1"], ctx["lost_reason"])
    assert lead.status == Lead.Status.DISQUALIFIED


def test_leads_api_queue_visibility_and_convert(t1, t2, api):
    with tenant_context(t1["tenant"].id):
        src = LeadSource(name="Website")
        src.save()
        mine = Lead(name="Mine", owner=t1["users"]["rep1"], source=src)
        mine.save()
        other = Lead(name="Other", owner=t1["users"]["rep2"], source=src)
        other.save()
    c = api(t1["users"]["rep1"])
    names = {x["name"] for x in c.get("/api/v1/leads/").json()["results"]}
    assert names == {"Mine"}
    # cross-tenant 404
    assert api(t2["users"]["admin"]).get(f"/api/v1/leads/{mine.id}/").status_code == 404
    # convert via API
    r = c.post(f"/api/v1/leads/{mine.id}/convert/",
               {"pipeline_id": t1["pipeline"].id, "deal_title": "Mine deal"})
    assert r.status_code == 200 and r.json()["status"] == "qualified"
    with tenant_context(t1["tenant"].id):
        assert Deal.objects.filter(title="Mine deal").exists()
        assert Person.objects.filter(first_name="Mine").exists()
    # disqualify without reason -> 400
    r = c.post("/api/v1/leads/", {"name": "DQ me"})
    lead_id = r.json()["id"]
    assert c.post(f"/api/v1/leads/{lead_id}/disqualify/", {}).status_code == 400


def test_lead_create_normalizes_phone_and_dupe_endpoint(t1, api):
    c = api(t1["users"]["rep1"])
    r = c.post("/api/v1/leads/", {"name": "P", "phone_raw": "98111 22333"})
    assert r.status_code == 201 and r.json()["phone_normalized"] == "+919811122333"
    d = c.get("/api/v1/leads/duplicates/?phone=+919811122333").json()
    assert len(d["leads"]) == 1


def test_lead_set_status_disposition(t1, api):
    c = api(t1["users"]["rep1"])
    lead_id = c.post("/api/v1/leads/", {"name": "Disp"}).json()["id"]
    r = c.post(f"/api/v1/leads/{lead_id}/set_status/", {"status": "contacted"})
    assert r.status_code == 200 and r.json()["status"] == "contacted"
    assert c.post(f"/api/v1/leads/{lead_id}/set_status/", {"status": "qualified"}).status_code == 400
