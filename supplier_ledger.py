"""Tedarikçi (Watalina) borç defteri — Faz 1 / Aşama 2 (03.11.2026).

Hareket tipleri (tedarikci_borc_hareketleri.tip), tutar İŞARETLİ tutulur
(odeme hariç — o pozitif girilir ve bakiyeden düşülür):
  acilis    -> açılış bakiyesi (+), manuel; ör. 31.10.2026 Watalina ekstresi
  alis      -> satılan satır × sipariş tarihindeki maliyet (KDV dahil) (+), OTOMATİK
  iade      -> alış yazılmış satır sonradan iptal/iade olursa (−), OTOMATİK
  duzeltme  -> elle düzeltme (±)
  odeme     -> ödeme (pozitif girilir, bakiyeden düşer)
  satis     -> eski adı 'alis' (geriye uyum; bakiye hesabında alis gibi)

Otomatik alış yalnızca LEDGER_START'tan (01.11.2026, İstanbul) itibaren
sipariş tarihli satırlar için yazılır; öncesi açılış bakiyesindedir.

Kendi stok: product_costs.kendi_stok_kalan > 0 olan SKU'nun her satılan adedi
önce kendi stoktan düşer (borç yazılmaz, kendi_stok_tuketim'e kaydedilir);
kalan 0'a inince satışlar tedarikçi borcuna yazılır. Sayım tarihinden
(kendi_stok_sayim_ms) önceki satışlar sayımda zaten düşülmüş sayılır.
Kendi stoktan satılan satır iptal/iade olursa adet stoğa geri eklenir.

Vade: M ayının alımları M+1 ayının son günü (tedarikci_vade_ayar ile ay bazında
değiştirilebilir; her hareketin vadesi ayrıca düzenlenebilir).
"""

import calendar
from collections import defaultdict
from datetime import date, datetime
from zoneinfo import ZoneInfo

from database import _EXCLUDED_ORDER_STATUSES, get_connection

TZ = ZoneInfo("Europe/Istanbul")
LEDGER_START = date(2026, 11, 1)


def _start_ms():
    return int(datetime(LEDGER_START.year, LEDGER_START.month, LEDGER_START.day, tzinfo=TZ).timestamp() * 1000)


def ms_to_date(ms):
    return datetime.fromtimestamp(ms / 1000, TZ).date()


def default_due(d):
    """M ayındaki alımın vadesi: M+1 ayının son günü."""
    y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
    return date(y, m, calendar.monthrange(y, m)[1])


def _excluded(mp, status):
    import finance_engine
    return (status in _EXCLUDED_ORDER_STATUSES.get(mp, set())
            or status in finance_engine.NEVER_FULFILLED_STATUSES)


