"""
blueprints/cash_routes.py
-------------------------
Nakit ve borç yönetimi (Faz 1 / Aşama 2): /nakit sayfası, 13 haftalık nakit
akışı, hesap bakiyeleri, kredi kartları/taksitler, planlı ödemeler.
Hesap mantığı nakit.py'de; bu kayıtlar kâr-zarar hesabına girmez.
"""
from datetime import date

from flask import Blueprint, jsonify, render_template, request

import nakit
from database import get_connection

bp = Blueprint("cash_routes", __name__)


def _err(exc, code=400):
    return jsonify({"error": str(exc)}), code


@bp.route("/nakit")
def nakit_page():
    return render_template("pages/nakit.html", active_page="nakit")


@bp.route("/api/nakit/akis")
def api_forecast():
    only = request.args.get("yalnizca_kesin") in ("1", "true")
    try:
        return jsonify(nakit.forecast_13_weeks(only_certain=only))
    except Exception as exc:  # noqa: BLE001 - kullanıcıya hata metni dönsün
        return _err(f"Hesaplama hatası: {exc}", 500)


@bp.route("/api/nakit/hesaplar")
def api_accounts():
    with get_connection() as conn:
        accounts = nakit.latest_balances(conn)
    return jsonify({"items": accounts, "serbestNakit": nakit.free_cash(accounts)})


@bp.route("/api/nakit/hesaplar/<int:hesap_id>/bakiye", methods=["POST"])
def api_add_balance(hesap_id):
    d = request.get_json(silent=True) or {}
    try:
        with get_connection() as conn:
            nakit.add_balance(conn, hesap_id, d.get("tarih") or date.today().isoformat(),
                              d.get("bakiye"), d.get("altin_adet"), d.get("birim_fiyat"),
                              d.get("birim_maliyet"), d.get("notlar"))
    except (TypeError, ValueError) as exc:
        return _err(exc)
    return jsonify({"ok": True})


@bp.route("/api/nakit/kartlar")
def api_cards():
    with get_connection() as conn:
        return jsonify({"items": nakit.card_overview(conn)})


@bp.route("/api/nakit/kartlar/<int:kart_id>/borc", methods=["POST"])
def api_card_debt(kart_id):
    d = request.get_json(silent=True) or {}
    try:
        borc = float(d["guncel_borc"])
        tarih = d.get("tarih") or date.today().isoformat()
        date.fromisoformat(tarih)
    except (KeyError, TypeError, ValueError) as exc:
        return _err(exc)
    with get_connection() as conn:
        conn.execute("UPDATE credit_cards SET guncel_borc=?, guncel_borc_tarihi=? WHERE id=?", (borc, tarih, kart_id))
    return jsonify({"ok": True})


@bp.route("/api/nakit/kartlar/<int:kart_id>/ekstre", methods=["POST"])
def api_add_statement(kart_id):
    d = request.get_json(silent=True) or {}
    try:
        date.fromisoformat(d["son_odeme_tarihi"])
        with get_connection() as conn:
            conn.execute("""INSERT INTO card_statements (kart_id, donem, tutar, son_odeme_tarihi) VALUES (?,?,?,?)
                            ON CONFLICT(kart_id, donem) DO UPDATE SET tutar=excluded.tutar,
                            son_odeme_tarihi=excluded.son_odeme_tarihi""",
                         (kart_id, d["donem"], float(d["tutar"]), d["son_odeme_tarihi"]))
    except (KeyError, TypeError, ValueError) as exc:
        return _err(exc)
    return jsonify({"ok": True})


@bp.route("/api/nakit/ekstre/<int:ekstre_id>/odendi", methods=["POST"])
def api_statement_paid(ekstre_id):
    d = request.get_json(silent=True) or {}
    with get_connection() as conn:
        nakit.mark_statement_paid(conn, ekstre_id, d.get("tarih"), d.get("odendi", True))
    return jsonify({"ok": True})


@bp.route("/api/nakit/taksit/<int:plan_id>/odendi", methods=["POST"])
def api_installment_paid(plan_id):
    with get_connection() as conn:
        nakit.pay_installment(conn, plan_id)
    return jsonify({"ok": True})


@bp.route("/api/nakit/planli")
def api_scheduled():
    today = date.today()
    with get_connection() as conn:
        items = []
        for p in conn.execute("SELECT * FROM scheduled_payments ORDER BY baslangic_tarihi").fetchall():
            p = dict(p)
            events = {e["plan_tarihi"]: dict(e) for e in conn.execute(
                "SELECT * FROM scheduled_payment_events WHERE odeme_id=?", (p["id"],))}
            overrides = {r["plan_tarihi"]: r["tutar"] for r in conn.execute(
                "SELECT plan_tarihi, tutar FROM scheduled_payment_amounts WHERE odeme_id=?", (p["id"],))}
            occ = nakit.payment_occurrences(p, today, nakit.add_months(today, 12), events)
            p["siradakiler"] = [{"plan": a.isoformat(), "tarih": b.isoformat(),
                                 "tutar": nakit.occurrence_amount(p, a, overrides)} for a, b in occ[:3]]
            items.append(p)
    return jsonify({"items": items})


