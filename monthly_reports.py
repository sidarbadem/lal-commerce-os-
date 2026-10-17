"""Aylik rapor motoru: rakamlar finance_engine'den, snapshot monthly_reports tablosunda."""

import calendar
import json
from datetime import datetime

import database
import finance_engine
import notifications

TR_MONTHS = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
             "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]

METRIC_KEYS = ["grossRevenue", "returnAmount", "netRevenue", "cogsTotal", "commission",
               "cargoTotal", "stoppage", "platformServiceFee", "overheadTotal", "netProfit"]


def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monthly_reports (
            period TEXT PRIMARY KEY,
            status TEXT NOT NULL,
            data_json TEXT NOT NULL,
            ai_summary TEXT,
            generated_at TEXT,
            finalized_at TEXT
        )
    """)


def parse_period(period):
    y, m = period.split("-")
    return int(y), int(m)


def shift_period(period, delta):
    y, m = parse_period(period)
    idx = y * 12 + (m - 1) + delta
    return "%04d-%02d" % (idx // 12, idx % 12 + 1)


def previous_period(today=None):
    today = today or datetime.now()
    return shift_period(today.strftime("%Y-%m"), -1)


def period_label(period):
    y, m = parse_period(period)
    return "%s %d" % (TR_MONTHS[m - 1], y)


def period_range(period):
    y, m = parse_period(period)
    last = calendar.monthrange(y, m)[1]
    return datetime(y, m, 1), datetime(y, m, last, 23, 59, 59, 999999)


def pct_change(cur, prev):
    if cur is None or prev in (None, 0):
        return None
    return round((cur - prev) / abs(prev) * 100, 1)


def aggregate_products(lines):
    agg = {}
    for ln in lines:
        if ln.get("sku"):
            key = ln["sku"]
        elif ln.get("barcode"):
            key = "barcode:%s" % ln["barcode"]
        else:
            key = "unknown"
        a = agg.setdefault(key, {"sku": ln.get("sku"), "productName": ln.get("productName"),
                                 "quantity": 0, "revenue": 0.0, "profit": 0.0, "profitLines": 0})
        a["quantity"] += ln.get("quantity") or 0
        a["revenue"] += ln.get("grossRevenue") or 0
        if ln.get("profit") is not None:
            a["profit"] += ln["profit"]
            a["profitLines"] += 1
    out = []
    for key, a in agg.items():
        has_profit = a["profitLines"] > 0
        margin = (a["profit"] / a["revenue"]) if (has_profit and a["revenue"]) else None
        out.append({
            "key": key,
            "sku": a["sku"],
            "productName": a["productName"],
            "quantity": a["quantity"],
            "revenue": round(a["revenue"], 2),
            "profit": round(a["profit"], 2) if has_profit else None,
            "margin": round(margin, 4) if margin is not None else None,
        })
    out.sort(key=lambda r: r["revenue"], reverse=True)
    return out


def build_report_data(period):
    start_dt, end_dt = period_range(period)
    summary = finance_engine.compute_profit_summary(start_dt=start_dt, end_dt=end_dt)
    totals = summary["totals"]
    quality = summary["data_quality"]
    lines = summary["lines"]

    orders = set()
    units = 0
    for ln in lines:
        orders.add((ln.get("marketplace"), ln.get("orderNumber")))
        units += ln.get("quantity") or 0

    fixed = finance_engine.get_fixed_expenses_by_month(period, period).get(period, 0.0)

    metrics = {k: round(totals.get(k) or 0, 2) for k in METRIC_KEYS}
    metrics["fixedExpenses"] = round(fixed, 2)
    metrics["realNetProfit"] = round(metrics["netProfit"] - fixed, 2)
    metrics["orderCount"] = len(orders)
    metrics["unitCount"] = units
    metrics["avgBasket"] = round(metrics["grossRevenue"] / len(orders), 2) if orders else 0.0

    missing_cargo = quality.get("orders_missing_cargo_invoice") or 0
    estimated = quality.get("lines_estimated_pending_settlement") or 0
    status = "kesin" if (missing_cargo == 0 and estimated == 0) else "taslak"

    return {
        "period": period,
        "label": period_label(period),
        "status": status,
        "metrics": metrics,
        "byMarketplace": summary.get("by_marketplace"),
        "dataQuality": {
            "ordersMissingCargo": missing_cargo,
            "linesEstimated": estimated,
            "skusMissingCost": quality.get("skus_missing_cost") or [],
        },
        "products": aggregate_products(lines),
    }


def save_report(conn, period, data):
    ensure_schema(conn)
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    finalized = now if data["status"] == "kesin" else None
    conn.execute(
        "INSERT INTO monthly_reports (period, status, data_json, generated_at, finalized_at) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(period) DO UPDATE SET status = excluded.status, "
        "data_json = excluded.data_json, generated_at = excluded.generated_at, "
        "finalized_at = excluded.finalized_at",
        (period, data["status"], json.dumps(data, ensure_ascii=False, default=str), now, finalized),
    )


def get_report(conn, period):
    ensure_schema(conn)
    r = conn.execute("SELECT * FROM monthly_reports WHERE period = ?", (period,)).fetchone()
    if r is None:
        return None
    return {
        "period": r["period"],
        "status": r["status"],
        "data": json.loads(r["data_json"]),
        "aiSummary": r["ai_summary"],
        "generatedAt": r["generated_at"],
        "finalizedAt": r["finalized_at"],
    }


def _compare_metrics(cur, other):
    out = {}
    for k, v in cur.items():
        pv = other.get(k) if other else None
        out[k] = {"value": v, "prev": pv, "pct": pct_change(v, pv)}
    return out


def load_report_view(conn, period):
    cur = get_report(conn, period)
    if cur is None:
        return None
    prev = get_report(conn, shift_period(period, -1))
    yoy = get_report(conn, shift_period(period, -12))
    metrics = cur["data"]["metrics"]

    prev_products = {p["key"]: p for p in prev["data"]["products"]} if prev else {}
    products = []
    for p in cur["data"]["products"]:
        q = dict(p)
        pp = prev_products.get(p["key"])
        q["prevRevenue"] = pp["revenue"] if pp else None
        q["prevQuantity"] = pp["quantity"] if pp else None
        q["revenuePct"] = pct_change(p["revenue"], pp["revenue"]) if pp else None
        products.append(q)

    with_profit = [p for p in products if p["profit"] is not None]
    series = []
    for i in range(11, -1, -1):
        sp = shift_period(period, -i)
        r = get_report(conn, sp)
        if r:
            m = r["data"]["metrics"]
            series.append({"period": sp, "label": period_label(sp), "status": r["status"],
                           "grossRevenue": m.get("grossRevenue"), "netProfit": m.get("netProfit"),
                           "realNetProfit": m.get("realNetProfit")})
    available = [{"period": r["period"], "status": r["status"]} for r in
                 conn.execute("SELECT period, status FROM monthly_reports ORDER BY period DESC").fetchall()]

    return {
        "period": period,
        "label": cur["data"]["label"],
        "status": cur["status"],
        "generatedAt": cur["generatedAt"],
        "finalizedAt": cur["finalizedAt"],
        "aiSummary": cur["aiSummary"],
        "metrics": metrics,
        "byMarketplace": cur["data"].get("byMarketplace"),
        "dataQuality": cur["data"]["dataQuality"],
        "compare": {
            "prev": _compare_metrics(metrics, prev["data"]["metrics"] if prev else None),
            "yoy": _compare_metrics(metrics, yoy["data"]["metrics"] if yoy else None),
        },
        "products": products,
        "topProfit": sorted(with_profit, key=lambda p: p["profit"], reverse=True)[:10],
        "topQuantity": sorted(products, key=lambda p: p["quantity"], reverse=True)[:10],
        "lossMaking": sorted([p for p in with_profit if p["profit"] < 0], key=lambda p: p["profit"])[:10],
        "series": series,
        "availablePeriods": available,
    }


def _notify_ready(conn, period, data):
    notifications.ensure_schema(conn)
    if not notifications._claim(conn, "report", period):
        return False
    m = data["metrics"]
    prev = get_report(conn, shift_period(period, -1))
    pct = pct_change(m.get("netProfit"), prev["data"]["metrics"].get("netProfit")) if prev else None
    parts = ["Ciro %s" % notifications._try(m.get("netRevenue")),
             "Net kâr %s" % notifications._try(m.get("netProfit"))]
    if pct is not None:
        parts.append("önceki aya göre %+.1f%%" % pct)
    body = " · ".join(parts)
    missing = data["dataQuality"]["ordersMissingCargo"]
    if data["status"] == "taslak" and missing:
        body += ". Kargo faturası bekleyen %d sipariş var, rapor taslak." % missing
    notifications._add(conn, "report", "%s raporu hazır" % data["label"], body,
                       {"period": period, "status": data["status"]}, None)
    return True


def generate_report(period, force=False, notify=False):
    with database.get_connection() as conn:
        ensure_schema(conn)
        conn.commit()
        row = conn.execute("SELECT status FROM monthly_reports WHERE period = ?", (period,)).fetchone()
    if row is not None and row["status"] == "kesin" and not force:
        return {"period": period, "skipped": True, "status": "kesin"}
    data = build_report_data(period)
    with database.get_connection() as conn:
        save_report(conn, period, data)
        notified = _notify_ready(conn, period, data) if notify else False
        conn.commit()
    return {"period": period, "skipped": False, "status": data["status"], "notified": notified}


def refresh_drafts(months=3, today=None):
    prev = previous_period(today)
    results = []
    for i in range(months):
        period = shift_period(prev, -i)
        with database.get_connection() as conn:
            ensure_schema(conn)
            conn.commit()
            row = conn.execute("SELECT status FROM monthly_reports WHERE period = ?", (period,)).fetchone()
        if row is None:
            if period == prev:
                results.append(generate_report(period, notify=True))
            continue
        if row["status"] == "taslak":
            results.append(generate_report(period, force=True))
    return results


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if len(args) != 2:
        print("kullanim: python3 monthly_reports.py BASLANGIC(YYYY-MM) BITIS(YYYY-MM)")
        sys.exit(1)
    p = args[0]
    while p <= args[1]:
        print(generate_report(p, force=True))
        p = shift_period(p, 1)
