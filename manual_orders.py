"""Manual orders for channels without API access (softhydra.com, n11, Amazon).

Stored in their own tables so Trendyol/Hepsiburada sync and finance_engine are untouched.
Net profit = sale total - cost of goods (cost incl. VAT, snapshotted at entry) - commission - cargo.
"""
import sqlite3
from datetime import datetime

from database import get_connection, list_product_images
from finance_engine import NEVER_FULFILLED_STATUSES

MANUAL_CHANNELS = {"softhydra": "softhydra.com", "n11": "n11", "amazon": "Amazon"}
MANUAL_STATUSES = ("Delivered", "Shipped", "Created", "Cancelled")


def parse_order_date_ms(value):
    s = str(value or "").strip()
    for fmt in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s, fmt)
        except ValueError:
            continue
        if fmt == "%Y-%m-%d":
            dt = dt.replace(hour=12)
        return int(dt.timestamp() * 1000)
    raise ValueError("order_date must be YYYY-MM-DD or YYYY-MM-DDTHH:MM")


def _num(value, field, default=None, minimum=0.0):
    if value is None or value == "":
        if default is None:
            raise ValueError(f"{field} is required")
        return float(default)
    try:
        if isinstance(value, str):
            value = value.strip().replace(",", ".")
        n = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field} must be a number")
    if n < minimum:
        raise ValueError(f"{field} must be >= {minimum:g}")
    return n


def compute_totals(items, commission, cargo_cost):
    sale = sum(i["quantity"] * i["unit_price"] for i in items)
    cogs = sum(i["quantity"] * i["unit_cost"] for i in items)
    net = sale - cogs - commission - cargo_cost
    return {"saleTotal": round(sale, 2), "cogsTotal": round(cogs, 2), "netProfit": round(net, 2)}


def _validate(payload, conn, cost_hint=None):
    if not isinstance(payload, dict):
        raise ValueError("JSON body required")
    channel = str(payload.get("channel") or "").strip().lower()
    if channel not in MANUAL_CHANNELS:
        raise ValueError("channel must be one of: " + ", ".join(MANUAL_CHANNELS))
    status = str(payload.get("status") or "Delivered").strip()
    if status not in MANUAL_STATUSES:
        raise ValueError("status must be one of: " + ", ".join(MANUAL_STATUSES))
    order_date = parse_order_date_ms(payload.get("order_date"))
    raw_items = payload.get("items")
    if not isinstance(raw_items, list) or not raw_items:
        raise ValueError("at least one item is required")
    import cost_history
    history = cost_history.load_history_safe(conn)
    items = []
    for idx, it in enumerate(raw_items, start=1):
        if not isinstance(it, dict):
            raise ValueError(f"item {idx}: invalid")
        sku = str(it.get("sku") or "").strip()
        if not sku:
            raise ValueError(f"item {idx}: sku is required")
        pc = conn.execute(
            "SELECT sku, product_name, cost_incl_vat, sale_price_incl_vat FROM product_costs WHERE sku = ?",
            (sku,),
        ).fetchone()
        if pc is None:
            raise ValueError(f"item {idx}: unknown sku {sku}")
        qty = int(_num(it.get("quantity"), f"item {idx}: quantity", default=1, minimum=1))
        unit_price = _num(it.get("unit_price"), f"item {idx}: unit_price", default=pc["sale_price_incl_vat"])
        unit_cost = (cost_hint or {}).get(sku)
        if unit_cost is None:
            unit_cost = cost_history.cost_at(
                history, sku, order_date, fallback=pc["cost_incl_vat"]
            )
        if unit_cost is None:
            raise ValueError(f"item {idx}: {sku} has no cost defined")
        items.append({
            "sku": sku,
            "product_name": pc["product_name"],
            "quantity": qty,
            "unit_price": unit_price,
            "unit_cost": float(unit_cost),
        })
    sale_total = sum(i["quantity"] * i["unit_price"] for i in items)
    if payload.get("commission") not in (None, ""):
        commission = _num(payload.get("commission"), "commission")
    elif payload.get("commission_rate") not in (None, ""):
        commission = round(sale_total * _num(payload.get("commission_rate"), "commission_rate") / 100.0, 2)
    else:
        commission = 0.0
    cargo_cost = _num(payload.get("cargo_cost"), "cargo_cost", default=0.0)
    return {
        "channel": channel,
        "status": status,
        "order_date": order_date,
        "order_ref": str(payload.get("order_ref") or "").strip() or None,
        "customer": str(payload.get("customer") or "").strip() or None,
        "notes": str(payload.get("notes") or "").strip() or None,
        "commission": commission,
        "cargo_cost": cargo_cost,
        "items": items,
    }


