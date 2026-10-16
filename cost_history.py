"""Maliyet geçmişi: bir satışın alış maliyeti, SİPARİŞ TARİHİNDE geçerli olan maliyettir.

Kural: product_cost_history'de (sku, valid_from_ms, cost_incl_vat) kayıtları tutulur.
Bir siparişin maliyeti = valid_from_ms <= order_date olan en yeni kayıt.
Böylece zam sonrası girilen yeni maliyet geçmiş satışların kârını DEĞİŞTİRMEZ.

product_costs tablosu "güncel maliyet" olarak kalır (form, manuel sipariş,
bildirimler onu okur); KDV oranı da oradan okunur.

Tüm fonksiyonlar açık bir sqlite3 bağlantısı alır (get_connection() ile uyumlu,
row_factory=sqlite3.Row olması gerekmez). Commit çağıran tarafa aittir.
"""
import sqlite3
import time
from bisect import bisect_right

BASLANGIC_MS = 0  # "her zamandan beri" geçerli ilk kayıt


def ensure_table(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS product_cost_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sku TEXT NOT NULL,
            cost_incl_vat REAL NOT NULL,
            valid_from_ms INTEGER NOT NULL,
            source TEXT NOT NULL DEFAULT 'manual',
            note TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime')),
            UNIQUE (sku, valid_from_ms)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_pch_sku_from ON product_cost_history(sku, valid_from_ms)"
    )


def backfill_from_product_costs(conn):
    """Geçmişi olmayan her SKU için mevcut maliyeti valid_from=0 ile ekler.
    Idempotent: ikinci çalıştırmada hiçbir şey eklemez. Eklenen satır sayısını döner."""
    before = conn.execute("SELECT COUNT(*) FROM product_cost_history").fetchone()[0]
    conn.execute("""
        INSERT OR IGNORE INTO product_cost_history
            (sku, cost_incl_vat, valid_from_ms, source, note)
        SELECT pc.sku, pc.cost_incl_vat, 0, 'backfill', 'Mevcut maliyet (geçmiş başlangıcı)'
        FROM product_costs pc
        WHERE pc.sku IS NOT NULL AND pc.cost_incl_vat IS NOT NULL
          AND NOT EXISTS (SELECT 1 FROM product_cost_history h WHERE h.sku = pc.sku)
    """)
    after = conn.execute("SELECT COUNT(*) FROM product_cost_history").fetchone()[0]
    return after - before


def load_history(conn):
    """{sku: ([valid_from_ms,...], [cost_incl_vat,...])} -- tarih sırasına göre."""
    out = {}
    rows = conn.execute(
        "SELECT sku, valid_from_ms, cost_incl_vat FROM product_cost_history "
        "ORDER BY sku, valid_from_ms"
    ).fetchall()
    for r in rows:
        starts, costs = out.setdefault(r[0], ([], []))
        starts.append(r[1])
        costs.append(r[2])
    return out


def cost_at(history, sku, order_date_ms, fallback=None):
    """Siparişin verildiği anda geçerli KDV dahil birim maliyet.
    Geçmiş yoksa ya da sipariş tarihi bilinmiyorsa fallback (güncel maliyet) döner."""
    h = history.get(sku)
    if not h or order_date_ms is None:
        return fallback
    i = bisect_right(h[0], order_date_ms) - 1
    return h[1][i] if i >= 0 else fallback


