"""
blueprints/supplier_routes.py
------------------------------
Toptancı borcu yönetimi: tedarikçi ekleme/silme, SKU->tedarikçi ataması
(bkz. cost_routes.py'deki /api/product-cost/<sku>/tedarikci), ödeme girişi
ve bakiye görüntüleme.

Satış kaynaklı borç hareketleri OTOMATİK eklenir (database.py ->
upsert_order_lines -> _sync_supplier_debt); burada elle işlem yapılmaz.

app.py'de kayıt: app.register_blueprint(supplier_routes_bp)
"""

from flask import Blueprint, jsonify, request

from database import (
    add_supplier_adjustment,
    add_supplier_payment,
    backfill_supplier_debt,
    create_supplier,
    delete_supplier,
    get_total_supplier_debt,
    list_sales_since,
    list_supplier_ledger,
    list_suppliers,
    reset_supplier_debt,
)

bp = Blueprint("supplier_routes", __name__)


@bp.route("/api/tedarikciler", methods=["GET"])
def get_suppliers():
    return jsonify({"items": list_suppliers(), "toplam_borc": get_total_supplier_debt()})


@bp.route("/api/tedarikciler", methods=["POST"])
def add_supplier():
    data = request.get_json(silent=True) or {}
    ad = (data.get("ad") or "").strip()
    if not ad:
        return jsonify({"error": "'ad' alanı zorunlu."}), 400
    new_id = create_supplier(ad)
    return jsonify({"ok": True, "id": new_id, "ad": ad})


@bp.route("/api/tedarikciler/<int:tedarikci_id>", methods=["DELETE"])
def remove_supplier(tedarikci_id):
    delete_supplier(tedarikci_id)
    return jsonify({"ok": True})


@bp.route("/api/tedarikciler/<int:tedarikci_id>/odeme", methods=["POST"])
def pay_supplier(tedarikci_id):
    data = request.get_json(silent=True) or {}
    try:
        tutar = float(data["tutar"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "'tutar' zorunlu ve sayısal olmalı."}), 400
    aciklama = data.get("aciklama", "")
    if tutar <= 0:
        return jsonify({"error": "Ödeme tutarı pozitif olmalı."}), 400
    try:
        add_supplier_payment(tedarikci_id, tutar, aciklama, data.get("tarih") or None)
    except ValueError:
        return jsonify({"error": "'tarih' YYYY-MM-DD olmalı."}), 400
    return jsonify({"ok": True})


@bp.route("/api/tedarikciler/<int:tedarikci_id>/hareketler", methods=["GET"])
def supplier_ledger(tedarikci_id):
    return jsonify({"items": list_supplier_ledger(tedarikci_id)})


@bp.route("/api/tedarikciler/<int:tedarikci_id>/duzeltme", methods=["POST"])
def adjust_supplier(tedarikci_id):
    """'Borç Ekle' butonu: tutar pozitifse bakiyeyi artırır, negatifse
    düşürür. Gerçek bir ödeme sayılmaz (son_odeme_tarihi'ni etkilemez)."""
    data = request.get_json(silent=True) or {}
    try:
        tutar = float(data["tutar"])
    except (KeyError, TypeError, ValueError):
        return jsonify({"error": "'tutar' zorunlu ve sayısal olmalı."}), 400
    aciklama = data.get("aciklama", "Manuel borç düzeltmesi")
    add_supplier_adjustment(tedarikci_id, tutar, aciklama)
    return jsonify({"ok": True})


@bp.route("/api/tedarikciler/<int:tedarikci_id>/sifirla", methods=["POST"])
def zero_supplier_debt(tedarikci_id):
    """Tedarikçinin o anki bakiyesini sıfırlar (dengeleyici 'duzeltme'
    hareketi eklenir, geçmiş silinmez)."""
    data = request.get_json(silent=True) or {}
    aciklama = data.get("aciklama", "Bakiye sıfırlama")
    eklenen = reset_supplier_debt(tedarikci_id, aciklama)
    return jsonify({"ok": True, "eklenen_hareket": eklenen})


@bp.route("/api/tedarikciler/satislar", methods=["GET"])
def supplier_sales():
    """03.08.2026 (veya ?since=YYYY-MM-DD ile başka bir tarih) sonrası
    satılan tüm ürünleri döner, iptal/iade hariç. Frontend'de Excel/PDF'e
    aktarım butonu için düz liste."""
    since = request.args.get("since", "2026-08-03")
    items = list_sales_since(since)
    return jsonify({
        "since": since,
        "items": items,
        "toplam_adet": sum(i["quantity"] for i in items),
        "toplam_tutar": round(sum(i["total"] for i in items), 2),
    })


