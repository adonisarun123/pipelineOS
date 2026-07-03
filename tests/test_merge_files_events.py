"""C-5 merge, file attachments, §7 event bus + webhooks."""
import io

import pytest
from django.core.exceptions import ValidationError

from crm import events, services
from crm.audit import AuditLog
from crm.models import Organization, Person, PersonEmail, PersonPhone, WebhookSubscription
from tenants.context import tenant_context


@pytest.fixture
def ctx(t1):
    with tenant_context(t1["tenant"].id):
        yield t1


def _person(name, phone=None, email=None, **kw):
    p = Person(first_name=name, **kw)
    p.save()
    if phone:
        PersonPhone(person=p, raw=phone, normalized=services.normalize_phone(phone)).save()
    if email:
        PersonEmail(person=p, email=email).save()
    return p


# ---- C-5 merge ----

def test_merge_people_fills_moves_and_audits(ctx):
    user = ctx["users"]["admin"]
    org = Organization(name="Acme")
    org.save()
    primary = _person("Ravi", phone="98765 43210")
    dup = _person("Ravi", phone="98765 43210", email="ravi@acme.in",
                  last_name="Kumar", organization=org)
    deal = services.create_deal(user=user, title="M", pipeline=ctx["pipeline"])
    deal.people.add(dup, through_defaults={"tenant_id": ctx["tenant"].id})
    result = services.merge_people(primary, dup, user)
    primary.refresh_from_db()
    assert primary.last_name == "Kumar" and primary.organization_id == org.id
    assert result["moved"]["phones"] == 0  # same normalized number → not duplicated
    assert result["moved"]["emails"] == 1
    assert primary.phones.count() == 1 and primary.emails.count() == 1
    assert deal.people.filter(pk=primary.pk).exists()
    assert Person.objects.filter(pk=dup.pk).count() == 0  # hidden
    entry = AuditLog.objects.get(model_name="person")
    assert entry.detail["merged_from"] == dup.pk  # reversibility breadcrumb
    with pytest.raises(ValidationError):
        services.merge_people(primary, primary, user)


def test_merge_orgs_and_api_role_gate(t1, api, ctx):
    a = Organization(name="Acme Corp", industry="Events")
    a.save()
    b = Organization(name="ACME Corporation", website="https://acme.in")
    b.save()
    _person("Contact", organization=b)
    r = api(t1["users"]["rep1"]).post(f"/api/v1/organizations/{a.id}/merge/",
                                      {"duplicate_id": b.id})
    assert r.status_code == 403
    r = api(t1["users"]["manager"]).post(f"/api/v1/organizations/{a.id}/merge/",
                                         {"duplicate_id": b.id})
    assert r.status_code == 200
    assert r.json()["moved"]["people"] == 1
    a.refresh_from_db()
    assert a.website == "https://acme.in"  # blank filled from duplicate


# ---- files ----

def _upload(client, name="quote.pdf", deal=None, content=b"%PDF fake"):
    f = io.BytesIO(content)
    f.name = name
    data = {"file": f}
    if deal:
        data["deal"] = deal
    return client.post("/api/v1/files/", data, format="multipart")


def test_file_upload_download_and_tenant_isolation(t1, t2, api, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    with tenant_context(t1["tenant"].id):
        deal = services.create_deal(user=t1["users"]["rep1"], title="F",
                                    pipeline=t1["pipeline"])
    c = api(t1["users"]["rep1"])
    r = _upload(c, deal=deal.id)
    assert r.status_code == 201, r.content
    fid = r.json()["id"]
    assert r.json()["size"] == len(b"%PDF fake")
    listing = c.get(f"/api/v1/files/?deal={deal.id}").json()["results"]
    assert [x["name"] for x in listing] == ["quote.pdf"]
    dl = c.get(f"/api/v1/files/{fid}/download/")
    assert dl.status_code == 200
    assert b"".join(dl.streaming_content) == b"%PDF fake"
    # cross-tenant download → 404
    assert api(t2["users"]["admin"]).get(f"/api/v1/files/{fid}/download/").status_code == 404
    # member cannot delete, manager can (soft)
    assert c.delete(f"/api/v1/files/{fid}/").status_code == 403
    assert api(t1["users"]["manager"]).delete(f"/api/v1/files/{fid}/").status_code == 204


def test_file_size_cap(t1, api, settings, tmp_path):
    settings.MEDIA_ROOT = str(tmp_path)
    big = b"x" * (settings.MAX_ATTACHMENT_MB * 1024 * 1024 + 1)
    assert _upload(api(t1["users"]["rep1"]), content=big).status_code == 400


# ---- event bus + webhooks ----

def test_events_fire_post_commit_and_sign_webhooks(
        ctx, monkeypatch, django_capture_on_commit_callbacks):
    received: list[tuple] = []
    posted: list[dict] = []
    events.register(lambda et, payload, tid: received.append((et, tid)))
    monkeypatch.setattr(events, "_post",
                        lambda url, body, sig: posted.append(
                            {"url": url, "body": body, "sig": sig}))
    WebhookSubscription(url="https://app.trebound.com/hooks/crm",
                        events=["deal.won"], secret="s3cret").save()
    user = ctx["users"]["rep1"]
    with django_capture_on_commit_callbacks(execute=True):
        deal = services.create_deal(user=user, title="EV", pipeline=ctx["pipeline"])
        services.mark_won(deal, user)

    kinds = [k for k, _ in received]
    assert "deal.created" in kinds and "deal.won" in kinds
    # webhook filtered to deal.won only
    assert len(posted) == 1
    import hashlib
    import hmac as hmac_mod
    import json

    body = posted[0]["body"]
    assert json.loads(body)["event"] == "deal.won"
    expected = hmac_mod.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert posted[0]["sig"] == expected
    sub = WebhookSubscription.objects.get()
    assert sub.last_delivery_at is not None and sub.last_error == ""
    events._consumers.clear()


def test_webhook_failure_recorded_not_raised(
        ctx, monkeypatch, django_capture_on_commit_callbacks):
    def boom(url, body, sig):
        raise OSError("connection refused")

    monkeypatch.setattr(events, "_post", boom)
    WebhookSubscription(url="https://down.example", events=[], secret="k").save()
    user = ctx["users"]["rep1"]
    with django_capture_on_commit_callbacks(execute=True):
        services.create_deal(user=user, title="EV2", pipeline=ctx["pipeline"])  # no raise
    sub = WebhookSubscription.objects.get()
    assert "connection refused" in sub.last_error


def test_webhooks_admin_only(t1, api):
    body = {"url": "https://x.example/h", "events": [], "secret": "k"}
    assert api(t1["users"]["manager"]).post("/api/v1/webhooks/", body,
                                            format="json").status_code == 403
    r = api(t1["users"]["admin"]).post("/api/v1/webhooks/", body, format="json")
    assert r.status_code == 201
    assert "secret" not in r.json()  # write-only
