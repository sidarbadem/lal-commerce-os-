"""Manual Hepsiburada cookie/session probe; never run as an automated test."""

import pytest

pytestmark = pytest.mark.skip(reason="Canlı Hepsiburada oturumu ağ testi; otomatik koşuda atlanır.")


def test_hb_session_live_probe():
    import requests

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (compatible; LAL test probe)",
        "Accept": "application/json",
    })
    page_url = "https://www.hepsiburada.com/"
    session.get(page_url, timeout=10)
    response = session.get(
        "https://user-content-gw-hermes.hepsiburada.com/queryapi/v2/ApprovedUserContents",
        params={"sku": "HBV00000ONEUV", "from": 0, "size": 10},
        headers={"Referer": page_url, "Origin": page_url.rstrip("/")},
        timeout=10,
    )
    assert response.status_code == 200
