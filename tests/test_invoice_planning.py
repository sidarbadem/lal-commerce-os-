from datetime import date

from database import get_connection
from tests.conftest import auth_headers


def test_invoice_planning_uses_operating_profit_and_excludes_vat(client, db, monkeypatch):
    monkeypatch.setattr("blueprints.finance_routes.compute_profit_summary", lambda **kwargs: {
        "totals": {"operatingProfit": 1000, "realNetProfit": 100, "taxesAndPremiums": 900,
                   "vatPayableEstimate": 250, "vatAssumed": True}
    })
    headers = auth_headers()
    response = client.post("/api/invoices", headers=headers, json={
        "date": "2026-10-10", "description": "Stok alımı", "amount_ex_vat": 200, "vat_amount": 40,
    })
    assert response.status_code == 201

    response = client.put("/api/invoice-target", headers=headers, json={
        "month": "2026-10", "target_profit": 500,
    })
    assert response.status_code == 200

    response = client.get("/api/invoice-planning?month=2026-10", headers=headers)
    data = response.get_json()
    assert response.status_code == 200
    assert data["operating_profit"] == 1000
    assert data["invoice_total_ex_vat"] == 200
    assert data["remaining_invoice_need"] == 300
    today = date.today()
    assert data["month_complete"] is ((2026, 10) < (today.year, today.month))
    assert data["profit_status"] == "Tahmini (KDV varsayımlı)"
    assert data["invoices"][0]["vat_amount"] == 40

    with get_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM business_invoices").fetchone()[0] == 1
        assert conn.execute("SELECT target_profit FROM invoice_profit_targets WHERE month='2026-10'").fetchone()[0] == 500


def test_invoice_need_never_goes_below_zero(client, db, monkeypatch):
    monkeypatch.setattr("blueprints.finance_routes.compute_profit_summary", lambda **kwargs: {
        "totals": {"operatingProfit": 100, "vatAssumed": False}
    })
    headers = auth_headers()
    client.post("/api/invoices", headers=headers, json={
        "date": "2026-10-10", "description": "Stok", "amount_ex_vat": 250, "vat_amount": 50,
    })
    response = client.get("/api/invoice-planning?month=2026-10", headers=headers)
    assert response.get_json()["remaining_invoice_need"] == 0
