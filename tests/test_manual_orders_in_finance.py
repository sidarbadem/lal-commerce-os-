"""
tests/test_manual_orders_in_finance.py
--------------------------------------
Manuel siparişler (softhydra.com / n11 / Amazon) yalnızca Siparişler
listesinde görünüyordu; Bugünkü Satış, günlük kâr, Gösterge Paneli ve aylık
grafikler (daily-sales, today-order-count, today-net-profit,
compute_profit_summary, monthly_profit) onları hiç saymıyordu.

Bu test, bir manuel siparişin HER BİRİNDE göründüğünü ve iptal edilen manuel
siparişin görünmediğini kanıtlar.

Hesap (tek kalem: 2 adet x 500 TL satış, birim maliyet 200 TL, komisyon 50 TL,
kargo 30 TL):
  ciro = 1000, COGS = 400, brüt kâr (ciro-COGS) = 600,
  net kâr = 1000 - 400 - 50 - 30 = 520
"""

from datetime import datetime, timedelta

import finance_engine
import manual_orders
import pytest
from tests.conftest import auth_headers


def _seed_sku(db_module, sku="SKU-MAN-1", cost=200.0, price=500.0):
    with db_module.get_connection() as conn:
        conn.execute(
            "INSERT INTO product_costs (sku, product_name, cost_incl_vat, sale_price_incl_vat) VALUES (?, ?, ?, ?)",
            (sku, "Manuel Test Ürünü", cost, price),
        )
        conn.commit()


def _manual(status="Delivered", when=None, channel="softhydra"):
    when = when or (datetime.now() - timedelta(minutes=1))
    return manual_orders.create_manual_order({
        "channel": channel,
        "order_date": when.strftime("%Y-%m-%dT%H:%M"),
        "status": status,
        "items": [{"sku": "SKU-MAN-1", "quantity": 2, "unit_price": 500}],
        "commission": 50,
        "cargo_cost": 30,
    })


def test_manual_order_counts_in_daily_sales_and_today_counters(client, db):
    _seed_sku(db)
    _manual()
    today = datetime.now().strftime("%Y-%m-%d")

    resp = client.get("/api/daily-sales?full_history=true", headers=auth_headers())
    assert resp.status_code == 200
    day = next(d for d in resp.get_json()["daily"] if d["date"] == today)
    assert day["order_count"] == 1
    assert day["net_amount"] == 1000.0
    assert day["gross_amount"] == 1000.0
    assert day["item_count"] == 2
    assert day["commission_amount"] == 50.0

    resp = client.get("/api/today-order-count", headers=auth_headers())
    assert resp.get_json()["count"] == 1

    resp = client.get("/api/today-net-profit", headers=auth_headers())
    body = resp.get_json()
    assert body["netProfit"] == round(1000 / 1.2 - 400 / 1.2 - 50 / 1.2 - 30 / 1.2, 2)
    assert body["hasMissingCost"] is False


def test_manual_order_counts_in_profit_summary_and_monthly(client, db):
    _seed_sku(db)
    _manual()
    start = datetime.now() - timedelta(days=2)
    end = datetime.now()

    summary = finance_engine.compute_profit_summary(start_dt=start, end_dt=end, marketplace_filter=None)
    t = summary["totals"]
    assert t["grossRevenue"] == pytest.approx(round(1000.0 / 1.2, 2))
    assert t["trueGrossProfit"] == pytest.approx(round(1000 / 1.2 - 400 / 1.2, 2))
    expected_profit = 1000 / 1.2 - 400 / 1.2 - 50 / 1.2 - 30 / 1.2
    assert t["netProfit"] == pytest.approx(round(expected_profit, 2))
    assert t["commission"] == pytest.approx(round(50.0 / 1.2, 2))
    assert t["cargoTotal"] == pytest.approx(round(30.0 / 1.2, 2))
    assert summary["by_marketplace"]["softhydra"]["netProfit"] == pytest.approx(round(expected_profit, 2))
    assert summary["by_marketplace"]["softhydra"]["orderCount"] == 1
    assert summary["data_quality"]["skus_missing_cost"] == []

    # Pazaryeri sekmeleri (Trendyol / Hepsiburada) manuel kanalları KARIŞTIRMAZ.
    only_ty = finance_engine.compute_profit_summary(start_dt=start, end_dt=end, marketplace_filter="trendyol")
    assert only_ty["totals"]["grossRevenue"] == 0.0
    assert "softhydra" not in only_ty["by_marketplace"]

    months = finance_engine.monthly_profit(datetime.now().replace(day=1, hour=0, minute=0), end)
    this_month = next(m for m in months if m["month"] == datetime.now().strftime("%Y-%m"))
    assert this_month["revenue"] == pytest.approx(round(1000.0 / 1.2, 2))
    assert this_month["trueGrossProfit"] == pytest.approx(round(1000 / 1.2 - 400 / 1.2, 2))
    assert this_month["netProfit"] == pytest.approx(round(expected_profit, 2))
    assert this_month["ordersMissingCargo"] == 0


def test_cancelled_manual_order_is_not_counted(client, db):
    _seed_sku(db)
    _manual(status="Cancelled")
    today = datetime.now().strftime("%Y-%m-%d")

    resp = client.get("/api/daily-sales?full_history=true", headers=auth_headers())
    day = next(d for d in resp.get_json()["daily"] if d["date"] == today)
    assert day["net_amount"] == 0.0
    assert day["cancelled_count"] == 1

    summary = finance_engine.compute_profit_summary(
        start_dt=datetime.now() - timedelta(days=2), end_dt=datetime.now(), marketplace_filter=None)
    assert summary["totals"]["grossRevenue"] == 0.0
    assert summary["totals"]["netProfit"] == 0.0


def test_net_profit_month_period_includes_earlier_days_of_month(client, db):
    """?period=month ayın 1'inden bugüne kadar olan siparişleri de sayar;
    period verilmezse yalnızca bugün."""
    now = datetime.now()
    if now.day == 1:
        pytest.skip("Ayın 1'inde 'ayın önceki günü' yok")
    _seed_sku(db)
    _manual(when=datetime(now.year, now.month, 1, 12, 0))

    today = client.get("/api/today-net-profit", headers=auth_headers()).get_json()
    month = client.get("/api/today-net-profit?period=month", headers=auth_headers()).get_json()
    expected = round(1000 / 1.2 - 400 / 1.2 - 50 / 1.2 - 30 / 1.2, 2)
    assert today["period"] == "today"
    assert today["netProfit"] == 0
    assert month["period"] == "month"
    assert month["netProfit"] == expected
    assert month["netProfitPartial"] == expected


def test_daily_sales_has_marketplace_breakdown(client, db):
    _seed_sku(db)
    _manual()
    today = datetime.now().strftime("%Y-%m-%d")
    resp = client.get("/api/daily-sales?full_history=true", headers=auth_headers())
    day = next(d for d in resp.get_json()["daily"] if d["date"] == today)
    assert day["by_marketplace"] == {"manuel": 1000.0}
    assert sum(day["by_marketplace"].values()) == day["net_amount"]