def apply_cost_change(conn, sku, new_cost_incl, effective_ms=None, source="manual", note=None):
    """Zam/indirim kaydı: new_cost_incl, effective_ms'den (varsayılan: şimdi) itibaren
    verilen SİPARİŞLERE uygulanır; öncesine dokunulmaz.

    - Gelecek tarihli geçerlilik reddedilir (product_costs 'güncel' değeri tutarsız kalır).
    - SKU'nun geçmişi yoksa önce mevcut product_costs değeri valid_from=0 ile kaydedilir.
    - product_costs'ta hiç kayıt yoksa (yeni SKU) tek satır valid_from=0 olarak yazılır.
    - Aynı (sku, valid_from_ms) için ikinci kayıt öncekinin üzerine yazar.
    Döner: bu anda geçerli maliyet (product_costs.cost_incl_vat bununla eşitlenmeli)."""
    if new_cost_incl is None or float(new_cost_incl) < 0:
        raise ValueError("Maliyet sıfır veya pozitif bir sayı olmalı.")
    new_cost_incl = float(new_cost_incl)
    now_ms = int(time.time() * 1000)
    eff = now_ms if effective_ms is None else int(effective_ms)
    if eff > now_ms:
        raise ValueError("Geçerlilik tarihi gelecekte olamaz.")

    has_history = conn.execute(
        "SELECT 1 FROM product_cost_history WHERE sku = ? LIMIT 1", (sku,)
    ).fetchone()
    if not has_history:
        cur = conn.execute("SELECT cost_incl_vat FROM product_costs WHERE sku = ?", (sku,)).fetchone()
        if cur is None or cur[0] is None:
            # Yeni SKU: tek başlangıç kaydı, geçmiş satışlar da bu maliyeti kullanır
            # (bugünkü davranışla aynı).
            conn.execute(
                "INSERT INTO product_cost_history (sku, cost_incl_vat, valid_from_ms, source, note) "
                "VALUES (?, ?, ?, ?, ?)",
                (sku, new_cost_incl, BASLANGIC_MS, source, note or "İlk maliyet"),
            )
            return new_cost_incl
        conn.execute(
            "INSERT INTO product_cost_history (sku, cost_incl_vat, valid_from_ms, source, note) "
            "VALUES (?, ?, ?, 'backfill', 'Önceki maliyet (geçmiş başlangıcı)')",
            (sku, float(cur[0]), BASLANGIC_MS),
        )

    conn.execute(
        """INSERT INTO product_cost_history (sku, cost_incl_vat, valid_from_ms, source, note)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(sku, valid_from_ms) DO UPDATE SET
               cost_incl_vat = excluded.cost_incl_vat,
               source = excluded.source,
               note = excluded.note""",
        (sku, new_cost_incl, eff, source, note),
    )
    return conn.execute(
        "SELECT cost_incl_vat FROM product_cost_history "
        "WHERE sku = ? AND valid_from_ms <= ? ORDER BY valid_from_ms DESC LIMIT 1",
        (sku, now_ms),
    ).fetchone()[0]


def preview_change(conn, sku, effective_ms=None):
    """Arayüz önizlemesi: bu geçerlilik tarihinden ÖNCEKİ (değişmeyecek) ve
    SONRAKİ (yeni maliyetle hesaplanacak) sipariş satırı sayıları."""
    eff = int(time.time() * 1000) if effective_ms is None else int(effective_ms)
    row = conn.execute(
        """SELECT COALESCE(SUM(CASE WHEN o.order_date <  ? THEN 1 ELSE 0 END), 0),
                  COALESCE(SUM(CASE WHEN o.order_date >= ? THEN 1 ELSE 0 END), 0)
           FROM order_lines ol
           JOIN orders o ON o.marketplace = ol.marketplace
                        AND o.shipment_package_id = ol.shipment_package_id
           WHERE COALESCE(ol.merchant_sku, ol.barcode) = ?""",
        (eff, eff, sku),
    ).fetchone()
    return {"unchanged_lines": row[0], "affected_lines": row[1], "effective_ms": eff}


class CostBook(dict):
    """{sku: product_costs satırı} + .history (maliyet geçmişi).
    Mevcut kodun costs.get(sku) kullanımını bozmadan geçmişi yanında taşır."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.history = {}


def load_history_safe(conn):
    """Tablo henüz yoksa (eski DB) boş geçmiş döner; çağıran güncel maliyete düşer."""
    try:
        return load_history(conn)
    except sqlite3.OperationalError:
        return {}


def record_changes(conn, rows, source="form", now_ms=None):
    """product_costs yazıldıktan SONRA çağrılır: cost_incl_vat geçmişteki güncel
    değerden farklı olan SKU'lara 'şimdiden itibaren' kayıt ekler.
    Değişmeyen maliyet (örn. aynı Excel'in yeniden yüklenmesi) kayıt eklemez.
    Geçmişi hiç olmayan yeni SKU için tek başlangıç kaydı (valid_from=0) yazılır.
    Döner: geçmişe yeni kayıt eklenen SKU listesi."""
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    history = load_history(conn)
    changed = []
    for r in rows:
        sku, new = r.get("sku"), r.get("cost_incl_vat")
        if not sku or new is None:
            continue
        new = float(new)
        latest = cost_at(history, sku, now)
        if latest is None:
            conn.execute(
                "INSERT OR IGNORE INTO product_cost_history "
                "(sku, cost_incl_vat, valid_from_ms, source, note) VALUES (?, ?, ?, ?, ?)",
                (sku, new, BASLANGIC_MS, source, "İlk maliyet"),
            )
        elif abs(latest - new) > 1e-9:
            apply_cost_change(conn, sku, new, effective_ms=now, source=source)
            changed.append(sku)
    return changed
