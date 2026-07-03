"""S1: tenant isolation — the SaaS trust foundation (spec §8)."""
import pytest

from crm import services
from crm.models import Deal, Pipeline
from tenants.context import TenantContextError, tenant_context


def _mkdeal(t, title="Deal", **kw):
    with tenant_context(t["tenant"].id):
        return services.create_deal(
            user=t["users"]["rep1"], title=title, pipeline=t["pipeline"], **kw
        )


def test_manager_fails_closed_without_context(t1):
    with pytest.raises(TenantContextError):
        list(Deal.objects.all())


def test_save_fails_closed_without_context(t1):
    with pytest.raises(TenantContextError):
        Pipeline(name="Rogue").save()


def test_queries_scoped_to_current_tenant(t1, t2):
    _mkdeal(t1, "Alpha deal")
    _mkdeal(t2, "Beta deal")
    with tenant_context(t1["tenant"].id):
        titles = set(Deal.objects.values_list("title", flat=True))
    assert titles == {"Alpha deal"}


def test_save_auto_assigns_current_tenant(t1):
    deal = _mkdeal(t1)
    assert deal.tenant_id == t1["tenant"].id


def test_soft_deleted_hidden(t1):
    deal = _mkdeal(t1)
    with tenant_context(t1["tenant"].id):
        deal.is_deleted = True
        deal.save()
        assert Deal.objects.count() == 0
        assert Deal.unscoped.count() == 1


def test_cross_tenant_api_read_is_404(t1, t2, api):
    """Tenant A token + tenant B deal id → 404, no existence leak."""
    beta_deal = _mkdeal(t2)
    client = api(t1["users"]["admin"])
    assert client.get(f"/api/v1/deals/{beta_deal.id}/").status_code == 404
    assert client.post(f"/api/v1/deals/{beta_deal.id}/won/").status_code == 404


def test_cross_tenant_list_leaks_nothing(t1, t2, api):
    _mkdeal(t1, "Alpha deal")
    _mkdeal(t2, "Beta deal")
    r = api(t1["users"]["admin"]).get("/api/v1/deals/")
    titles = {d["title"] for d in r.json()["results"]}
    assert titles == {"Alpha deal"}


def test_cross_tenant_pipelines_and_reasons(t1, t2, api):
    c = api(t1["users"]["admin"])
    pipeline_ids = {p["id"] for p in c.get("/api/v1/pipelines/").json()["results"]}
    assert t2["pipeline"].id not in pipeline_ids
    reason_ids = {x["id"] for x in c.get("/api/v1/lost-reasons/").json()}
    assert t2["lost_reason"].id not in reason_ids
