"""PR-1/PR-2 products + line items, CF-2 stage nudges, R-1 pipeline summary."""
from decimal import Decimal

import pytest

from crm import services
from crm.custom_fields import CustomFieldDef
from crm.models import DealLineItem, Product
from tenants.context import tenant_context


@pytest.fixture
def ctx(t1):
    with tenant_context(t1["tenant"].id):
        p1 = Product(name="Full Day", unit_price=Decimal("2500.00"), tax_rate=18)
        p1.save()
        p2 = Product(name="Coach", unit_price=Decimal("15000.00"), tax_rate=5)
        p2.save()
        deal = services.create_deal(user=t1["users"]["rep1"], title="LI deal",
                                    pipeline=t1["pipeline"], value=999)
        yield {**t1, "p1": p1, "p2": p2, "deal": deal}


def test_subtotal_math_with_discount(ctx):
    li = DealLineItem(deal=ctx["deal"], product=ctx["p1"], quantity=Decimal("40"),
                      unit_price=Decimal("2500.00"), discount_pct=Decimal("10"))
    li.save()
    # 40 × 2500 = 100000; −10% = 90000.00 (pre-tax, per stated assumption)
    assert li.subtotal == Decimal("90000.00")


def test_auto_sum_recompute_and_manual_mode(ctx):
    deal = ctx["deal"]
    DealLineItem(deal=deal, product=ctx["p1"], quantity=2,
                 unit_price=Decimal("2500.00")).save()
    services.recompute_deal_value(deal)
    assert deal.value == Decimal("999")  # manual mode untouched (PR-2)
    deal.value_auto = True
    deal.save(update_fields=["value_auto"])
    services.recompute_deal_value(deal)
    assert deal.value == Decimal("5000.00")


def test_line_items_api_flow(t1, ctx, api):
    c = api(ctx["users"]["rep1"])
    deal = ctx["deal"]
    c.patch(f"/api/v1/deals/{deal.id}/", {"value_auto": True}, format="json")
    r = c.post(f"/api/v1/deals/{deal.id}/line_items/",
               {"product": ctx["p1"].id, "quantity": "40", "discount_pct": "10"},
               format="json")
    assert r.status_code == 200, r.content
    body = r.json()
    assert body["items"][0]["unit_price"] == "2500.00"  # price from catalogue
    assert body["deal_value"] == "90000.00" and body["value_auto"] is True
    item_id = body["items"][0]["id"]
    r = c.delete(f"/api/v1/deals/{deal.id}/line_items/{item_id}/")
    assert r.status_code == 200 and r.json()["deal_value"] == "0.00"


def test_stage_nudges_on_move(t1, ctx, api):
    with tenant_context(t1["tenant"].id):
        CustomFieldDef(entity="deal", name="Event Date", key="event_date",
                       field_type="date", is_important=True, nudge_stage_order=1).save()
    c = api(ctx["users"]["rep1"])
    deal = ctx["deal"]
    # move to stage order 1 with empty event_date → nudge listed, move NOT blocked
    r = c.post(f"/api/v1/deals/{deal.id}/move/", {"stage_id": t1["stages"][1].id})
    assert r.status_code == 200
    assert r.json()["nudges"] == ["Event Date"]
    assert r.json()["stage"] == t1["stages"][1].id
    # fill it → no nudge on next move
    c.post(f"/api/v1/deals/{deal.id}/set_custom/", {"event_date": "2026-12-01"},
           format="json")
    r = c.post(f"/api/v1/deals/{deal.id}/move/", {"stage_id": t1["stages"][2].id})
    assert r.json()["nudges"] == []


def test_pipeline_summary(t1, api):
    with tenant_context(t1["tenant"].id):
        d1 = services.create_deal(user=t1["users"]["rep1"], title="S1",
                                  pipeline=t1["pipeline"], value=10000)  # stage prob 10
        services.create_deal(user=t1["users"]["rep1"], title="S2",
                             pipeline=t1["pipeline"], value=5000,
                             stage=t1["stages"][1])  # prob 20
        won = services.create_deal(user=t1["users"]["rep1"], title="W",
                                   pipeline=t1["pipeline"], value=7000)
        services.mark_won(won, t1["users"]["rep1"])
        d1.probability = 50  # per-deal override beats stage default
        d1.save(update_fields=["probability"])
    r = api(t1["users"]["manager"]).get(f"/api/v1/pipelines/{t1['pipeline'].id}/summary/")
    assert r.status_code == 200
    s = r.json()
    assert s["open_count"] == 2 and s["open_value"] == "15000.00"
    # 10000×50% + 5000×20% = 6000
    assert s["weighted_forecast"] == "6000.00"
    assert s["won_this_month"] == {"count": 1, "value": "7000.00"}
    assert s["added_this_month"] == 3
    assert s["needs_next_activity"] == 2
