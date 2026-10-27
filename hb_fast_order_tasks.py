"""Hepsiburada: yeni siparisi API'den gorur gormez "Yeni siparis" bildirimi uretir.

Salt okunurdur (yazma izni bayraklarina bagli degildir). Tekillestirme anahtari
notification_seen(kind='order_fast', key=<siparis no>); notifications.detect_and_notify
ayni anahtari kullanir, bu yuzden ayni siparis iki kez bildirilmez.
Ilk calismada mevcut siparisler sessizce baseline'lanir.
"""

import logging

from celery_app import celery_app
from sync_lock import acquire_sync_lock, release_sync_lock

logger = logging.getLogger("trendyol_satis")
_LOCK = "hepsiburada_fast_order_notify"
_BASELINE = "hb_fast_order_baseline_done"


def _line_amount(item):
    price = item.get("totalPrice")
    if isinstance(price, dict):
        price = price.get("amount")
    try:
        return float(price or 0)
    except (TypeError, ValueError):
        return 0.0


def group_orders(items):
    grouped = {}
    for item in items:
        if "cancel" in str(item.get("status") or "").lower():
            continue
        number = str(item.get("orderNumber") or "").strip()
        if number:
            grouped.setdefault(number, []).append(item)
    return grouped


def order_total(items):
    return sum(_line_amount(it) for it in items)


@celery_app.task(name="hb_fast_order_tasks.notify_new_hepsiburada_orders")
def notify_new_hepsiburada_orders():
    import database
    import hb_auto_prepare_tasks as hap
    import notifications
    import sync_core

    cred_error = sync_core._check_hb_credentials()
    if cred_error:
        return {"skipped": True, "reason": cred_error}
    lock = acquire_sync_lock(_LOCK)
    if lock is None:
        return {"skipped": True, "reason": "baska bir kontrol calisiyor"}
    try:
        grouped = group_orders(hap._open_orders(sync_core))
        with database.get_connection() as conn:
            notifications.ensure_schema(conn)
            first = conn.execute(
                "SELECT 1 FROM notification_state WHERE name = ?", (_BASELINE,)
            ).fetchone() is None
            if first:
                for number in grouped:
                    notifications._claim(conn, "order_fast", number)
                conn.execute(
                    "INSERT OR IGNORE INTO notification_state (name, value) VALUES (?, '1')",
                    (_BASELINE,),
                )
                return {"baseline": True, "existing": len(grouped), "created": 0}
            created = 0
            for number, items in grouped.items():
                if not notifications._claim(conn, "order_fast", number):
                    continue
                total = order_total(items)
                notifications._add(
                    conn, "order", "Yeni sipari\u015f",
                    "%s \u00b7 %s \u00b7 %s" % (
                        notifications._mp("hepsiburada"), number, notifications._try(total)),
                    {"orders": [{"marketplace": "hepsiburada", "order_number": number,
                                 "net_amount": total}]},
                    "hepsiburada",
                )
                created += 1
            return {"baseline": False, "created": created}
    finally:
        release_sync_lock(lock, _LOCK)
