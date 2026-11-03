"""Hepsiburada orders: move new eligible orders into package preparation.

The rollout is scoped by HEPSIBURADA_AUTO_PREPARE_ENABLED and the existing
LAL_WRITES_ENABLED guard. Existing open orders are baselined on first run and
are not submitted retroactively.
"""

import logging
import os

from celery_app import celery_app
from sync_lock import acquire_sync_lock, release_sync_lock

logger = logging.getLogger("trendyol_satis")
_LOCK = "hepsiburada_auto_prepare"


def _open_orders(core):
    items = []
    offset, limit = 0, 100
    for _ in range(30):
        data = core.hepsiburada_get(core.HB_ORDERS_PATH, {"offset": offset, "limit": limit}) or {}
        page = data.get("items") or []
        items.extend(page)
        offset += limit
        if offset >= int(data.get("totalCount") or 0) or not page:
            break
    return items


def _groups(items):
    grouped = {}
    for item in items:
        if item.get("packageNumber") or (item.get("status") or "").lower() != "open":
            continue
        number = str(item.get("orderNumber") or "").strip()
        if number:
            grouped.setdefault(number, []).append(item)
    return grouped


def _baseline(conn, order_numbers):
    import notifications
    notifications.ensure_schema(conn)
    baseline = conn.execute(
        "SELECT 1 FROM notification_state WHERE name = 'hb_auto_prepare_baseline_done'"
    ).fetchone()
    if baseline:
        return False
    for number in order_numbers:
        notifications._claim(conn, "hb_auto_prepare", number)
    conn.execute(
        "INSERT OR IGNORE INTO notification_state (name, value) VALUES (?, '1')",
        ("hb_auto_prepare_baseline_done",),
    )
    return True


def _already_seen(conn, order_number):
    return conn.execute(
        "SELECT 1 FROM notification_seen WHERE kind = 'hb_auto_prepare' AND key = ?",
        (order_number,),
    ).fetchone() is not None


def _mark_prepared(order_number, items, req, status, response):
    import json
    import database
    import notifications
    with database.get_connection() as conn:
        notifications.ensure_schema(conn)
        notifications._claim(conn, "hb_auto_prepare", order_number)
        first = items[0]
        notifications._add(
            conn,
            "order_prepared",
            "Hepsiburada siparişi hazırlığa alındı",
            "%s · %d ürün kalemi" % (order_number, len(items)),
            {"orders": [{
                "marketplace": "hepsiburada",
                "order_number": order_number,
                "status": "Hazırlanıyor",
                "net_amount": (first.get("totalPrice") or {}).get("amount")
                    if isinstance(first.get("totalPrice"), dict)
                    else first.get("totalPrice"),
            }]},
            "hepsiburada",
        )
        # Task result and response are also recorded in the existing operation log.
        conn.execute(
            "INSERT INTO paketlenecekler_islemleri "
            "(marketplace, action, order_number, target_id, request_json, dry_run, "
            "http_status, response_text, ok) VALUES (?, ?, ?, ?, ?, 0, ?, ?, 1)",
            (
                "hepsiburada", "auto_pack", order_number,
                ",".join(str(it.get("id")) for it in items),
                json.dumps(req, ensure_ascii=False),
                status, str(response)[:2000],
            ),
        )


@celery_app.task(name="hb_auto_prepare_tasks.prepare_new_hepsiburada_orders")
def prepare_new_hepsiburada_orders():
    if os.getenv("HEPSIBURADA_AUTO_PREPARE_ENABLED", "0").strip() != "1":
        return {"skipped": True, "reason": "otomatik hazırlama kapalı"}
    if os.getenv("LAL_WRITES_ENABLED", "0").strip() != "1":
        return {"skipped": True, "reason": "pazaryeri yazma izni kapalı"}

    import database
    import hb_write_client as hbw
    import notifications
    import sync_core

    cred_error = sync_core._check_hb_credentials()
    if cred_error:
        return {"skipped": True, "reason": cred_error}
    lock = acquire_sync_lock(_LOCK)
    if lock is None:
        return {"skipped": True, "reason": "başka bir hazırlama çalışıyor"}
    try:
        grouped = _groups(_open_orders(sync_core))
        with database.get_connection() as conn:
            notifications.ensure_schema(conn)
            if _baseline(conn, grouped):
                return {"baseline": True, "existing_open_orders": len(grouped), "prepared": 0}
            known = {number for number in grouped if _already_seen(conn, number)}

        prepared, skipped, errors = [], [], []
        for number, items in grouped.items():
            if number in known:
                continue
            if any(item.get("canCreatePackage") is False for item in items):
                skipped.append(number)
                continue
            lines = []
            for item in items:
                line_id = item.get("id")
                if line_id in (None, ""):
                    lines = []
                    break
                try:
                    qty = int(item.get("quantity") or 1)
                except (TypeError, ValueError):
                    qty = 0
                lines.append({"id": line_id, "quantity": qty})
            if not lines:
                errors.append({"order_number": number, "error": "sipariş kalemi veya adet eksik"})
                continue
            try:
                req = hbw.build_requests("pack", sync_core.HB_MERCHANT_ID, {"lines": lines})[0]
                status, response = hbw.send(sync_core, req)
            except Exception as exc:
                errors.append({"order_number": number, "error": str(exc)[:300]})
                continue
            if 200 <= status < 300:
                _mark_prepared(number, items, req, status, response)
                prepared.append(number)
            else:
                errors.append({"order_number": number, "status": status, "error": response[:300]})

        return {"baseline": False, "prepared": len(prepared), "order_numbers": prepared,
                "skipped_not_eligible": skipped, "errors": errors}
    finally:
        release_sync_lock(lock, _LOCK)