@bp.route("/api/tedarikciler/satislar/export", methods=["GET"])
def supplier_sales_export():
    """Aynı veri (03.08.2026+ satışlar, iptal/iade hariç) CSV dosyası olarak
    indirilir -- Excel'de doğrudan açılır. ?since=YYYY-MM-DD ile tarih
    değiştirilebilir. Frontend'de <a href="/api/tedarikciler/satislar/export">
    şeklinde bir bağlantı/buton koymak yeterli, indirme tarayıcı tarafından
    otomatik tetiklenir."""
    import csv
    import io

    from flask import Response

    since = request.args.get("since", "2026-08-03")
    items = list_sales_since(since)

    buf = io.StringIO()
    buf.write("\ufeff")  # Excel'in Türkçe karakterleri doğru göstermesi için UTF-8 BOM
    writer = csv.writer(buf, delimiter=";")
    writer.writerow([
        "Pazaryeri", "Siparis No", "Tarih (epoch ms)", "Durum",
        "SKU", "Urun Adi", "Adet", "Birim Fiyat", "Toplam",
    ])
    for i in items:
        writer.writerow([
            i["marketplace"], i["order_number"], i["order_date"], i["status"],
            i["sku"], i["product_name"], i["quantity"], i["unit_price"], i["total"],
        ])

    filename = f"satislar_{since.replace('-', '')}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@bp.route("/api/tedarikciler/backfill", methods=["POST"])
def backfill():
    """Bir SKU'ya yeni tedarikçi atadıktan sonra, o SKU'nun atamadan ÖNCE
    satılmış geçmiş order_lines satırları için de borç yazılsın istersen
    bunu çağır. Tüm order_lines'ı tarar, idempotenttir."""
    taranan = backfill_supplier_debt()
    return jsonify({"ok": True, "taranan_satir": taranan, "items": list_suppliers()})


# ---------------------------------------------------------------- Faz 1 / Aşama 2
# Vade, açılış, mutabakat (bkz. supplier_ledger.py)

import supplier_ledger  # noqa: E402
from database import get_connection  # noqa: E402


@bp.route("/api/tedarikciler/<int:tedarikci_id>/ozet", methods=["GET"])
def supplier_summary(tedarikci_id):
    with get_connection() as conn:
        return jsonify({
            "bakiye": supplier_ledger.balance(conn, tedarikci_id),
            "vade": supplier_ledger.due_buckets(conn, tedarikci_id),
            "acikBorclar": [{"vade": d, "tutar": a} for d, a in supplier_ledger.open_obligations(conn, tedarikci_id)],
            "mutabakat": supplier_ledger.reconciliation(conn, tedarikci_id),
            "hareketler": supplier_ledger.ledger(conn, tedarikci_id),
            "otomatikBaslangic": supplier_ledger.LEDGER_START.isoformat(),
        })


@bp.route("/api/tedarikciler/<int:tedarikci_id>/hareket", methods=["POST"])
def supplier_add_movement(tedarikci_id):
    """Elle hareket: tip acilis / duzeltme (ödeme için /odeme)."""
    d = request.get_json(silent=True) or {}
    try:
        with get_connection() as conn:
            new_id = supplier_ledger.add_movement(conn, tedarikci_id, d.get("tip"), d["tutar"], d.get("aciklama", ""),
                                                  d["tarih"], d.get("vade_tarihi") or None)
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True, "id": new_id})


@bp.route("/api/tedarikciler/hareket/<int:hareket_id>/vade", methods=["POST"])
def supplier_movement_due(hareket_id):
    d = request.get_json(silent=True) or {}
    try:
        with get_connection() as conn:
            supplier_ledger.set_movement_due(conn, hareket_id, d["vade_tarihi"])
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


@bp.route("/api/tedarikciler/<int:tedarikci_id>/ay-vade", methods=["POST"])
def supplier_month_due(tedarikci_id):
    d = request.get_json(silent=True) or {}
    try:
        with get_connection() as conn:
            supplier_ledger.set_month_due(conn, tedarikci_id, d["ay"], d["vade_tarihi"])
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


@bp.route("/api/tedarikciler/<int:tedarikci_id>/fatura", methods=["POST"])
def supplier_invoice(tedarikci_id):
    """Ay sonu mutabakatı için tedarikçinin fatura toplamı (otomatik düzeltme YAPILMAZ)."""
    d = request.get_json(silent=True) or {}
    try:
        with get_connection() as conn:
            supplier_ledger.set_invoice(conn, tedarikci_id, d["ay"], float(d["tutar"]), d.get("aciklama"))
    except (KeyError, TypeError, ValueError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})
