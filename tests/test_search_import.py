"""S-1 global search, S-2 filters, I-1 CSV import."""
import pytest

from crm import services
from crm.importer import auto_map, import_people_csv
from crm.leads import Lead
from crm.models import Person, PersonPhone
from tenants.context import tenant_context

CSV = """Name,Company,Email,Mobile
Ravi,Acme Corp,ravi@acme.in,98765 43210
Priya,Beta Ltd,priya@beta.in,91234 56789
,NoName Inc,x@y.in,90000 00000
Dup,Acme Corp,ravi@acme.in,98765 43210
"""


@pytest.fixture
def ctx(t1):
    with tenant_context(t1["tenant"].id):
        yield t1


def test_auto_map_guesses_headers():
    m = auto_map(["Name", "Company", "Email", "Mobile", "Junk"])
    assert m == {"Name": "first_name", "Company": "organization",
                 "Email": "email", "Mobile": "phone", "Junk": None}


def test_import_dry_run_then_real(ctx):
    user = ctx["users"]["admin"]
    mapping = auto_map(["Name", "Company", "Email", "Mobile"])
    dry = import_people_csv(content=CSV, mapping=mapping, strategy="skip",
                            user=user, dry_run=True)
    assert dry.total == 4 and Person.objects.count() == 0  # dry-run writes nothing
    assert len(dry.errors) == 1 and "first_name" in dry.errors[0]["error"]

    real = import_people_csv(content=CSV, mapping=mapping, strategy="skip",
                             user=user, dry_run=False)
    assert real.created == 2 and real.skipped == 1 and len(real.errors) == 1
    assert Person.objects.count() == 2
    assert PersonPhone.objects.filter(normalized="+919876543210").exists()


def test_import_update_strategy(ctx):
    user = ctx["users"]["admin"]
    mapping = auto_map(["Name", "Company", "Email", "Mobile"])
    import_people_csv(content=CSV, mapping=mapping, strategy="skip", user=user, dry_run=False)
    updated_csv = CSV.replace("Ravi,Acme Corp", "Ravindra,Acme Corp")
    r = import_people_csv(content=updated_csv, mapping=mapping, strategy="update",
                          user=user, dry_run=False)
    assert r.updated == 3  # Ravindra + Priya (self-match) + Dup row all match existing
    ravi = Person.objects.get(emails__email="ravi@acme.in")
    assert ravi.first_name == "Dup"  # last row wins within one file (Ravindra then Dup)
    assert Person.objects.count() == 2  # no new people created on update run


def test_import_api_role_gated(t1, api):
    import io

    f = io.BytesIO(CSV.encode())
    f.name = "people.csv"
    r = api(t1["users"]["rep1"]).post("/api/v1/import/people/", {"file": f}, format="multipart")
    assert r.status_code == 403
    f = io.BytesIO(CSV.encode())
    f.name = "people.csv"
    r = api(t1["users"]["admin"]).post("/api/v1/import/people/",
                                       {"file": f, "dry_run": "true"}, format="multipart")
    assert r.status_code == 200
    body = r.json()
    assert body["dry_run"] is True and body["total"] == 4
    assert body["mapping"]["Mobile"] == "phone"


def test_global_search(ctx):
    user = ctx["users"]["rep1"]
    services.create_deal(user=user, title="Infosys offsite", pipeline=ctx["pipeline"])
    lead = Lead(name="Sunil Menon", phone_raw="98222 11000",
                phone_normalized="+919822211000", owner=user)
    lead.save()
    mapping = auto_map(["Name", "Company", "Email", "Mobile"])
    import_people_csv(content=CSV, mapping=mapping, strategy="skip",
                      user=ctx["users"]["admin"], dry_run=False)

    r = services.global_search(user, "infosys")
    assert len(r["deals"]) == 1
    r = services.global_search(user, "acme")
    assert len(r["organizations"]) == 1
    r = services.global_search(user, "9876543210")  # no country code
    assert len(r["people"]) == 1
    r = services.global_search(user, "sunil")
    assert len(r["leads"]) == 1
    assert services.global_search(user, "x") == {
        "deals": [], "people": [], "organizations": [], "leads": []}


def test_search_api_and_visibility(t1, api):
    with tenant_context(t1["tenant"].id):
        services.create_deal(user=t1["users"]["rep2"], title="Secret rep2 deal",
                             pipeline=t1["pipeline"])
    r = api(t1["users"]["rep1"]).get("/api/v1/search/?q=secret")
    assert r.status_code == 200 and r.json()["deals"] == []  # visibility respected
    r = api(t1["users"]["manager"]).get("/api/v1/search/?q=secret")
    assert len(r.json()["deals"]) == 1


def test_deal_list_filters(t1, api):
    with tenant_context(t1["tenant"].id):
        d = services.create_deal(user=t1["users"]["rep1"], title="Big", pipeline=t1["pipeline"],
                                 value=500000)
        services.create_deal(user=t1["users"]["rep1"], title="Small", pipeline=t1["pipeline"],
                             value=1000, stage=t1["stages"][1])
        services.mark_won(d, t1["users"]["rep1"])
    c = api(t1["users"]["rep1"])
    assert [x["title"] for x in c.get("/api/v1/deals/?status=won").json()["results"]] == ["Big"]
    by_stage = c.get(f"/api/v1/deals/?stage={t1['stages'][1].id}").json()["results"]
    assert [x["title"] for x in by_stage] == ["Small"]
    assert [x["title"] for x in c.get("/api/v1/deals/?min_value=10000").json()["results"]] == ["Big"]
