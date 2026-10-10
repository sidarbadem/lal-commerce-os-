from datetime import datetime

import pytest

from manual_orders import compute_totals, parse_order_date_ms, select_for_page


def test_date_only_uses_noon():
    ms = parse_order_date_ms("2026-10-10")
    assert datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") == "2026-10-10 12:00"


def test_date_with_time():
    ms = parse_order_date_ms("2026-10-10T14:35")
    assert datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M") == "2026-10-10 14:35"


def test_invalid_date_rejected():
    with pytest.raises(ValueError):
        parse_order_date_ms("10.10.2026")


def test_compute_totals():
    items = [
        {"quantity": 2, "unit_price": 500.0, "unit_cost": 300.0},
        {"quantity": 1, "unit_price": 100.0, "unit_cost": 40.0},
    ]
    assert compute_totals(items, commission=80.0, cargo_cost=50.0) == {
        "saleTotal": 1100.0, "cogsTotal": 640.0, "netProfit": 330.0,
    }


def _o(ts):
    return {"orderDate": ts}


def test_select_first_page_interleaves_newer_and_inside_range():
    orders = [_o(100), _o(90)]
    manual = [_o(200), _o(95), _o(85)]
    out = select_for_page(orders, manual, main_total=4, offset=0, page_size=2, prev_last_date=None)
    assert [o["orderDate"] for o in out] == [200, 100, 95, 90]


def test_select_last_page_takes_older_manual_without_duplicates():
    orders = [_o(80), _o(70)]
    manual = [_o(200), _o(95), _o(85), _o(10)]
    out = select_for_page(orders, manual, main_total=4, offset=2, page_size=2, prev_last_date=90)
    assert [o["orderDate"] for o in out] == [85, 80, 70, 10]
