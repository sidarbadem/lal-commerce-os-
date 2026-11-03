"""
Faz 1 / Aşama 1 (03.11.2026): KDV çift sayım düzeltmesi, e-ticaret stopajı,
gelir vergisi karşılığı ve sipariş export etiketi.

Ağustos 2026 senaryosu canlı DB'deki gider tutarlarıyla kurulur:
  vat_payment 11.617,96 + vat_withholding 1.490,62 = 13.108,58 (nakit çıkışı)
  bagkur 11.808,00, geçici vergi 1.085,20, stopaj 2.737,10
"""

from datetime import datetime
from io import BytesIO

import pytest
from conftest import auth_headers as _auth

import database
import finance_engine as fe
import monthly_reports as mr
from database import (
    upsert_fixed_expense,
    upsert_order_lines,
    upsert_orders,
    upsert_other_financials,
    upsert_product_costs,
)

AUG_START = datetime(2026, 8, 1)
AUG_END = datetime(2026, 8, 31, 23, 59, 59)

EXPENSES = [
    ("4B Bağ-Kur", 11808.00),
    ("G.GEÇİCİ -Tahakkuk", 1085.20),
    ("Gerçek Usulde KDV", 11617.96),
    ("4017 KDV Tevkifatı", 1490.62),
    ("0003 GELİR VERGİSİ S. (MUHTASAR)", 1000.00),
]
STOPPAGE = 2737.10


def _seed_august(with_stoppage=True):
    for label, amount in EXPENSES:
        upsert_fixed_expense({"month": "2026-08", "label": label, "amount": amount, "note": None})
    if with_stoppage:
        ts = int(datetime(2026, 8, 15, 12).timestamp() * 1000)
        upsert_other_financials([{
            "id": "stop1", "marketplace": "trendyol", "transaction_date": ts,
            "barcode": None, "transaction_type": "Stoppage", "raw_transaction_type": "Stopaj",
            "transaction_sub_type": None, "receipt_id": None, "description": None,
            "debt": STOPPAGE, "credit": 0.0, "order_number": None, "payment_order_id": None,
            "payment_date": ts, "shipment_package_id": None,
        }])


def _aug_summary(rate=0.20):
    return fe.compute_profit_summary(start_dt=AUG_START, end_dt=AUG_END,
                                     include_period_expenses=True, provision_rate=rate)


# ------------------------------------------------------------
# 1.1 KDV kârdan düşülmez, ayrı nakit çıkışı olarak döner
# ------------------------------------------------------------

def test_vat_payments_are_cash_outflow_not_profit(db):
    _seed_august()
    t = _aug_summary()["totals"]
    assert t["vatCashPayments"] == pytest.approx(13108.58)
    # Eski formül: net_profit(muhtasar hariç) − tüm 'tax' grubu (KDV + muhtasar dahil)
    old_net = t["netProfit"] + 1000.00
    old_real = old_net - sum(a for _, a in EXPENSES)
    # 1.1 etkisi +13.108,58; 1.2 etkisi −stopaj; muhtasar yalnızca yer değiştirir.
    assert t["realNetProfit"] - old_real == pytest.approx(13108.58 - STOPPAGE)


def test_vat_only_change_without_stoppage_is_exactly_13108_58(db):
    _seed_august(with_stoppage=False)
    t = _aug_summary()["totals"]
    old_real = (t["netProfit"] + 1000.00) - sum(a for _, a in EXPENSES)
    assert t["realNetProfit"] - old_real == pytest.approx(13108.58)


# ------------------------------------------------------------
# 1.2 Stopaj + geçici vergi = gelir vergisi ön ödemeleri; muhtasar iş gideri
# ------------------------------------------------------------

def test_income_tax_prepayments_and_muhtasar_as_business_expense(db):
    _seed_august()
    t = _aug_summary()["totals"]
    assert t["stoppage"] == pytest.approx(STOPPAGE)
    assert t["provisionalTax"] == pytest.approx(1085.20)
    assert t["incomeTaxPrepayments"] == pytest.approx(STOPPAGE + 1085.20)
    assert t["socialPremiums"] == pytest.approx(11808.00)
    assert t["businessExpenses"] == pytest.approx(1000.00)  # muhtasar, KDV'siz
    assert t["realNetProfit"] == pytest.approx(t["netProfit"] - 11808.00 - 1085.20 - STOPPAGE)
    assert t["taxesAndPremiums"] == pytest.approx(11808.00 + 1085.20 + STOPPAGE)


