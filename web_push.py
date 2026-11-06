"""Telefona/tarayiciya Web Push bildirimi.

Bildirimlerin kaynagi `notifications` tablosudur (siparis, iptal, yorum...).
dispatch_pending() son gonderilen id'den sonrakileri tum abonelere yollar.
Gonderilecek id araligi ONCE sahiplenilir (notification_state.push_last_id),
sonra gonderilir: iki gorev ayni anda calissa da ayni bildirim iki kez gitmez.

Anahtarlar .env'de: VAPID_PUBLIC_KEY, VAPID_PRIVATE_KEY, VAPID_SUBJECT.
"""

import base64
import json
import logging
import os

import database

logger = logging.getLogger(__name__)

PUSH_KINDS = ("order", "order_cancelled", "review")
MAX_INDIVIDUAL = 5
_STATE_KEY = "push_last_id"
_URLS = {
    "order": "/siparisler",
    "order_cancelled": "/siparisler",
    "review": "/yorumlar",
}


def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS push_subscriptions (
            endpoint TEXT PRIMARY KEY,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            user_agent TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            last_ok_at TEXT,
            fail_count INTEGER NOT NULL DEFAULT 0
        )
    """)


def config():
    pub = os.getenv("VAPID_PUBLIC_KEY", "").strip()
    priv = os.getenv("VAPID_PRIVATE_KEY", "").strip()
    sub = os.getenv("VAPID_SUBJECT", "").strip() or "mailto:push@lal-commerce.local"
    return {"public_key": pub, "private_key": priv, "subject": sub, "enabled": bool(pub and priv)}


def generate_vapid_keys():
    """(public_b64url, private_b64url) uretir; .env'e yazmak icin."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    key = ec.generate_private_key(ec.SECP256R1())
    raw_priv = key.private_numbers().private_value.to_bytes(32, "big")
    raw_pub = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    enc = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    return enc(raw_pub), enc(raw_priv)


def subscribe(sub, user_agent=None):
    endpoint = (sub or {}).get("endpoint")
    keys = (sub or {}).get("keys") or {}
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        raise ValueError("gecersiz abonelik")
    if not str(endpoint).startswith("https://"):
        raise ValueError("gecersiz endpoint")
    with database.get_connection() as conn:
        ensure_schema(conn)
        conn.execute(
            "INSERT INTO push_subscriptions (endpoint, p256dh, auth, user_agent) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth, "
            "user_agent = excluded.user_agent, fail_count = 0",
            (endpoint, keys["p256dh"], keys["auth"], (user_agent or "")[:300]),
        )


def unsubscribe(endpoint):
    with database.get_connection() as conn:
        ensure_schema(conn)
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


def subscription_count():
    with database.get_connection() as conn:
        ensure_schema(conn)
        return conn.execute("SELECT COUNT(*) FROM push_subscriptions").fetchone()[0]


def _send_one(row, payload, cfg):
    """True: gonderildi, False: abonelik olu (silindi), None: gecici hata."""
    from pywebpush import WebPushException, webpush

    try:
        webpush(
            subscription_info={"endpoint": row["endpoint"],
                               "keys": {"p256dh": row["p256dh"], "auth": row["auth"]}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=cfg["private_key"],
            vapid_claims={"sub": cfg["subject"]},
            ttl=6 * 3600,
            timeout=10,
        )
        return True
    except WebPushException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status in (404, 410):
            return False
        logger.warning("[push] gonderilemedi (%s): %s", status, exc)
        return None
    except Exception as exc:  # ag hatasi vb.
        logger.warning("[push] gonderilemedi: %s", exc)
        return None


def send_to_all(payload):
    cfg = config()
    if not cfg["enabled"]:
        return {"sent": 0, "removed": 0, "failed": 0, "disabled": True}
    with database.get_connection() as conn:
        ensure_schema(conn)
        rows = conn.execute(
            "SELECT endpoint, p256dh, auth FROM push_subscriptions"
        ).fetchall()
    stats = {"sent": 0, "removed": 0, "failed": 0}
    for row in rows:
        ok = _send_one(row, payload, cfg)
        with database.get_connection() as conn:
            if ok:
                stats["sent"] += 1
                conn.execute(
                    "UPDATE push_subscriptions SET last_ok_at = datetime('now', 'localtime'), "
                    "fail_count = 0 WHERE endpoint = ?", (row["endpoint"],))
            elif ok is False:
                stats["removed"] += 1
                conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (row["endpoint"],))
            else:
                stats["failed"] += 1
                conn.execute(
                    "UPDATE push_subscriptions SET fail_count = fail_count + 1 WHERE endpoint = ?",
                    (row["endpoint"],))
                conn.execute("DELETE FROM push_subscriptions WHERE fail_count >= 20")
    return stats


def _payload(n):
    detail = {}
    try:
        detail = json.loads(n["detail_json"]) if n["detail_json"] else {}
    except ValueError:
        pass
    p = {
        "title": n["title"],
        "body": n["body"] or "",
        "url": _URLS.get(n["kind"], "/panel"),
        "tag": "lal-%s-%s" % (n["kind"], n["id"]),
        "kind": n["kind"],
    }
    revs = detail.get("reviews") or []
    if n["kind"] == "review" and len(revs) == 1 and revs[0].get("image_url"):
        p["image"] = revs[0]["image_url"]
    return p


def _claim_pending(conn):
    ensure_schema(conn)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notification_state (name TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute("BEGIN IMMEDIATE")
    max_id = conn.execute("SELECT COALESCE(MAX(id), 0) FROM notifications").fetchone()[0]
    row = conn.execute(
        "SELECT value FROM notification_state WHERE name = ?", (_STATE_KEY,)
    ).fetchone()
    if row is None:
        # Ilk calisma: gecmisi telefona yagdirma.
        conn.execute(
            "INSERT INTO notification_state (name, value) VALUES (?, ?)", (_STATE_KEY, str(max_id))
        )
        conn.commit()
        return None
    last = int(row["value"] or 0)
    rows = conn.execute(
        "SELECT id, kind, title, body, detail_json FROM notifications "
        "WHERE id > ? AND id <= ? AND kind IN (%s) ORDER BY id" % ",".join("?" * len(PUSH_KINDS)),
        (last, max_id) + PUSH_KINDS,
    ).fetchall()
    if max_id != last:
        conn.execute(
            "UPDATE notification_state SET value = ? WHERE name = ?", (str(max_id), _STATE_KEY)
        )
    conn.commit()
    return rows


def dispatch_pending():
    if not config()["enabled"]:
        return {"disabled": True}
    import notifications

    with database.get_connection() as conn:
        notifications.ensure_schema(conn)
        conn.commit()
        rows = _claim_pending(conn)
    if rows is None:
        return {"baseline": True}
    if not rows:
        return {"pushed": 0}
    if len(rows) <= MAX_INDIVIDUAL:
        payloads = [_payload(r) for r in rows]
    else:
        orders = sum(1 for r in rows if r["kind"] == "order")
        payloads = [{
            "title": "%d yeni bildirim" % len(rows),
            "body": ("%d yeni sipariş · " % orders if orders else "") + "Ayrıntılar için dokunun.",
            "url": "/siparisler" if orders else "/panel",
            "tag": "lal-batch-%s" % rows[-1]["id"],
            "kind": "batch",
        }]
    total = {"pushed": len(payloads), "sent": 0, "removed": 0, "failed": 0}
    for p in payloads:
        s = send_to_all(p)
        for k in ("sent", "removed", "failed"):
            total[k] += s.get(k, 0)
    return total
