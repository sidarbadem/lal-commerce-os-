"""
blueprints/finance_routes.py
------------------------------
Senkronizasyon tetikleme/durum, aylık kâr, sabit giderler ve Hepsiburada
miktar backfill route'ları. Kod app.py'den BİREBİR taşındı (davranış/URL
değişmedi); asıl senkron orkestrasyonu (_run_full_sync/_run_hb_sync/
_run_sync_in_thread) ve HB backfill iş mantığı sync_core.py'de kalıyor.

cost_routes.py / stock_routes.py / payout_routes.py ile aynı desen.
app.py'de kayıt: app.register_blueprint(finance_routes.bp)
"""

from datetime import date, datetime, timedelta
import math

from flask import Blueprint, jsonify, request

from database import (
    delete_fixed_expense,
    get_sync_progress,
    list_fixed_expenses,
    upsert_fixed_expense,
    list_expense_type_settings,
    get_finance_settings,
    save_finance_setting,
    save_expense_type_setting,
    list_vat_settings,
    save_vat_setting,
    get_connection,
)
from finance_engine import compute_profit_summary
from sync_lock import sync_lock_status
from sync_core import (
    DATA_START_DATE,
    HB_ENV,
    HB_MERCHANT_ID,
    _check_credentials,
    _check_hb_credentials,
    _is_incremental_eligible,
    _monthly_profit_for_marketplace,
    _resolve_sync_range,
    _run_full_sync,
    _run_hb_sync,
    _run_sync_in_thread,
    backfill_hb_settlement_only_quantities,
    find_hb_settlement_only_packages,
)

bp = Blueprint("finance_routes", __name__)


def _invoice_month(month):
    try:
        parsed = datetime.strptime(month, "%Y-%m")
        if parsed.strftime("%Y-%m") != month:
            raise ValueError
        start = datetime(parsed.year, parsed.month, 1)
        next_month = datetime(parsed.year + (parsed.month == 12), 1 if parsed.month == 12 else parsed.month + 1, 1)
        return start, next_month
    except (TypeError, ValueError):
        return None, None


@bp.route("/api/invoice-planning", methods=["GET"])
def api_invoice_planning():
    month = (request.args.get("month") or "").strip()
    start, end = _invoice_month(month)
    if start is None:
        return jsonify({"error": "month YYYY-MM biçiminde olmalı."}), 400
    with get_connection() as conn:
        invoices = [dict(row) for row in conn.execute(
            "SELECT id,invoice_date,description,amount_ex_vat,vat_amount,deductible_vat FROM business_invoices "
            "WHERE invoice_date >= ? AND invoice_date < ? ORDER BY invoice_date,id",
            (start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
        ).fetchall()]
        target_row = conn.execute("SELECT target_profit FROM invoice_profit_targets WHERE month=?", (month,)).fetchone()
    today = date.today()
    is_complete = (start.year, start.month) < (today.year, today.month)
    period_end = end - timedelta(milliseconds=1) if is_complete else max(
        start, min(datetime.now(), end - timedelta(milliseconds=1))
    )
    summary = compute_profit_summary(start_dt=start, end_dt=period_end, include_period_expenses=True)
    totals = summary["totals"]
    target = float(target_row["target_profit"]) if target_row else 0.0
    invoice_total = sum(float(row["amount_ex_vat"]) for row in invoices)
    invoice_deductible_vat = sum(float(row["vat_amount"]) for row in invoices if row["deductible_vat"])
    operating_profit = float(totals.get("operatingProfit") or 0)
    remaining = max(0.0, operating_profit - invoice_total - target)
    return jsonify({
        "month": month,
        "invoices": invoices,
        "invoice_total_ex_vat": round(invoice_total, 2),
        "target_profit": round(target, 2),
        "operating_profit": round(operating_profit, 2),
        "remaining_invoice_need": round(remaining, 2),
        "invoice_deductible_vat": round(invoice_deductible_vat, 2),
        "vat_payable_after_invoices_estimate": round(float(totals.get("vatPayableEstimate") or 0) - invoice_deductible_vat, 2),
        "month_complete": is_complete,
        "warning": None if is_complete else "Ay sonu kesinleşmedi; tutar dönem sonu hesabı değildir.",
        "profit_status": "Tahmini (KDV varsayımlı)" if totals.get("vatAssumed") else "Tahmini",
    })


@bp.route("/api/invoices", methods=["POST"])
def api_create_invoice():
    data = request.get_json(silent=True) or {}
    try:
        invoice_date = datetime.strptime(str(data.get("date", "")), "%Y-%m-%d").date()
        description = str(data.get("description") or "").strip()
        amount = float(data.get("amount_ex_vat"))
        vat_amount = float(data.get("vat_amount") or 0)
        deductible_vat = data.get("deductible_vat", True)
        if not isinstance(deductible_vat, bool):
            raise ValueError
        if not description or not math.isfinite(amount) or not math.isfinite(vat_amount) or amount < 0 or vat_amount < 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Tarih, açıklama ve sıfırdan küçük olmayan sayısal tutarlar gerekli."}), 400
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO business_invoices(invoice_date,description,amount_ex_vat,vat_amount,deductible_vat) VALUES(?,?,?,?,?)",
            (invoice_date.isoformat(), description, amount, vat_amount, int(deductible_vat)),
        )
        row = conn.execute("SELECT id,invoice_date,description,amount_ex_vat,vat_amount,deductible_vat FROM business_invoices WHERE id=?", (cur.lastrowid,)).fetchone()
    return jsonify({"ok": True, "item": dict(row)}), 201


