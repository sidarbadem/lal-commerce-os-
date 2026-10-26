from datetime import datetime

from database import get_connection, upsert_settlements
from tests.conftest import auth_headers


def test_return_condition_api_lists_and_saves_status(client, db):
    now_ms = int(datetime.now().timestamp() * 1000)
    upsert_settlements([{
        "id": "api-return-1", "marketplace": "trendyol", "transaction_date": now_ms,
        "barcode": "SKU-API-RET", "transaction_type": "Return", "raw_transaction_type": "İade",
        "receipt_id": None, "description": "API iade testi", "debt": 100.0, "credit": 0.0,
        "payment_period": None, "commission_rate": None, "commission_amount": None,
        "seller_revenue": None, "order_number": "API-RET-1", "payment_order_id": None,
        "payment_date": None, "shipment_package_id": 8123,
    }])
    month = datetime.fromtimestamp(now_ms / 1000).strftime("%Y-%m")
    headers = auth_headers()

    response = client.get(f"/api/returns?month={month}", headers=headers)
    assert response.status_code == 200
    assert response.get_json()["items"][0]["condition"] == "sellable"
    assert response.get_json()["items"][0]["match_status"] == "Kontrol gerekli"

    response = client.post("/api/returns", headers=headers, json={
        "marketplace": "trendyol", "settlement_id": "api-return-1", "condition": "lost",
    })
    assert response.status_code == 200
    with get_connection() as conn:
        saved = conn.execute("select condition from return_conditions where marketplace='trendyol' and settlement_id='api-return-1'").fetchone()
    assert saved["condition"] == "lost"

    response = client.get(f"/api/returns?month={month}", headers=headers)
    assert response.get_json()["items"][0]["condition"] == "lost"