# ------------------------------------------------------------
# 1.3 Gelir vergisi karşılığı
# ------------------------------------------------------------

def test_income_tax_provision_profitable_month():
    p = fe.income_tax_provision(60000, 10000, 3000, 0.20)
    assert p["base"] == 50000
    assert p["gross"] == 10000
    assert p["provision"] == 7000


def test_income_tax_provision_loss_month_credits_prepayments():
    p = fe.income_tax_provision(-5000, 10000, 2000, 0.20)
    assert p["base"] == 0
    assert p["provision"] == -2000  # eksi kalır; YTD toplamı doğru çıksın


def test_income_tax_provision_prepayment_exceeds_provision():
    p = fe.income_tax_provision(12000, 10000, 1000, 0.20)
    assert p["gross"] == 400
    assert p["provision"] == -600


def test_summary_after_tax_profit_identity(db):
    _seed_august()
    t = _aug_summary(rate=0.15)["totals"]
    base = max(0, t["netProfit"] - 11808.00)
    assert t["incomeTaxProvisionRate"] == 0.15
    assert t["incomeTaxProvision"] == pytest.approx(base * 0.15 - (STOPPAGE + 1085.20), abs=0.01)
    # Vergi sonrası = faaliyet kârı − Bağ-Kur − matrah × oran
    assert t["netProfitAfterIncomeTax"] == pytest.approx(t["netProfit"] - 11808.00 - base * 0.15, abs=0.02)


def test_finance_setting_rate_default_and_update(db):
    assert database.get_finance_settings()["income_tax_provision_rate"] == 0.20
    database.save_finance_setting("income_tax_provision_rate", 0.27)
    assert database.get_finance_settings()["income_tax_provision_rate"] == 0.27
    with pytest.raises(ValueError):
        database.save_finance_setting("income_tax_provision_rate", 0.9)
    with pytest.raises(ValueError):
        database.save_finance_setting("bilinmeyen", 1)


def test_compute_profit_summary_reads_rate_from_settings(db):
    database.save_finance_setting("income_tax_provision_rate", 0.10)
    t = fe.compute_profit_summary(start_dt=AUG_START, end_dt=AUG_END, include_period_expenses=True)["totals"]
    assert t["incomeTaxProvisionRate"] == 0.10


def test_expense_group_validation_accepts_new_groups(db):
    item = database.save_expense_type_setting(
        {"type_key": "bagkur", "group_name": "income_tax_prepayment", "vat_included": 0, "vat_rate": 0})
    assert item["group_name"] == "income_tax_prepayment"
    with pytest.raises(ValueError):
        database.save_expense_type_setting({"type_key": "bagkur", "group_name": "xyz", "vat_rate": 0})


def test_default_expense_groups_on_fresh_db(db):
    groups = {r["type_key"]: r["group_name"] for r in database.list_expense_type_settings()}
    assert groups["vat_payment"] == "vat_cash"
    assert groups["vat_withholding"] == "vat_cash"
    assert groups["provisional_tax"] == "income_tax_prepayment"
    assert groups["tax_withholding"] == "business"
    assert groups["bagkur"] == "tax"


def test_monthly_profit_ytd_floor_and_reset(db, monkeypatch):
    values = {"2026-01": -3000.0, "2026-02": 1000.0, "2026-03": 5000.0}

    def fake(start_dt, **kw):
        key = start_dt.strftime("%Y-%m")
        return {"totals": {"incomeTaxProvision": values.get(key, 0.0)},
                "data_quality": {}}
    monkeypatch.setattr(fe, "compute_profit_summary", fake)
    months = fe.monthly_profit(datetime(2026, 1, 1), datetime(2026, 3, 31))
    assert [m["incomeTaxProvisionYtd"] for m in months] == [0.0, 0.0, 3000.0]
    assert not any(m["incomeTaxProvisionYtdPartial"] for m in months)
    partial = fe.monthly_profit(datetime(2026, 2, 1), datetime(2026, 3, 31))
    assert partial[0]["incomeTaxProvisionYtdPartial"] is True