@bp.route("/api/invoices/<int:invoice_id>", methods=["DELETE"])
def api_delete_invoice(invoice_id):
    with get_connection() as conn:
        cur = conn.execute("DELETE FROM business_invoices WHERE id=?", (invoice_id,))
    if not cur.rowcount:
        return jsonify({"error": "Fatura kaydı bulunamadı."}), 404
    return jsonify({"ok": True, "id": invoice_id})


@bp.route("/api/invoice-target", methods=["PUT"])
def api_invoice_target():
    data = request.get_json(silent=True) or {}
    month = str(data.get("month") or "").strip()
    start, _ = _invoice_month(month)
    try:
        target = float(data.get("target_profit"))
        if start is None or not math.isfinite(target) or target < 0:
            raise ValueError
    except (TypeError, ValueError):
        return jsonify({"error": "Geçerli ay ve sıfır veya daha büyük hedef kâr gerekli."}), 400
    with get_connection() as conn:
        conn.execute("""
            INSERT INTO invoice_profit_targets(month,target_profit) VALUES(?,?)
            ON CONFLICT(month) DO UPDATE SET target_profit=excluded.target_profit,updated_at=datetime('now','localtime')
        """, (month, target))
    return jsonify({"ok": True, "month": month, "target_profit": round(target, 2)})


@bp.route("/api/returns", methods=["GET", "POST"])
def api_returns():
    """List returns and persist whether returned goods can be resold."""
    if request.method == "GET":
        month = (request.args.get("month") or "").strip()
        params = []
        date_clause = ""
        if month:
            try:
                start = int(datetime.strptime(month, "%Y-%m").timestamp() * 1000)
                year, mon = map(int, month.split("-"))
                end_dt = datetime(year + (mon == 12), 1 if mon == 12 else mon + 1, 1)
                end = int(end_dt.timestamp() * 1000)
            except (ValueError, TypeError):
                return jsonify({"error": "month YYYY-MM biçiminde olmalı."}), 400
            date_clause = " AND s.transaction_date >= ? AND s.transaction_date < ?"
            params.extend([start, end])
        with get_connection() as conn:
            rows = conn.execute("""
                SELECT s.id,s.marketplace,s.transaction_date,s.order_number,s.barcode,
                       s.description,COALESCE(s.debt,0)-COALESCE(s.credit,0) AS amount,
                       COALESCE(rc.condition,'sellable') AS condition
                FROM settlements s LEFT JOIN return_conditions rc
                  ON rc.marketplace=s.marketplace AND rc.settlement_id=s.id
                WHERE (s.transaction_type='Return'
                       OR s.transaction_type IN ('ManualRefund','ManualRefundCancel')
                       OR s.raw_transaction_type IN ('İade','Return'))
            """ + date_clause + " ORDER BY s.transaction_date DESC", params).fetchall()
        items = [dict(r) for r in rows]
        if month:
            summary = compute_profit_summary(
                start_dt=datetime.fromtimestamp(start / 1000),
                end_dt=datetime.fromtimestamp(end / 1000) - timedelta(milliseconds=1),
            )
            matched = {r["id"]: r for r in summary["totals"].get("matchedReturns", [])}
            uncertain = {r["id"]: r for r in summary["totals"].get("unmatchedReturns", [])}
            for item in items:
                if item["id"] in matched:
                    item["match_status"] = "Eşleşti"
                    item["match_method"] = matched[item["id"]]["method"]
                elif item["id"] in uncertain:
                    item["match_status"] = "Kontrol gerekli"
                    item["match_reason"] = uncertain[item["id"]]["reason"]
                else:
                    item["match_status"] = "Bu dönemin dışında"
        return jsonify({"items": items})

    data = request.get_json(silent=True) or {}
    marketplace = str(data.get("marketplace") or "").strip().lower()
    settlement_id = str(data.get("settlement_id") or "").strip()
    condition = str(data.get("condition") or "").strip().lower()
    if marketplace not in ("trendyol", "hepsiburada") or not settlement_id:
        return jsonify({"error": "Pazaryeri ve iade kayıt numarası gerekli."}), 400
    if condition not in ("sellable", "damaged", "lost"):
        return jsonify({"error": "condition sellable, damaged veya lost olmalı."}), 400
    with get_connection() as conn:
        exists = conn.execute("""
            SELECT 1 FROM settlements WHERE marketplace=? AND id=? AND
              (transaction_type='Return' OR transaction_type IN ('ManualRefund','ManualRefundCancel')
               OR raw_transaction_type IN ('İade','Return'))
        """, (marketplace, settlement_id)).fetchone()
        if not exists:
            return jsonify({"error": "İade kaydı bulunamadı."}), 404
        conn.execute("""
            INSERT INTO return_conditions (marketplace,settlement_id,condition)
            VALUES (?,?,?) ON CONFLICT(marketplace,settlement_id) DO UPDATE SET
              condition=excluded.condition,updated_at=datetime('now','localtime')
        """, (marketplace, settlement_id, condition))
    return jsonify({"ok": True, "marketplace": marketplace,
                    "settlement_id": settlement_id, "condition": condition})