def _write_items(conn, order_id, items):
    for i in items:
        conn.execute(
            """INSERT INTO manuel_siparis_kalemleri
               (order_id, sku, product_name, quantity, unit_price, unit_cost)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (order_id, i["sku"], i["product_name"], i["quantity"], i["unit_price"], i["unit_cost"]),
        )


def create_manual_order(payload):
    with get_connection() as conn:
        d = _validate(payload, conn)
        cur = conn.execute(
            """INSERT INTO manuel_siparisler
               (channel, order_ref, order_date, customer, status, commission, cargo_cost, notes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (d["channel"], d["order_ref"], d["order_date"], d["customer"], d["status"],
             d["commission"], d["cargo_cost"], d["notes"]),
        )
        order_id = cur.lastrowid
        _write_items(conn, order_id, d["items"])
        conn.commit()
    return order_id


def update_manual_order(order_id, payload):
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM manuel_siparisler WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise LookupError("manual order not found")
        hints = {
            r["sku"]: r["unit_cost"]
            for r in conn.execute(
                "SELECT sku, unit_cost FROM manuel_siparis_kalemleri WHERE order_id = ?", (order_id,)
            ).fetchall()
        }
        d = _validate(payload, conn, cost_hint=hints)
        conn.execute(
            """UPDATE manuel_siparisler
               SET channel = ?, order_ref = ?, order_date = ?, customer = ?, status = ?,
                   commission = ?, cargo_cost = ?, notes = ?, updated_at = datetime('now','localtime')
               WHERE id = ?""",
            (d["channel"], d["order_ref"], d["order_date"], d["customer"], d["status"],
             d["commission"], d["cargo_cost"], d["notes"], order_id),
        )
        conn.execute("DELETE FROM manuel_siparis_kalemleri WHERE order_id = ?", (order_id,))
        _write_items(conn, order_id, d["items"])
        conn.commit()


def delete_manual_order(order_id):
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM manuel_siparisler WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise LookupError("manual order not found")
        conn.execute("DELETE FROM manuel_siparis_kalemleri WHERE order_id = ?", (order_id,))
        conn.execute("DELETE FROM manuel_siparisler WHERE id = ?", (order_id,))
        conn.commit()


def _build_listing(row, items, image_map):
    sale = sum((i["quantity"] or 0) * (i["unit_price"] or 0) for i in items)
    cogs = sum((i["quantity"] or 0) * (i["unit_cost"] or 0) for i in items)
    commission = row["commission"] or 0.0
    cargo = row["cargo_cost"] or 0.0
    cancelled = row["status"] in NEVER_FULFILLED_STATUSES
    net = 0.0 if cancelled else round(sale - cogs - commission - cargo, 2)
    return {
        "shipmentPackageId": None,
        "manualId": row["id"],
        "isManual": True,
        "orderNumber": row["order_ref"] or f"M-{row['id']}",
        "orderRef": row["order_ref"],
        "orderDate": row["order_date"],
        "status": row["status"],
        "customer": row["customer"],
        "cargoProvider": None,
        "grossAmount": round(sale, 2),
        "discountAmount": 0.0,
        "netAmount": round(sale, 2),
        "marketplace": row["channel"],
        "lines": [
            {
                "barcode": None,
                "merchantSku": i["sku"],
                "productName": i["product_name"],
                "quantity": i["quantity"],
                "lineUnitPrice": i["unit_price"],
                "commissionRate": None,
                "imageUrl": image_map.get(i["sku"]),
            }
            for i in items
        ],
        "items": [
            {
                "sku": i["sku"],
                "productName": i["product_name"],
                "quantity": i["quantity"],
                "unitPrice": i["unit_price"],
                "unitCost": i["unit_cost"],
            }
            for i in items
        ],
        "saleTotal": round(sale, 2),
        "cogsTotal": round(cogs, 2),
        "commission": commission,
        "cargoCost": cargo,
        "notes": row["notes"],
        "netProfit": net,
        "profitEstimated": False,
        "cargoEstimated": False,
    }


def fetch_manual_orders(conn, start_ms, end_ms, status=None, q=None, channel=None):
    where = ["order_date BETWEEN ? AND ?"]
    params = [start_ms, end_ms]
    if status:
        where.append("status = ?")
        params.append(status)
    if q:
        where.append("(order_ref LIKE ? OR customer LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%"])
    if channel:
        where.append("channel = ?")
        params.append(channel)
    where_sql = " AND ".join(where)
    rows = conn.execute(
        f"SELECT * FROM manuel_siparisler WHERE {where_sql} ORDER BY order_date DESC, id DESC", params
    ).fetchall()
    item_rows = conn.execute(
        f"""SELECT * FROM manuel_siparis_kalemleri
            WHERE order_id IN (SELECT id FROM manuel_siparisler WHERE {where_sql}) ORDER BY id""",
        params,
    ).fetchall()
    by_order = {}
    for r in item_rows:
        by_order.setdefault(r["order_id"], []).append(r)
    image_map = list_product_images()
    return [_build_listing(r, by_order.get(r["id"], []), image_map) for r in rows]


