"""Phase 3: self-serve signup, plan limits, trial expiry, billing webhook."""
import hashlib
import hmac
import json
from datetime import timedelta

from django.utils import timezone
from rest_framework.test import APIClient

from tenants.models import Tenant

SIGNUP = {"company": "Acme Events", "subdomain": "acme-events",
          "username": "acme_admin", "email": "a@acme.in",
          "password": "very-good-pass-1"}


def _signup(**overrides):
    return APIClient().post("/api/v1/signup/", {**SIGNUP, **overrides}, format="json")


def test_signup_creates_working_workspace(db):
    r = _signup()
    assert r.status_code == 201, r.content
    body = r.json()
    assert body["role"] == "admin" and body["trial_ends_at"]
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {body['token']}")
    # seeded defaults exist and workspace is usable immediately
    pipes = c.get("/api/v1/pipelines/").json()["results"]
    assert pipes[0]["name"] == "Sales Pipeline" and len(pipes[0]["stages"]) == 4
    r = c.post("/api/v1/deals/", {"title": "First deal", "pipeline": pipes[0]["id"]})
    assert r.status_code == 201
    tenant = Tenant.objects.get(subdomain="acme-events")
    assert tenant.plan == "trial" and tenant.seats_limit == 5


def test_signup_validation(db):
    assert _signup(subdomain="x").status_code == 400            # too short
    assert _signup(password="short").status_code == 400          # weak password
    _signup()
    assert _signup(username="other").status_code == 409          # subdomain taken
    assert _signup(subdomain="other-co").status_code == 409      # username taken


def test_seat_limit_enforced(db, api):
    _signup()
    tenant = Tenant.objects.get(subdomain="acme-events")
    from accounts.models import User

    admin = User.objects.get(username="acme_admin")
    c = APIClient()
    from rest_framework.authtoken.models import Token

    c.credentials(HTTP_AUTHORIZATION=f"Token {Token.objects.get(user=admin).key}")
    for i in range(4):  # admin + 4 = 5 = trial limit
        r = c.post("/api/v1/users/", {"username": f"rep{i}", "email": f"r{i}@a.in",
                                      "password": "very-good-pass-1", "role": "member"})
        assert r.status_code == 201
    r = c.post("/api/v1/users/", {"username": "one-too-many", "email": "x@a.in",
                                  "password": "very-good-pass-1", "role": "member"})
    assert r.status_code == 402 and "Seat limit" in r.json()["detail"]
    assert tenant.seats_limit == 5


def test_trial_expiry_blocks_writes_allows_reads_and_export(db):
    body = _signup().json()
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Token {body['token']}")
    pid = c.get("/api/v1/pipelines/").json()["results"][0]["id"]
    Tenant.objects.filter(subdomain="acme-events").update(
        trial_ends_at=timezone.now() - timedelta(days=1))
    r = c.post("/api/v1/deals/", {"title": "Nope", "pipeline": pid})
    assert r.status_code == 403 and "Trial expired" in r.json()["detail"]
    assert c.get("/api/v1/deals/").status_code == 200          # reads fine
    assert c.get("/api/v1/deals/export/").status_code == 200   # DPDPA export intact


def test_usage_endpoint(t1, api):
    r = api(t1["users"]["admin"]).get("/api/v1/billing/usage/")
    assert r.status_code == 200
    body = r.json()
    assert body["plan"] == "internal" and body["seats_used"] == 5
    assert body["writable"] is True and body["razorpay_configured"] is False


def test_billing_webhook_signature_and_activation(db, monkeypatch):
    _signup()
    monkeypatch.setenv("RAZORPAY_WEBHOOK_SECRET", "whsec_test")
    payload = {"event": "subscription.charged",
               "payload": {"subscription": {"entity": {"notes": {
                   "tenant": "acme-events", "plan": "starter"}}}}}
    raw = json.dumps(payload).encode()
    sig = hmac.new(b"whsec_test", raw, hashlib.sha256).hexdigest()
    c = APIClient()
    # bad signature rejected
    r = c.post("/api/v1/billing/webhook/", data=raw,
               content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE="wrong")
    assert r.status_code == 400
    r = c.post("/api/v1/billing/webhook/", data=raw,
               content_type="application/json", HTTP_X_RAZORPAY_SIGNATURE=sig)
    assert r.status_code == 200 and r.json()["activated"] is True
    tenant = Tenant.objects.get(subdomain="acme-events")
    assert tenant.plan == "starter" and tenant.trial_ends_at is None
    assert tenant.seats_limit == 10


def test_webhook_unconfigured_503(db):
    import os

    assert "RAZORPAY_WEBHOOK_SECRET" not in os.environ
    r = APIClient().post("/api/v1/billing/webhook/", {}, format="json")
    assert r.status_code == 503