def test_monthly_profit_accrual_does_not_prorate_stoppage(db, monkeypatch):
    def fake(start_dt, **kw):
        return {"totals": {"taxesAndPremiums": 1300.0, "socialPremiums": 1000.0,
                           "provisionalTax": 0.0, "stoppage": 300.0, "realNetProfit": 5000.0},
                "data_quality": {}}
    monkeypatch.setattr(fe, "compute_profit_summary", fake)
    m = fe.monthly_profit(datetime(2026, 11, 1), datetime(2026, 11, 10, 12))[0]
    assert m["inProgress"] is True
    assert m["taxesAndPremiumsAccrued"] == pytest.approx(300.0 + 1000.0 * 10 / 30, abs=0.01)


# ------------------------------------------------------------
# Aylık rapor: yeni alanlar, YTD ve 'kesin' statüsünün korunması
# ------------------------------------------------------------

def test_report_contains_new_metrics_and_ytd(db):
    _seed_august()
    with database.get_connection() as conn:
        mr.ensure_schema(conn)
        jul = {"period": "2026-07", "label": "Temmuz 2026", "status": "kesin", "statusLabel": "Kesin",
               "metrics": {"incomeTaxProvision": -20000.0}, "dataQuality": {}, "products": []}
        mr.save_report(conn, "2026-07", jul)
        conn.commit()
    mr.generate_report("2026-08", force=True)
    with database.get_connection() as conn:
        view = mr.load_report_view(conn, "2026-08")
    m = view["metrics"]
    assert m["vatCashPayments"] == pytest.approx(13108.58)
    assert m["incomeTaxPrepayments"] == pytest.approx(STOPPAGE + 1085.20)
    assert m["incomeTaxProvisionYtd"] == max(0.0, round(-20000.0 + m["incomeTaxProvision"], 2))
    assert any("nakit çıkışı" in n for n in view["notes"])
    assert any("tahmini" in n for n in view["notes"])


def test_regenerate_final_report_keeps_status(db):
    with database.get_connection() as conn:
        mr.ensure_schema(conn)
        old = {"period": "2026-08", "label": "Ağustos 2026", "status": "kesin", "statusLabel": "Kesin",
               "metrics": {}, "dataQuality": {}, "products": []}
        mr.save_report(conn, "2026-08", old, finalized_at="2026-09-05 10:00:00")
        conn.commit()
    res = mr.generate_report("2026-08", force=True, keep_final=True)
    assert res["status"] == "kesin"
    with database.get_connection() as conn:
        r = mr.get_report(conn, "2026-08")
    assert r["status"] == "kesin"
    assert r["finalizedAt"] == "2026-09-05 10:00:00"
    assert "vatCashPayments" in r["data"]["metrics"]


# ------------------------------------------------------------
# 1.4 Sipariş export etiketi + ayar API'si
# ------------------------------------------------------------

def test_orders_export_header_is_line_profit(client):
    auth_headers = _auth()
    from openpyxl import load_workbook
    resp = client.get("/api/orders/export?days=30", headers=auth_headers)
    assert resp.status_code == 200
    ws = load_workbook(BytesIO(resp.data)).active
    headers = [c.value for c in ws[1]]
    assert "Satır Kârı (reklam/sabit gider öncesi)" in headers
    assert "Net Kâr" not in headers


def test_finance_settings_api(client):
    auth_headers = _auth()
    r = client.get("/api/finance-settings", headers=auth_headers)
    assert r.get_json()["settings"]["income_tax_provision_rate"] == 0.20
    r = client.post("/api/finance-settings", json={"income_tax_provision_rate": 0.25}, headers=auth_headers)
    assert r.get_json()["settings"]["income_tax_provision_rate"] == 0.25
    r = client.post("/api/finance-settings", json={"income_tax_provision_rate": 2}, headers=auth_headers)
    assert r.status_code == 400