def ensure_schema(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS kendi_stok_tuketim (
            order_line_key TEXT PRIMARY KEY,
            sku TEXT NOT NULL,
            adet INTEGER NOT NULL,
            sayim_oncesi INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tedarikci_faturalari (
            tedarikci_id INTEGER NOT NULL REFERENCES tedarikciler(id),
            ay TEXT NOT NULL,
            fatura_tutari REAL NOT NULL,
            aciklama TEXT,
            PRIMARY KEY (tedarikci_id, ay)
        )""")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tedarikci_vade_ayar (
            tedarikci_id INTEGER NOT NULL REFERENCES tedarikciler(id),
            ay TEXT NOT NULL,
            vade_tarihi TEXT NOT NULL,
            PRIMARY KEY (tedarikci_id, ay)
        )""")


def migrate_ledger_v3(conn):
    """tip CHECK'ine alis/iade/acilis eklenir, vade_tarihi + islem_tarihi
    kolonları gelir. Eski satırlar korunur ('satis' -> 'alis')."""
    row = conn.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='tedarikci_borc_hareketleri'").fetchone()
    if row and "'alis'" not in row[0]:
        conn.executescript("""
            ALTER TABLE tedarikci_borc_hareketleri RENAME TO tedarikci_borc_hareketleri_v2;
            CREATE TABLE tedarikci_borc_hareketleri (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tedarikci_id INTEGER NOT NULL REFERENCES tedarikciler(id),
                tip TEXT NOT NULL CHECK(tip IN ('acilis','alis','iade','odeme','duzeltme','satis')),
                tutar REAL NOT NULL,
                order_line_key TEXT,
                aciklama TEXT,
                islem_tarihi TEXT,
                vade_tarihi TEXT,
                tarih TEXT DEFAULT (datetime('now', 'localtime')),
                UNIQUE(order_line_key, tip)
            );
            INSERT INTO tedarikci_borc_hareketleri (id, tedarikci_id, tip, tutar, order_line_key, aciklama, islem_tarihi, tarih)
            SELECT id, tedarikci_id, CASE WHEN tip='satis' THEN 'alis' ELSE tip END, tutar, order_line_key, aciklama,
                   substr(tarih, 1, 10), tarih
            FROM tedarikci_borc_hareketleri_v2;
            DROP TABLE tedarikci_borc_hareketleri_v2;
        """)
    ensure_schema(conn)


def _due_for(conn, tedarikci_id, d):
    row = conn.execute("SELECT vade_tarihi FROM tedarikci_vade_ayar WHERE tedarikci_id=? AND ay=?",
                       (tedarikci_id, d.strftime("%Y-%m"))).fetchone()
    return row["vade_tarihi"] if row else default_due(d).isoformat()


def reconcile(conn=None):
    """İdempotent: 01.11.2026+ sipariş satırlarından alış/iade hareketlerini ve
    kendi stok tüketimini senkronlar. Dönen sözlük ne yapıldığını sayar."""
    if conn is None:
        with get_connection() as c:
            return reconcile(c)
    ensure_schema(conn)
    import cost_history
    products = {r["sku"]: dict(r) for r in conn.execute(
        "SELECT sku, cost_incl_vat, tedarikci_id, kendi_stok_kalan, kendi_stok_sayim_ms FROM product_costs")}
    stats = defaultdict(int)
    if not any(p["tedarikci_id"] or (p["kendi_stok_kalan"] or 0) > 0 for p in products.values()):
        return dict(stats)
    history = cost_history.load_history_safe(conn)
    lines = conn.execute("""
        SELECT l.marketplace, l.shipment_package_id, l.barcode, COALESCE(l.merchant_sku, l.barcode) AS sku,
               l.quantity, o.status, o.order_date, o.order_number
        FROM order_lines l JOIN orders o
          ON o.marketplace = l.marketplace AND o.shipment_package_id = l.shipment_package_id
        WHERE o.order_date >= ?
        ORDER BY o.order_date, l.marketplace, l.shipment_package_id, l.barcode
    """, (_start_ms(),)).fetchall()
    moves = defaultdict(dict)
    for r in conn.execute("SELECT id, tip, tutar, order_line_key FROM tedarikci_borc_hareketleri "
                          "WHERE order_line_key IS NOT NULL AND tip IN ('alis','iade')"):
        moves[r["order_line_key"]][r["tip"]] = dict(r)
    used = {r["order_line_key"]: dict(r) for r in conn.execute("SELECT * FROM kendi_stok_tuketim")}

    def restore_stock(key):
        u = used.pop(key, None)
        if u:
            conn.execute("DELETE FROM kendi_stok_tuketim WHERE order_line_key=?", (key,))
            conn.execute("UPDATE product_costs SET kendi_stok_kalan = COALESCE(kendi_stok_kalan,0) + ? WHERE sku=?",
                         (u["adet"], u["sku"]))
            if u["sku"] in products:
                products[u["sku"]]["kendi_stok_kalan"] = (products[u["sku"]]["kendi_stok_kalan"] or 0) + u["adet"]
            stats["kendi_stok_iade"] += u["adet"]

    seen = set()
    for ln in lines:
        key = f"{ln['marketplace']}:{ln['shipment_package_id']}:{ln['barcode']}"
        seen.add(key)
        sku, qty = ln["sku"], int(ln["quantity"] or 0)
        prod = products.get(sku)
        m = moves.get(key, {})
        if _excluded(ln["marketplace"], ln["status"]):
            restore_stock(key)
            if "alis" in m and "iade" not in m:
                d = ms_to_date(ln["order_date"])
                conn.execute("""INSERT INTO tedarikci_borc_hareketleri
                    (tedarikci_id, tip, tutar, order_line_key, aciklama, islem_tarihi, vade_tarihi)
                    SELECT tedarikci_id, 'iade', -tutar, order_line_key, ?, ?, vade_tarihi
                    FROM tedarikci_borc_hareketleri WHERE id=?""",
                             (f"İptal/iade - {sku} ({ln['status']})", datetime.now(TZ).date().isoformat(), m["alis"]["id"]))
                stats["iade"] += 1
            continue
        if "iade" in m:  # iade talebi reddedildi / sipariş yeniden geçerli
            conn.execute("DELETE FROM tedarikci_borc_hareketleri WHERE id=?", (m["iade"]["id"],))
            stats["iade_geri_alindi"] += 1
        if "alis" in m or key in used or prod is None or qty <= 0:
            continue
        own = 0
        if (prod["kendi_stok_kalan"] or 0) > 0 or prod.get("kendi_stok_sayim_ms"):
            sayim = prod.get("kendi_stok_sayim_ms")
            if sayim and ln["order_date"] < sayim:
                conn.execute("INSERT INTO kendi_stok_tuketim (order_line_key, sku, adet, sayim_oncesi) VALUES (?,?,?,1)",
                             (key, sku, qty))
                used[key] = {"order_line_key": key, "sku": sku, "adet": qty}
                stats["sayim_oncesi_kendi_stok"] += qty
                continue
            own = min(qty, prod["kendi_stok_kalan"] or 0)
            if own:
                conn.execute("INSERT INTO kendi_stok_tuketim (order_line_key, sku, adet) VALUES (?,?,?)", (key, sku, own))
                conn.execute("UPDATE product_costs SET kendi_stok_kalan = kendi_stok_kalan - ? WHERE sku=?", (own, sku))
                prod["kendi_stok_kalan"] -= own
                used[key] = {"order_line_key": key, "sku": sku, "adet": own}
                stats["kendi_stok_dusen"] += own
        rest = qty - own
        if rest <= 0 or not prod["tedarikci_id"]:
            continue
        cost = cost_history.cost_at(history, sku, ln["order_date"], fallback=prod["cost_incl_vat"])
        if cost is None:
            stats["maliyetsiz"] += 1
            continue
        d = ms_to_date(ln["order_date"])
        conn.execute("""INSERT OR IGNORE INTO tedarikci_borc_hareketleri
            (tedarikci_id, tip, tutar, order_line_key, aciklama, islem_tarihi, vade_tarihi)
            VALUES (?, 'alis', ?, ?, ?, ?, ?)""",
                     (prod["tedarikci_id"], round(cost * rest, 2), key,
                      f"Alış - {sku} x{rest} ({ln['order_number']})", d.isoformat(),
                      _due_for(conn, prod["tedarikci_id"], d)))
        stats["alis"] += 1

    # Satırı artık olmayan otomatik hareketler (ör. silinen HB placeholder paketi)
    for key, m in moves.items():
        if key in seen:
            continue
        for tip in ("alis", "iade"):
            if tip in m:
                conn.execute("DELETE FROM tedarikci_borc_hareketleri WHERE id=?", (m[tip]["id"],))
                stats["yetim_silindi"] += 1
    for key in [k for k in used if k not in seen]:
        restore_stock(key)
    conn.commit()
    return dict(stats)


# ---------------------------------------------------------------- okuma

def _sign_sql():
    return "CASE WHEN tip='odeme' THEN -tutar ELSE tutar END"


def balance(conn, tedarikci_id):
    return round(conn.execute(f"SELECT COALESCE(SUM({_sign_sql()}),0) FROM tedarikci_borc_hareketleri "
                              "WHERE tedarikci_id=?", (tedarikci_id,)).fetchone()[0], 2)


def open_obligations(conn, tedarikci_id):
    """Vadesine göre açık borç: borç doğuran hareketler vade tarihine göre
    gruplanır, ödemeler (ve eksi düzeltmeler) en eski vadeden başlayarak düşülür.
    [(vade 'YYYY-MM-DD', kalan tutar)]"""
    by_due = defaultdict(float)
    credit = 0.0
    for r in conn.execute("SELECT tip, tutar, vade_tarihi, islem_tarihi, tarih FROM tedarikci_borc_hareketleri "
                          "WHERE tedarikci_id=?", (tedarikci_id,)):
        if r["tip"] == "odeme":
            credit += r["tutar"]
        elif r["tip"] == "duzeltme" and r["tutar"] < 0:
            credit += -r["tutar"]
        else:
            due = r["vade_tarihi"] or r["islem_tarihi"] or (r["tarih"] or "")[:10]
            by_due[due] += r["tutar"]
    out = []
    for due in sorted(by_due):
        amt = by_due[due]
        if amt <= 0:
            credit += -amt
            continue
        take = min(amt, credit)
        credit -= take
        if amt - take > 0.005:
            out.append((due, round(amt - take, 2)))
    return out


def due_buckets(conn, tedarikci_id, today=None):
    today = today or datetime.now(TZ).date()
    this_end = date(today.year, today.month, calendar.monthrange(today.year, today.month)[1])
    next_end = default_due(today)
    b = {"vadesiGecmis": 0.0, "buAy": 0.0, "gelecekAy": 0.0, "sonrasi": 0.0}
    for due, amt in open_obligations(conn, tedarikci_id):
        d = date.fromisoformat(due)
        key = ("vadesiGecmis" if d < today else "buAy" if d <= this_end
               else "gelecekAy" if d <= next_end else "sonrasi")
        b[key] += amt
    return {k: round(v, 2) for k, v in b.items()}


def reconciliation(conn, tedarikci_id):
    """Ay sonu mutabakatı: sistemin alış hesabı (alis + iade) vs tedarikçi faturası."""
    sys_rows = conn.execute("""
        SELECT substr(islem_tarihi,1,7) AS ay, SUM(tutar) AS t FROM tedarikci_borc_hareketleri
        WHERE tedarikci_id=? AND tip IN ('alis','iade','satis') GROUP BY 1""", (tedarikci_id,)).fetchall()
    inv = {r["ay"]: dict(r) for r in conn.execute(
        "SELECT ay, fatura_tutari, aciklama FROM tedarikci_faturalari WHERE tedarikci_id=?", (tedarikci_id,))}
    months = sorted({r["ay"] for r in sys_rows if r["ay"]} | set(inv))
    sysmap = {r["ay"]: r["t"] for r in sys_rows}
    out = []
    for ay in months:
        s = round(sysmap.get(ay) or 0.0, 2)
        f = inv.get(ay, {}).get("fatura_tutari")
        out.append({"ay": ay, "sistem": s, "fatura": f, "fark": round(f - s, 2) if f is not None else None,
                    "aciklama": inv.get(ay, {}).get("aciklama")})
    return out


def ledger(conn, tedarikci_id, limit=300):
    return [dict(r) for r in conn.execute("""
        SELECT id, tip, tutar, aciklama, islem_tarihi, vade_tarihi, tarih, order_line_key
        FROM tedarikci_borc_hareketleri WHERE tedarikci_id=?
        ORDER BY COALESCE(islem_tarihi, substr(tarih,1,10)) DESC, id DESC LIMIT ?""", (tedarikci_id, limit))]


# ---------------------------------------------------------------- yazma

def add_movement(conn, tedarikci_id, tip, tutar, aciklama, islem_tarihi, vade_tarihi=None):
    if tip not in ("acilis", "odeme", "duzeltme"):
        raise ValueError("Elle yalnızca acilis/odeme/duzeltme girilebilir")
    tutar = float(tutar)
    if tip == "odeme" and tutar <= 0:
        raise ValueError("Ödeme tutarı pozitif olmalı")
    date.fromisoformat(islem_tarihi)
    if vade_tarihi:
        date.fromisoformat(vade_tarihi)
    cur = conn.execute("""INSERT INTO tedarikci_borc_hareketleri
        (tedarikci_id, tip, tutar, aciklama, islem_tarihi, vade_tarihi) VALUES (?,?,?,?,?,?)""",
                       (tedarikci_id, tip, tutar, aciklama, islem_tarihi, vade_tarihi))
    return cur.lastrowid


def set_movement_due(conn, hareket_id, vade_tarihi):
    date.fromisoformat(vade_tarihi)
    conn.execute("UPDATE tedarikci_borc_hareketleri SET vade_tarihi=? WHERE id=? AND tip!='odeme'",
                 (vade_tarihi, hareket_id))


def set_month_due(conn, tedarikci_id, ay, vade_tarihi):
    """Bir ayın tüm alış/iade hareketlerinin vadesini değiştirir; o ay için
    sonradan yazılacak alışlar da bu vadeyi alır."""
    date.fromisoformat(vade_tarihi)
    ensure_schema(conn)
    conn.execute("INSERT INTO tedarikci_vade_ayar (tedarikci_id, ay, vade_tarihi) VALUES (?,?,?) "
                 "ON CONFLICT(tedarikci_id, ay) DO UPDATE SET vade_tarihi=excluded.vade_tarihi",
                 (tedarikci_id, ay, vade_tarihi))
    conn.execute("UPDATE tedarikci_borc_hareketleri SET vade_tarihi=? WHERE tedarikci_id=? "
                 "AND tip IN ('alis','iade') AND substr(islem_tarihi,1,7)=?", (vade_tarihi, tedarikci_id, ay))


def set_invoice(conn, tedarikci_id, ay, tutar, aciklama=None):
    ensure_schema(conn)
    conn.execute("INSERT INTO tedarikci_faturalari (tedarikci_id, ay, fatura_tutari, aciklama) VALUES (?,?,?,?) "
                 "ON CONFLICT(tedarikci_id, ay) DO UPDATE SET fatura_tutari=excluded.fatura_tutari, "
                 "aciklama=excluded.aciklama", (tedarikci_id, ay, float(tutar), aciklama))