@bp.route("/api/sync-finance", methods=["POST"])
def sync_finance():
    """Siparişleri + Finans API verisini Flask sürecinin arka plan
    thread'inde çeker (Celery worker gerektirmez, bkz. _run_sync_in_thread
    notu). Hemen döner; ilerleme için /api/sync-status'ü yoklayın (polling).
    Hepsiburada bilgileri .env'de tanımlıysa, aynı tetiklemeyle Hepsiburada
    senkronizasyonu da (ayrı kilit, ayrı thread'de, paralel) başlatılır."""
    error = _check_credentials()
    if error:
        return jsonify({"error": error}), 400

    if sync_lock_status("trendyol"):
        return jsonify({"error": "Zaten devam eden bir senkronizasyon var."}), 409

    start_dt, end_dt = _resolve_sync_range(request.args)
    incremental_ok = _is_incremental_eligible(request.args)

    _run_sync_in_thread("trendyol", _run_full_sync, start_dt, end_dt, incremental_ok=incremental_ok)

    hb_started = False
    if _check_hb_credentials() is None and not sync_lock_status("hepsiburada"):
        _run_sync_in_thread("hepsiburada", _run_hb_sync, start_dt, end_dt, incremental_ok=incremental_ok)
        hb_started = True

    return jsonify({
        "started": True,
        "hepsiburada_started": hb_started,
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": end_dt.strftime("%Y-%m-%d"),
    })

@bp.route("/api/sync-status")
def sync_status():
    marketplace = request.args.get("marketplace", "trendyol")
    return jsonify(get_sync_progress(marketplace=marketplace))

@bp.route("/api/sync-hepsiburada", methods=["POST"])
def sync_hepsiburada():
    """Hepsiburada siparişlerini Flask sürecinin arka plan thread'inde çeker
    (Celery worker gerektirmez, bkz. _run_sync_in_thread notu).
    Parametreler: days=N | start_date=YYYY-MM-DD | full_history=true
    (Trendyol ile aynı mantık)."""
    error = _check_hb_credentials()
    if error:
        return jsonify({"error": error}), 400

    if sync_lock_status("hepsiburada"):
        return jsonify({"error": "Zaten devam eden bir Hepsiburada senkronizasyonu var."}), 409

    start_dt, end_dt = _resolve_sync_range(request.args)
    incremental_ok = _is_incremental_eligible(request.args)

    _run_sync_in_thread("hepsiburada", _run_hb_sync, start_dt, end_dt, incremental_ok=incremental_ok)

    return jsonify({
        "started": True,
        "start_date": start_dt.strftime("%Y-%m-%d"),
        "end_date": end_dt.strftime("%Y-%m-%d"),
    })

@bp.route("/api/hb-config-status")
def hb_config_status():
    error = _check_hb_credentials()
    return jsonify({
        "configured": error is None,
        "message": error,
        "env": HB_ENV,
        "merchant_id": HB_MERCHANT_ID if HB_MERCHANT_ID else None,
    })

