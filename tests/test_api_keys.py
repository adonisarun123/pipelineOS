"""API-1/API-3: API keys, scopes, tenant throttle, OpenAPI schema."""
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from crm import services
from crm.api_keys import ApiKey
from tenants.context import tenant_context


@pytest.fixture(autouse=True)
def _clear_throttle_cache():
    cache.clear()
    yield
    cache.clear()


def _make_key(t1, scope="read"):
    with tenant_context(t1["tenant"].id):
        key, raw = ApiKey.generate(name="ci", scope=scope,
                                   acting_user=t1["users"]["admin"],
                                   created_by=t1["users"]["admin"])
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f"Api-Key {raw}")
    return key, raw, c


def test_key_auth_reads_and_scopes_writes(t1):
    with tenant_context(t1["tenant"].id):
        services.create_deal(user=t1["users"]["rep1"], title="K",
                             pipeline=t1["pipeline"])
    _key, _raw, c = _make_key(t1, scope="read")
    r = c.get("/api/v1/deals/")
    assert r.status_code == 200 and len(r.json()["results"]) == 1
    # read scope blocks writes
    r = c.post("/api/v1/deals/", {"title": "x", "pipeline": t1["pipeline"].id})
    assert r.status_code == 403 and "read-only" in r.json()["detail"]
    # write scope allows
    _k2, _r2, cw = _make_key(t1, scope="write")
    assert cw.post("/api/v1/deals/", {"title": "via key",
                                      "pipeline": t1["pipeline"].id}).status_code == 201


def test_key_hash_only_stored_and_revocation(t1):
    key, raw, c = _make_key(t1)
    assert raw not in key.key_hash and key.key_hash != raw
    assert c.get("/api/v1/deals/").status_code == 200
    with tenant_context(t1["tenant"].id):
        key.is_active = False
        key.save(update_fields=["is_active"])
    assert c.get("/api/v1/deals/").status_code == 401
    # garbage key
    bad = APIClient()
    bad.credentials(HTTP_AUTHORIZATION="Api-Key pk_live_totallywrong")
    assert bad.get("/api/v1/deals/").status_code == 401


def test_key_is_tenant_scoped(t1, t2):
    with tenant_context(t2["tenant"].id):
        services.create_deal(user=t2["users"]["rep1"], title="Beta secret",
                             pipeline=t2["pipeline"])
    _key, _raw, c = _make_key(t1)
    titles = [d["title"] for d in c.get("/api/v1/deals/").json()["results"]]
    assert "Beta secret" not in titles


def test_tenant_throttle_429(t1, settings):
    from api.api_key_auth import TenantRateThrottle

    original = TenantRateThrottle.rate
    TenantRateThrottle.rate = "3/hour"
    try:
        _key, _raw, c = _make_key(t1)
        codes = [c.get("/api/v1/deals/").status_code for _ in range(5)]
        assert codes[:3] == [200, 200, 200] and 429 in codes[3:]
    finally:
        TenantRateThrottle.rate = original


def test_ui_token_traffic_not_throttled(t1, api):
    from api.api_key_auth import TenantRateThrottle

    original = TenantRateThrottle.rate
    TenantRateThrottle.rate = "1/hour"
    try:
        c = api(t1["users"]["rep1"])
        codes = [c.get("/api/v1/deals/").status_code for _ in range(4)]
        assert codes == [200, 200, 200, 200]  # session/token auth unaffected
    finally:
        TenantRateThrottle.rate = original


def test_key_management_endpoints(t1, api):
    admin = api(t1["users"]["admin"])
    r = admin.post("/api/v1/api-keys/", {"name": "zapier", "scope": "write"})
    assert r.status_code == 201
    raw = r.json()["key"]
    assert raw.startswith("pk_live_")
    listing = admin.get("/api/v1/api-keys/").json()
    assert listing[0]["name"] == "zapier" and "key" not in listing[0]  # shown once
    kid = listing[0]["id"]
    assert admin.post(f"/api/v1/api-keys/{kid}/revoke/", {}).status_code == 200
    # manager blocked
    assert api(t1["users"]["manager"]).post("/api/v1/api-keys/",
                                            {"name": "x"}).status_code == 403


def test_openapi_schema_and_docs(t1, api):
    c = api(t1["users"]["rep1"])
    r = c.get("/api/v1/schema/")
    assert r.status_code == 200
    assert c.get("/api/v1/docs/").status_code == 200
