"""
tests/test_hb_status_refresh.py
-------------------------------
02.11.2026: HB senkronu iptal (CancelledByCustomer) / iade talebi (ClaimCreated)
durumlarını hiç güncellemiyordu — iptal siparişler kâra satış olarak giriyor,
iade talepleri "settlement bekliyor" uyarısını şişiriyordu.
"""

from datetime import datetime, timedelta

import sync_core
from database import get_connection, upsert_order_lines, upsert_orders
from finance_engine import NEVER_FULFILLED_STATUSES, compute_profit_summary


def _seed(spid, order_number, status, price=100.0, days_ago=5):
    upsert_orders([{
        "shipment_package_id": spid, "marketplace": "hepsiburada",
        "order_number": order_number,
        "order_date": int((datetime.now() - timedelta(days=days_ago)).timestamp() * 1000),
        "status": status, "customer": "T", "cargo_provider": None,
        "gross_amount": price, "discount_amount": 0.0, "net_amount": price,
    }])
    upsert_order_lines([{
        "shipment_package_id": spid, "marketplace": "hepsiburada",
        "barcode": f"BC-{spid}", "merchant_sku": f"SKU-{spid}", "product_name": "Ürün",
        "quantity": 1, "line_unit_price": price, "commission_rate": 10.0,
    }])


def _status(spid):
    with get_connection() as conn:
        return conn.execute("SELECT status FROM orders WHERE marketplace='hepsiburada' "
                            "AND shipment_package_id=?", (spid,)).fetchone()["status"]


def test_hb_cancel_statuses_never_fulfilled():
    for s in ("CancelledByCustomer", "CancelledByMerchant", "CancelledBySap"):
        assert s in NEVER_FULFILLED_STATUSES


def test_resolve_package_status_partial_cancel_stays_live():
    assert sync_core._resolve_hb_package_status(["CancelledByCustomer"]) == "CancelledByCustomer"
    assert sync_core._resolve_hb_package_status(["CancelledByCustomer", "Delivered"]) == "Delivered"
    assert sync_core._resolve_hb_package_status([None]) is None


def test_updates_match_by_package_and_fallback_for_placeholder():
    detail = {"items": [
        {"packageNumber": "111", "status": "ClaimCreated"},
        {"packageNumber": "", "status": "CancelledByCustomer"},
    ]}
    # 111 paket eşleşmesi; -5 placeholder -> tüm kalemler (biri canlı -> ClaimCreated)
    ups = sync_core._hb_status_updates_from_detail([(111, "InTransit"), (-5, "AwaitingPackage")], detail)
    assert (("ClaimCreated", 111) in ups) and (("ClaimCreated", -5) in ups)
    # Değişmeyen durum yazılmaz
    assert sync_core._hb_status_updates_from_detail([(111, "ClaimCreated")], detail) == []


def test_refresh_updates_db_and_profit(db, monkeypatch):
    _seed(201, "HB-CANCEL", "AwaitingPackage")
    _seed(202, "HB-CLAIM", "InTransit")
    _seed(203, "HB-TRANSIT", "InTransit")

    details = {
        "HB-CANCEL": {"items": [{"packageNumber": "", "status": "CancelledByCustomer"}]},
        "HB-CLAIM": {"items": [{"packageNumber": "202", "status": "ClaimCreated"}]},
        "HB-TRANSIT": {"items": [{"packageNumber": "203", "status": "InTransit"}]},
    }
    monkeypatch.setattr(sync_core, "hepsiburada_get",
                        lambda path, params=None: details[path.rstrip("/").split("/")[-1]])

    before = compute_profit_summary(days=30)["data_quality"]
    assert before["lines_estimated_pending_settlement"] == 3

    res = sync_core.refresh_hb_order_statuses(force=True)
    assert res == {"checked": 3, "updated": 2, "failed": 0, "skipped": False}
    assert _status(201) == "CancelledByCustomer"
    assert _status(202) == "ClaimCreated"
    assert _status(203) == "InTransit"

    after = compute_profit_summary(days=30)
    dq = after["data_quality"]
    assert dq["lines_estimated_pending_settlement"] == 1   # sadece InTransit
    assert dq["lines_claim_pending"] == 1                  # iade talebi ayrı
    assert {l["orderNumber"] for l in after["lines"]} == {"HB-CLAIM", "HB-TRANSIT"}  # iptal kârdan çıktı

    # Aralık dolmadan ikinci çağrı API'ye gitmez
    assert sync_core.refresh_hb_order_statuses()["skipped"] is True


# ---- Kâr motoru korumaları (02.11.2026) ----
from database import upsert_product_costs, upsert_settlements  # noqa: E402


def _hb_settlement(id_, spid, order_number, barcode, raw_type, amount, days_ago=5):
    return {
        "id": id_, "marketplace": "hepsiburada",
        "transaction_date": int((datetime.now() - timedelta(days=days_ago)).timestamp() * 1000),
        "barcode": barcode, "transaction_type": "Sale", "raw_transaction_type": raw_type,
        "receipt_id": None, "description": "Ürün", "debt": 0.0, "credit": 0.0,
        "payment_period": None, "commission_rate": None,
        "commission_amount": abs(amount) if raw_type != "Payment" else 0.0,
        "seller_revenue": amount, "order_number": order_number,
        "payment_order_id": None, "payment_date": None, "shipment_package_id": spid,
    }


def test_settled_placeholder_not_double_counted(db):
    # Placeholder (negatif id, merchant SKU barkodu) gerçek pakete hiç dönüşmemiş,
    # ama gerçek paket numarasıyla satış kaydı gelmiş -> tek satış sayılmalı.
    _seed(-777, "HB-PH", "AwaitingPackage", price=500.0)
    upsert_settlements([
        _hb_settlement("p1", 9001, "HB-PH", "HBCV-X", "Payment", 500.0),
        _hb_settlement("p2", 9001, "HB-PH", "HBCV-X", "Commission", -100.0),
    ])
    lines = [l for l in compute_profit_summary(days=30)["lines"] if l["orderNumber"] == "HB-PH"]
    assert len(lines) == 1
    assert lines[0]["fromSettlementOnly"] and not lines[0]["estimated"]


def test_unsettled_placeholder_still_counted(db):
    _seed(-778, "HB-PH2", "AwaitingPackage", price=300.0, days_ago=1)
    lines = [l for l in compute_profit_summary(days=30)["lines"] if l["orderNumber"] == "HB-PH2"]
    assert len(lines) == 1 and lines[0]["estimated"]


def test_fee_only_settlement_has_no_cogs(db):
    upsert_product_costs([{
        "sku": "HBCV-FEE", "product_name": "Ürün",
        "sale_price_incl_vat": 1200.0, "sale_price_excl_vat": 1000.0,
        "cost_incl_vat": 600.0, "cost_excl_vat": 500.0,
    }])
    upsert_settlements([_hb_settlement("f1", 9100, "HB-FEE", "HBCV-FEE", "ProcessingFeeExpense", -13.19)])
    line = next(l for l in compute_profit_summary(days=30)["lines"] if l["orderNumber"] == "HB-FEE")
    assert line["quantity"] == 0
    assert not line["cogs"]
    assert line["profit"] < 0 and line["profit"] > -20   # sadece masraf
