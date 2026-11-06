import json

import pytest

import database
import notifications
import web_push


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", str(tmp_path / "push_test.db"))
    database.init_db()
    pub, priv = web_push.generate_vapid_keys()
    monkeypatch.setenv("VAPID_PUBLIC_KEY", pub)
    monkeypatch.setenv("VAPID_PRIVATE_KEY", priv)
    sent = []

    def fake_send(row, payload, cfg):
        sent.append((row["endpoint"], payload))
        return False if "dead" in row["endpoint"] else True

    monkeypatch.setattr(web_push, "_send_one", fake_send)
    return sent


def _note(kind, title="t", detail=None):
    with database.get_connection() as conn:
        notifications.ensure_schema(conn)
        notifications._add(conn, kind, title, "b", detail or {}, None)


def _sub(endpoint):
    web_push.subscribe({"endpoint": endpoint, "keys": {"p256dh": "p", "auth": "a"}})


def test_vapid_keys_are_valid_b64url():
    Vapid = pytest.importorskip("py_vapid").Vapid
    pub, priv = web_push.generate_vapid_keys()
    assert Vapid.from_string(priv).private_key is not None
    assert len(pub) == 87  # 65 bayt uncompressed nokta


def test_first_dispatch_is_baseline_then_sends_only_new(db):
    _sub("https://push.example/a")
    _note("order", "eski")
    assert web_push.dispatch_pending() == {"baseline": True}
    assert db == []
    _note("order", "Yeni sipariş")
    _note("profit_final", "push'a gitmez")
    _note("review", "Yeni yorum", {"reviews": [{"image_url": "https://img/x.jpg"}]})
    r = web_push.dispatch_pending()
    assert r["pushed"] == 2 and r["sent"] == 2
    titles = [p["title"] for _, p in db]
    assert titles == ["Yeni sipariş", "Yeni yorum"]
    assert db[1][1]["image"] == "https://img/x.jpg"
    assert db[0][1]["url"] == "/siparisler"
    # Ayni bildirim ikinci kez gitmez
    assert web_push.dispatch_pending() == {"pushed": 0}


def test_many_notifications_are_batched(db):
    _sub("https://push.example/a")
    web_push.dispatch_pending()
    for _ in range(7):
        _note("order")
    r = web_push.dispatch_pending()
    assert r["pushed"] == 1
    assert db[0][1]["title"] == "7 yeni bildirim"


def test_dead_subscription_is_removed(db):
    _sub("https://push.example/dead")
    _sub("https://push.example/ok")
    stats = web_push.send_to_all({"title": "x"})
    assert stats["sent"] == 1 and stats["removed"] == 1
    assert web_push.subscription_count() == 1


def test_subscribe_rejects_bad_input(db):
    with pytest.raises(ValueError):
        web_push.subscribe({"endpoint": "http://insecure", "keys": {"p256dh": "p", "auth": "a"}})
    with pytest.raises(ValueError):
        web_push.subscribe({"endpoint": "https://x"})


def test_disabled_without_keys(db, monkeypatch):
    monkeypatch.delenv("VAPID_PRIVATE_KEY")
    assert web_push.dispatch_pending() == {"disabled": True}


def test_routes(db, monkeypatch):
    import app as app_module
    client = app_module.app.test_client()
    with client.session_transaction() as s:
        s["lal_auth"] = True
    assert client.get("/api/push/config").get_json()["enabled"] is True
    r = client.post("/api/push/subscribe", json={"subscription": {"endpoint": "https://push.example/z", "keys": {"p256dh": "p", "auth": "a"}}})
    assert r.status_code == 200
    assert client.post("/api/push/test").get_json()["sent"] == 1
    sw = client.get("/sw.js")
    assert sw.status_code == 200 and sw.headers["Service-Worker-Allowed"] == "/"
    assert client.post("/api/push/unsubscribe", json={"endpoint": "https://push.example/z"}).get_json()["ok"]