def get_manual_order(order_id):
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM manuel_siparisler WHERE id = ?", (order_id,)).fetchone()
        if row is None:
            raise LookupError("manual order not found")
        items = conn.execute(
            "SELECT * FROM manuel_siparis_kalemleri WHERE order_id = ? ORDER BY id", (order_id,)
        ).fetchall()
        return _build_listing(row, items, list_product_images())


def select_for_page(orders, manual, main_total, offset, page_size, prev_last_date):
    if offset > 0 and prev_last_date is None:
        return orders
    hi = None if offset == 0 else prev_last_date
    lo = None if offset + page_size >= main_total else orders[-1]["orderDate"]
    picked = [
        m for m in manual
        if (hi is None or m["orderDate"] < hi) and (lo is None or m["orderDate"] >= lo)
    ]
    return sorted(orders + picked, key=lambda o: o["orderDate"], reverse=True)


def merge_into_listing(orders, main_total, *, where_sql, params, offset, page_size,
                       start_ms, end_ms, status, q, marketplace):
    if marketplace in ("trendyol", "hepsiburada"):
        return orders, main_total
    channel = marketplace if marketplace in MANUAL_CHANNELS else None
    try:
        with get_connection() as conn:
            manual = fetch_manual_orders(conn, start_ms, end_ms, status=status, q=q, channel=channel)
            if channel:
                return manual[offset:offset + page_size], len(manual)
            prev_last = None
            if offset > 0:
                row = conn.execute(
                    f"SELECT order_date FROM orders WHERE {where_sql} ORDER BY order_date DESC LIMIT 1 OFFSET ?",
                    [*params, offset - 1],
                ).fetchone()
                prev_last = row["order_date"] if row else None
    except Exception:
        return orders, main_total
    merged = select_for_page(orders, manual, main_total, offset, page_size, prev_last)
    return merged, main_total + len(manual)


def fetch_manual_daily_rows(conn, start_ms, end_ms):
    """/api/daily-sales için: aralıktaki TÜM manuel siparişler (iptaller dahil;
    daily-sales iptali kendisi ayıklar). Her sipariş için satış toplamı, adet ve
    komisyon hesaplanmış döner. Tablo yoksa (eski DB) boş liste."""
    try:
        rows = conn.execute(
            "SELECT * FROM manuel_siparisler WHERE order_date BETWEEN ? AND ? ORDER BY order_date DESC, id DESC",
            (start_ms, end_ms),
        ).fetchall()
        item_rows = conn.execute(
            """SELECT order_id, SUM(quantity * unit_price) AS sale, SUM(quantity) AS qty
               FROM manuel_siparis_kalemleri
               WHERE order_id IN (SELECT id FROM manuel_siparisler WHERE order_date BETWEEN ? AND ?)
               GROUP BY order_id""",
            (start_ms, end_ms),
        ).fetchall()
    except sqlite3.OperationalError:
        return []
    agg = {r["order_id"]: r for r in item_rows}
    out = []
    for r in rows:
        a = agg.get(r["id"])
        out.append({
            "id": r["id"],
            "orderNumber": r["order_ref"] or f"M-{r['id']}",
            "channel": r["channel"],
            "orderDate": r["order_date"],
            "status": r["status"],
            "customer": r["customer"],
            "sale": round((a["sale"] if a else 0) or 0, 2),
            "qty": int((a["qty"] if a else 0) or 0),
            "commission": r["commission"] or 0.0,
        })
    return out


def count_manual_orders(conn, start_ms, end_ms):
    """[start_ms, end_ms) aralığındaki manuel sipariş sayısı (tüm statüler —
    /api/today-order-count ham operasyonel sayaç olduğu için iptaller dahil)."""
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM manuel_siparisler WHERE order_date >= ? AND order_date < ?",
            (start_ms, end_ms),
        ).fetchone()
    except sqlite3.OperationalError:
        return 0
    return row["c"] if row else 0
