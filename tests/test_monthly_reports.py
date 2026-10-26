import copy
import sqlite3
from datetime import datetime

import pytest

import monthly_reports as mr


def _fake_summary(missing_cargo=0, estimated=0):
    return {
        "totals": {"grossRevenue": 10000.0, "returnAmount": 500.0, "netRevenue": 9500.0,
                   "cogsTotal": 6000.0, "commission": 1000.0, "cargoTotal": 800.0,
                   "stoppage": 50.0, "platformServiceFee": 20.0, "overheadTotal": 300.0,
                   "netProfit": 1200.0, "businessExpenses": 0.0,
                   "taxesAndPremiums": 200.0, "unallocatedExpenses": 0.0,
                   "realNetProfit": 1000.0,
                   "vatAssumed": False, "vatAssumptionCount": 0,
                   "expenseDuplicates": [], "withholdingForOffset": 0.0,
                   "vatWithholdingNotOffset": 0.0, "vatPayableEstimate": 0.0},
        "data_quality": {"lines_with_real_settlement": 3,
                         "lines_estimated_pending_settlement": estimated,
                         "skus_missing_cost": [], "orders_missing_cargo_invoice": missing_cargo},
        "by_marketplace": {"trendyol": {"grossRevenue": 10000.0}},
        "lines": [
            {"marketplace": "trendyol", "orderNumber": "A1", "sku": "S1", "barcode": "b1",
             "productName": "Musluk", "quantity": 2, "grossRevenue": 6000.0, "profit": 700.0},
            {"marketplace": "trendyol", "orderNumber": "A2", "sku": "S1", "barcode": "b1",
             "productName": "Musluk", "quantity": 1, "grossRevenue": 3000.0, "profit": 300.0},
            {"marketplace": "hepsiburada", "orderNumber": "A3", "sku": "S2", "barcode": "b2",
             "productName": "Tank", "quantity": 1, "grossRevenue": 1000.0, "profit": None},
        ],
    }


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@pytest.fixture
def fake_engine(monkeypatch):
    state = {"missing": 0, "estimated": 0}
    monkeypatch.setattr(mr.finance_engine, "compute_profit_summary",
                        lambda **kw: _fake_summary(state["missing"], state["estimated"]))
    monkeypatch.setattr(mr.finance_engine, "get_fixed_expenses_by_month",
                        lambda a, b: {"2026-09": 200.0})
    return state


def test_period_helpers():
    assert mr.shift_period("2026-01", -1) == "2025-12"
    assert mr.shift_period("2026-12", 1) == "2027-01"
    assert mr.shift_period("2026-09", -12) == "2025-09"
    assert mr.previous_period(datetime(2026, 11, 1)) == "2026-10"
    assert mr.previous_period(datetime(2027, 1, 1)) == "2026-12"
    start, end = mr.period_range("2028-02")
    assert start.day == 1 and end.day == 29 and end.hour == 23


def test_aggregate_products_groups_by_sku():
    prods = mr.aggregate_products(_fake_summary()["lines"])
    s1 = [p for p in prods if p["key"] == "S1"][0]
    assert s1["quantity"] == 3 and s1["revenue"] == 9000.0 and s1["profit"] == 1000.0
    assert s1["margin"] == round(1000.0 / 9000.0, 4)
    s2 = [p for p in prods if p["key"] == "S2"][0]
    assert s2["profit"] is None and s2["margin"] is None
    assert prods[0]["key"] == "S1"


def test_build_report_data_metrics_and_status(fake_engine):
    data = mr.build_report_data("2026-09")
    m = data["metrics"]
    assert m["orderCount"] == 3 and m["unitCount"] == 4
    assert m["avgBasket"] == round(10000.0 / 3, 2)
    assert m["fixedExpenses"] == 200.0 and m["realNetProfit"] == 1000.0
    assert data["status"] == "kesin"
    fake_engine["missing"] = 2
    assert mr.build_report_data("2026-09")["status"] == "taslak"
    fake_engine["missing"] = 0
    fake_engine["estimated"] = 1
    assert mr.build_report_data("2026-09")["status"] == "taslak"


def test_save_upsert_keeps_ai_summary(conn, fake_engine):
    data = mr.build_report_data("2026-09")
    mr.save_report(conn, "2026-09", data)
    conn.execute("UPDATE monthly_reports SET ai_summary = 'yorum' WHERE period = '2026-09'")
    data["status"] = "taslak"
    mr.save_report(conn, "2026-09", data)
    r = mr.get_report(conn, "2026-09")
    assert r["status"] == "taslak" and r["aiSummary"] == "yorum" and r["finalizedAt"] is None


def test_view_compares_with_previous_month(conn, fake_engine):
    cur = mr.build_report_data("2026-09")
    prev = copy.deepcopy(cur)
    prev["period"] = "2026-08"
    prev["metrics"]["netProfit"] = 1000.0
    mr.save_report(conn, "2026-08", prev)
    mr.save_report(conn, "2026-09", cur)
    view = mr.load_report_view(conn, "2026-09")
    assert view["compare"]["prev"]["netProfit"]["pct"] == 20.0
    assert view["compare"]["yoy"]["netProfit"]["pct"] is None
    s1 = [p for p in view["products"] if p["key"] == "S1"][0]
    assert s1["revenuePct"] == 0.0
    assert [s["period"] for s in view["series"]] == ["2026-08", "2026-09"]
    assert view["lossMaking"] == []


def test_notify_ready_only_once(conn, fake_engine):
    data = mr.build_report_data("2026-09")
    assert mr._notify_ready(conn, "2026-09", data) is True
    assert mr._notify_ready(conn, "2026-09", data) is False
    rows = conn.execute("SELECT kind, title FROM notifications").fetchall()
    assert len(rows) == 1
    assert rows[0]["kind"] == "report" and rows[0]["title"] == "Eylül 2026 raporu hazır"