@bp.route("/api/nakit/planli", methods=["POST"])
def api_add_scheduled():
    d = request.get_json(silent=True) or {}
    try:
        date.fromisoformat(d["baslangic_tarihi"])
        if d.get("bitis_tarihi"):
            date.fromisoformat(d["bitis_tarihi"])
        if d.get("kategori") not in nakit.PAYMENT_CATEGORIES:
            raise ValueError("kategori: " + ", ".join(nakit.PAYMENT_CATEGORIES))
        with get_connection() as conn:
            cur = conn.execute("""INSERT INTO scheduled_payments
                (aciklama, kategori, tutar, baslangic_tarihi, tekrar, ay_sonu, bitis_tarihi, notlar, tutar_bekleniyor)
                VALUES (?,?,?,?,?,?,?,?,?)""",
                               (d["aciklama"], d["kategori"], float(d.get("tutar") or 0), d["baslangic_tarihi"],
                                d.get("tekrar", "yok"), 1 if d.get("ay_sonu") else 0, d.get("bitis_tarihi") or None,
                                d.get("notlar"), 1 if d.get("tutar_bekleniyor") else 0))
    except (KeyError, TypeError, ValueError) as exc:
        return _err(exc)
    return jsonify({"ok": True, "id": cur.lastrowid})


@bp.route("/api/nakit/planli/<int:odeme_id>/olay", methods=["POST"])
def api_scheduled_event(odeme_id):
    """Bir taksiti ödendi / ertelendi (yeni_tarih) / iptal olarak işaretle."""
    d = request.get_json(silent=True) or {}
    try:
        if d.get("durum") not in ("odendi", "ertelendi", "iptal"):
            raise ValueError("durum: odendi / ertelendi / iptal")
        with get_connection() as conn:
            nakit.set_payment_event(conn, odeme_id, d["plan_tarihi"], d["durum"], d.get("yeni_tarih"))
    except (KeyError, TypeError, ValueError) as exc:
        return _err(exc)
    return jsonify({"ok": True})


@bp.route("/api/nakit/uyarilar")
def api_alerts():
    with get_connection() as conn:
        return jsonify({"kartlar": nakit.card_alerts(conn)})


@bp.route("/api/nakit/planli/<int:odeme_id>/tutar", methods=["POST"])
def api_scheduled_amount(odeme_id):
    """Tutarı beklenen (ör. muhasebeciden) bir taksitin tutarını gir."""
    d = request.get_json(silent=True) or {}
    try:
        with get_connection() as conn:
            nakit.set_occurrence_amount(conn, odeme_id, d["plan_tarihi"], d["tutar"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err(exc)
    return jsonify({"ok": True})


@bp.route("/api/nakit/pazaryeri-odemeleri")
def api_marketplace_payouts():
    import external_payout_db as ep
    from datetime import datetime
    items = [dict(e, tarih=datetime.fromtimestamp(e["payment_date"] / 1000).date().isoformat(),
                  kaynak="manuel" if e["region_code"] == ep.MANUAL_REGION else "panel")
             for e in ep.get_estimates()]
    return jsonify({"items": items, "durum": ep.get_scrape_status()})


@bp.route("/api/nakit/pazaryeri-odemeleri", methods=["POST"])
def api_add_marketplace_payout():
    """Pazaryeri panelindeki 'gelecek ödemeler' listesinden elle giriş (kesin sayılır)."""
    import external_payout_db as ep
    from datetime import datetime
    d = request.get_json(silent=True) or {}
    try:
        day = date.fromisoformat(d["tarih"])
        ms = int(datetime(day.year, day.month, day.day).timestamp() * 1000)
        ep.upsert_manual_estimate(d.get("marketplace"), ms, d["tutar"])
    except (KeyError, TypeError, ValueError) as exc:
        return _err(exc)
    return jsonify({"ok": True})


@bp.route("/api/nakit/pazaryeri-odemeleri/sil", methods=["POST"])
def api_delete_marketplace_payout():
    import external_payout_db as ep
    d = request.get_json(silent=True) or {}
    try:
        ep.delete_estimate(d["marketplace"], d["region_code"], int(d["payment_date"]))
    except (KeyError, TypeError, ValueError) as exc:
        return _err(exc)
    return jsonify({"ok": True})


@bp.route("/api/nakit/hb-gecikmis")
def api_hb_overdue():
    return jsonify(nakit.hb_overdue_estimates())