@bp.route("/api/backfill-hb-quantities", methods=["POST"])
def api_backfill_hb_quantities():
    """Faz 3 backfill'i küçük bir parti (varsayılan 50 sipariş) için tetikler.
    Kuyruk boşalana kadar tekrar tekrar çağırılması amaçlanmıştır (örn. panelden
    'Eksik miktarları tamamla' butonu, ya da cron ile günde birkaç kez)."""
    cred_error = _check_hb_credentials()
    if cred_error:
        return jsonify({"error": cred_error}), 400

    limit = request.args.get("limit", default=50, type=int)
    limit = max(1, min(limit, 500))
    try:
        result = backfill_hb_settlement_only_quantities(limit=limit)
    except Exception as e:
        return jsonify({"error": f"Backfill hatası: {e}"}), 500
    return jsonify(result)

@bp.route("/api/backfill-hb-quantities/status")
def api_backfill_hb_quantities_status():
    """Kuyrukta kaç paket kaldığını (henüz gerçek quantity'si çekilmemiş) döner."""
    try:
        remaining = len(find_hb_settlement_only_packages())
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"remaining": remaining})

@bp.route("/api/monthly-profit")
def api_monthly_profit():
    args = request.args
    end_dt = datetime.now()
    if args.get("start_date"):
        try:
            start_dt = datetime.strptime(args["start_date"], "%Y-%m-%d")
        except ValueError:
            return jsonify({"error": "start_date formatı YYYY-MM-DD olmalı."}), 400
    else:
        start_dt = DATA_START_DATE

    marketplace = (request.args.get("marketplace") or "all").strip().lower()
    if marketplace not in ("all", "trendyol", "hepsiburada"):
        marketplace = "all"

    try:
        months = _monthly_profit_for_marketplace(start_dt, end_dt, marketplace)
    except Exception as e:
        return jsonify({"error": f"Hesaplama hatası: {e}"}), 500

    first_active = next(
        (i for i, m in enumerate(months) if (m.get("revenue") or 0) != 0
         or (m.get("grossProfit") or 0) != 0 or (m.get("netProfit") or 0) != 0),
        0,
    )
    months = months[first_active:]

    return jsonify({"months": months})

@bp.route("/api/fixed-expenses", methods=["GET", "POST"])
def api_fixed_expenses():
    """GET: tüm aylık sabit gider kalemlerini döner (opsiyonel ?month=YYYY-MM
    ile tek aya filtrelenebilir). POST: yeni kalem ekler/günceller (body'de
    'id' verilirse günceller). Beklenen JSON: {month, label, amount, note?}
    (month formatı 'YYYY-MM')."""
    if request.method == "GET":
        month = (request.args.get("month") or "").strip() or None
        items = list_fixed_expenses(month=month)
        return jsonify({"items": items})

    data = request.get_json(silent=True) or {}
    month = (data.get("month") or "").strip()
    label = (data.get("label") or "").strip()

    if not month:
        return jsonify({"error": "'month' alanı zorunlu (YYYY-MM formatında)."}), 400
    if not label:
        return jsonify({"error": "'label' alanı zorunlu."}), 400
    try:
        amount = float(data["amount"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "'amount' zorunlu ve sayısal olmalı."}), 400

    row = {
        "id": data.get("id"),
        "month": month,
        "label": label,
        "amount": amount,
        "note": data.get("note") or None,
        "vat_amount": (float(data["vat_amount"]) if data.get("vat_amount") not in (None, "") else None),
    }
    try:
        saved = upsert_fixed_expense(row)
    except Exception as e:
        return jsonify({"error": f"Kaydetme hatası: {e}"}), 500

    return jsonify({"ok": True, "item": saved})

@bp.route("/api/fixed-expenses/<int:expense_id>", methods=["DELETE"])
def api_delete_fixed_expense(expense_id):
    try:
        delete_fixed_expense(expense_id)
    except Exception as e:
        return jsonify({"error": f"Silme hatası: {e}"}), 500
    return jsonify({"ok": True, "id": expense_id})


@bp.route("/api/expense-type-settings", methods=["GET", "POST"])
def api_expense_type_settings():
    if request.method == "GET":
        return jsonify({"items": list_expense_type_settings()})
    data = request.get_json(silent=True) or {}
    try:
        item = save_expense_type_setting(data)
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "item": item})


@bp.route("/api/finance-settings", methods=["GET", "POST"])
def api_finance_settings():
    if request.method == "GET":
        return jsonify({"settings": get_finance_settings()})
    data = request.get_json(silent=True) or {}
    try:
        settings = None
        for key, value in data.items():
            settings = save_finance_setting(key, value)
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "settings": settings or get_finance_settings()})


@bp.route("/api/vat-settings", methods=["GET", "POST"])
def api_vat_settings():
    if request.method == "GET":
        return jsonify({"items": list_vat_settings()})
    data = request.get_json(silent=True) or {}
    try:
        item = save_vat_setting(data)
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "item": item})
