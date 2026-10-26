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
               "cargoTotal", "stoppage", "platformServiceFee", "overheadTotal", "netProfit",
               "serviceFee", "cogsReversalTotal", "grossProfit", "operatingProfit",
               "realNetProfit", "businessExpenses", "taxesAndPremiums", "unallocatedExpenses",
               "vatPayableEstimate", "withholdingForOffset", "vatWithholdingNotOffset"]


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
    summary = finance_engine.compute_profit_summary(start_dt=start_dt, end_dt=end_dt, include_period_expenses=True)
    totals = summary["totals"]
    quality = summary["data_quality"]
    lines = summary["lines"]

    orders = set()
    units = 0
    for ln in lines:
        orders.add((ln.get("marketplace"), ln.get("orderNumber")))
        units += ln.get("quantity") or 0

    metrics = {k: round(totals.get(k) or 0, 2) for k in METRIC_KEYS}
    metrics["fixedExpenses"] = round(metrics["businessExpenses"] + metrics["taxesAndPremiums"], 2)
    metrics["orderCount"] = len(orders)
    metrics["unitCount"] = units
    metrics["avgBasket"] = round(metrics["grossRevenue"] / len(orders), 2) if orders else 0.0

    missing_cargo = quality.get("orders_missing_cargo_invoice") or 0
    estimated = quality.get("lines_estimated_pending_settlement") or 0
    vat_assumed = bool(totals.get("vatAssumed"))
    missing_costs = quality.get("skus_missing_cost") or []
    status = "kesin" if (missing_cargo == 0 and estimated == 0 and not missing_costs and not vat_assumed) else "taslak"
    status_label = ("Tahmini (KDV varsayımlı)" if vat_assumed else
                    (f"Tahmini ({missing_cargo + len(missing_costs) + estimated} eksik)" if status != "kesin" else "Kesin"))
    products = aggregate_products(lines)
    unallocated = round(totals.get("unallocatedExpenses") or 0, 2)
    if unallocated:
        products.append({"key": "__unallocated__", "sku": None, "productName": "Dağıtılmamış",
                         "quantity": 0, "revenue": 0.0, "profit": round(-unallocated, 2), "margin": None})

    return {
        "period": period,
        "label": period_label(period),
        "status": status,
        "statusLabel": status_label,
        "metrics": metrics,
        "byMarketplace": summary.get("by_marketplace"),
        "dataQuality": {
            "ordersMissingCargo": missing_cargo,
            "linesEstimated": estimated,
            "skusMissingCost": quality.get("skus_missing_cost") or [],
            "vatAssumed": vat_assumed,
            "vatAssumptionCount": totals.get("vatAssumptionCount", 0),
            "missingCount": missing_cargo + len(missing_costs),
            "expenseDuplicates": totals.get("expenseDuplicates", []),
        },
        "products": products,
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


def _tl(v):
    if v is None:
        return "-"
    s = "{:,.0f}".format(abs(v)).replace(",", ".")
    return ("-" if v < 0 else "") + "\u20ba" + s


def _num1(v):
    return "{:.1f}".format(v).replace(".", ",")


def _delta_text(entry):
    if not entry or entry.get("prev") is None or entry.get("value") is None:
        return None
    diff = entry["value"] - entry["prev"]
    if abs(diff) < 0.5:
        return "önceki ayla aynı seviyede"
    word = "arttı" if diff > 0 else "azaldı"
    if entry["prev"] > 0:
        return "önceki aya göre %%%s %s" % (_num1(abs(diff) / entry["prev"] * 100), word)
    return "önceki aya göre %s %s" % (_tl(abs(diff)), word)


_MP_NAMES = {"trendyol": "Trendyol", "hepsiburada": "Hepsiburada"}


def _marketplace_items(view):
    mp = view.get("byMarketplace")
    if isinstance(mp, dict):
        return list(mp.items())
    if isinstance(mp, list):
        return [(x.get("marketplace"), x) for x in mp if isinstance(x, dict)]
    return []


def build_notes(view):
    notes = []
    m = view.get("metrics") or {}
    prev = (view.get("compare") or {}).get("prev") or {}
    label = view.get("label") or view.get("period") or ""

    gross = m.get("grossRevenue")
    net_rev = m.get("netRevenue")
    net = m.get("netProfit")
    if net is not None:
        text = "%s: net ciro %s, net kâr %s oldu" % (label, _tl(net_rev), _tl(net))
        d = _delta_text(prev.get("netProfit"))
        if d:
            text += "; net kâr " + d
        notes.append(text + ".")

    real = m.get("realNetProfit")
    fixed = m.get("fixedExpenses")
    if real is not None and fixed is not None:
        if real >= 0:
            notes.append("Sabit giderler (%s) düşüldükten sonra gerçek net kâr %s kaldı." % (_tl(fixed), _tl(real)))
        else:
            notes.append("Sabit giderler (%s) düşüldükten sonra ay %s zararla kapandı." % (_tl(fixed), _tl(abs(real))))

    if net is not None and gross:
        notes.append("Net kâr marjı (brüt ciroya göre): %%%s." % _num1(net / gross * 100))

    ret = m.get("returnAmount")
    if ret and gross:
        notes.append("İadeler toplam %s tuttu, brüt ciroya oranı %%%s." % (_tl(ret), _num1(ret / gross * 100)))

    orders = m.get("orderCount")
    units = m.get("unitCount")
    if orders:
        text = "%d sipariş, %d adet satıldı; ortalama sepet %s" % (orders, units or 0, _tl(m.get("avgBasket")))
        d = _delta_text(prev.get("avgBasket"))
        if d:
            text += " (" + d + ")"
        notes.append(text + ".")

    items = [(k, x) for k, x in _marketplace_items(view)
             if isinstance((x or {}).get("grossRevenue"), (int, float))]
    total = sum(x["grossRevenue"] for _, x in items)
    if len(items) > 1 and total > 0:
        parts = ["%s %%%s" % (_MP_NAMES.get(k, k), _num1(x["grossRevenue"] / total * 100)) for k, x in items]
        notes.append("Brüt ciro dağılımı: " + ", ".join(parts) + ".")
        best = max(items, key=lambda it: it[1].get("netProfit") or 0)
        notes.append("Net kâra en çok katkı veren pazaryeri %s (%s)." % (
            _MP_NAMES.get(best[0], best[0]), _tl(best[1].get("netProfit"))))

    top = (view.get("topProfit") or [])[:1]
    if top:
        p = top[0]
        name = str(p.get("productName") or p.get("sku") or "")[:60]
        sku = p.get("sku")
        notes.append("En çok kâr getiren ürün: %s%s, %s kâr." % (
            name, " (%s)" % sku if sku else "", _tl(p.get("profit"))))
        loss = view.get("lossMaking") or []
        if loss:
            names = ", ".join(str(x.get("sku") or x.get("productName") or "")[:30] for x in loss[:3])
            notes.append("%d ürün zarar etti (en çok: %s)." % (len(loss), names))
        else:
            notes.append("Zarar eden ürün yok.")

    dq = view.get("dataQuality") or {}
    missing = dq.get("ordersMissingCargo") or 0
    est = dq.get("linesEstimated") or 0
    skus = dq.get("skusMissingCost") or []
    if missing > 0:
        notes.append("Kargo faturası bekleyen %d sipariş var; net kâr tahmini kargo tutarıyla hesaplandı, fatura geldikçe değişebilir." % missing)
    if est > 0:
        notes.append("%d satırın hakedişi henüz kesinleşmedi; bu satırlar tahmini değerle hesaplandı." % est)
    if skus:
        notes.append("Maliyeti girilmemiş ürün var: " + ", ".join(str(x) for x in skus[:6]) + ".")
    if view.get("status") == "taslak":
        notes.append("Bu rapor taslaktır; veriler kesinleştikçe rakamlar değişebilir.")
    return notes


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

    view = {
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
    view["notes"] = build_notes(view)
    return view


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
