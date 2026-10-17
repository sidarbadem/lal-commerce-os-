import database
import monthly_reports

try:
    from conftest import auth_headers
except ImportError:
    from tests.conftest import auth_headers


def _sample_data(period="2026-09"):
    return {
        "period": period,
        "label": monthly_reports.period_label(period),
        "status": "kesin",
        "metrics": {"grossRevenue": 10000.0, "netRevenue": 9500.0, "netProfit": 1200.0,
                    "realNetProfit": 1000.0, "orderCount": 3, "unitCount": 4, "avgBasket": 3333.33},
        "byMarketplace": {},
        "dataQuality": {"ordersMissingCargo": 0, "linesEstimated": 0, "skusMissingCost": []},
        "products": [],
    }


def _table_exists():
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'monthly_reports'"
        ).fetchone()
    return row is not None


def test_page_renders(client):
    r = client.get("/aylik-raporlar", headers=auth_headers())
    assert r.status_code == 200
    assert "Aylık Raporlar" in r.get_data(as_text=True)


def test_list_without_table_is_empty_and_does_not_create_table(client):
    r = client.get("/api/monthly-reports", headers=auth_headers())
    assert r.status_code == 200
    assert r.get_json() == {"items": []}
    r = client.get("/api/monthly-reports/2026-09", headers=auth_headers())
    assert r.status_code == 404
    assert _table_exists() is False


def test_invalid_period_is_rejected(client):
    assert client.get("/api/monthly-reports/2026-13", headers=auth_headers()).status_code == 400
    assert client.get("/api/monthly-reports/abc", headers=auth_headers()).status_code == 400
    assert client.post("/api/monthly-reports/xx/refresh", headers=auth_headers()).status_code == 400


def test_get_and_list_saved_report(client):
    with database.get_connection() as conn:
        monthly_reports.save_report(conn, "2026-09", _sample_data())
        conn.commit()
    r = client.get("/api/monthly-reports/2026-09", headers=auth_headers())
    assert r.status_code == 200
    body = r.get_json()
    assert body["period"] == "2026-09" and body["status"] == "kesin"
    assert body["metrics"]["netProfit"] == 1200.0
    r = client.get("/api/monthly-reports", headers=auth_headers())
    items = r.get_json()["items"]
    assert [i["period"] for i in items] == ["2026-09"]
    assert items[0]["label"] == "Eylül 2026"


def test_refresh_rejects_unfinished_month(client):
    current = __import__("datetime").datetime.now().strftime("%Y-%m")
    r = client.post("/api/monthly-reports/%s/refresh" % current, headers=auth_headers())
    assert r.status_code == 400


def test_refresh_forces_regeneration(client, monkeypatch):
    calls = []

    def fake_generate(period, force=False, notify=False):
        calls.append((period, force, notify))
        return {"period": period, "skipped": False, "status": "kesin"}

    monkeypatch.setattr(monthly_reports, "generate_report", fake_generate)
    r = client.post("/api/monthly-reports/2020-01/refresh", headers=auth_headers())
    assert r.status_code == 200
    assert calls == [("2020-01", True, False)]
