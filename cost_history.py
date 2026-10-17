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
from datetime import datetime
from zoneinfo import ZoneInfo

BASLANGIC_MS = 0  # "her zamandan beri" geçerli ilk kayıt
TZ = ZoneInfo("Europe/Istanbul")
KDV_ORANLARI = (0.0, 0.01, 0.10, 0.20)
VARSAYILAN_KDV = 0.20
BUYUK_FARK_ESIGI = 0.40  # bu orandan büyük maliyet değişimi uyarı üretir


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
        h = history.get(sku)
        son_kayit = h[1][-1] if h else None  # ileri tarihli (bekleyen) kayıt dahil en son maliyet
        if son_kayit is not None and abs(son_kayit - new) <= 1e-9:
            continue  # yeni maliyet zaten kayıtlı (bekleyen kayıt olabilir): tekrar yazma
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


# ---------------------------------------------------------------------------
# Arayüz/API katmanı: zam (fiyat değişikliği), önizleme, geçmiş, hata düzeltmesi
# ---------------------------------------------------------------------------

def parse_effective(text):
    """'YYYY-AA-GG SS:DD' veya 'YYYY-AA-GGTSS:DD' (İstanbul saati) -> epoch ms.
    Boş/None -> None (çağıran 'şimdi' kullanır)."""
    if text in (None, ""):
        return None
    s = str(text).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=TZ).timestamp() * 1000)
        except ValueError:
            continue
    raise ValueError("Tarih biçimi geçersiz (YYYY-AA-GG SS:DD).")


def format_ms(ms):
    if ms is None:
        return None
    if ms <= BASLANGIC_MS:
        return "Başlangıç"
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%Y-%m-%d %H:%M")


def vat_rate_for(conn, sku):
    """SKU'nun mevcut KDV oranı (incl/excl'den). Eksik ya da bilinen oranlara
    uymayan (bozuk/eski) kayıtta %20 varsayılır."""
    r = conn.execute(
        "SELECT cost_incl_vat, cost_excl_vat FROM product_costs WHERE sku = ?", (sku,)
    ).fetchone()
    if r and r[0] and r[1] and r[1] > 0:
        oran = r[0] / r[1] - 1
        en_yakin = min(KDV_ORANLARI, key=lambda x: abs(x - oran))
        if abs(en_yakin - oran) < 0.01:
            return en_yakin
    return VARSAYILAN_KDV


def _gecerli_maliyet(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError("Maliyet sayısal olmalı.")
    if not (v > 0):
        raise ValueError("Maliyet sıfırdan büyük olmalı.")
    return v


def describe_change(conn, sku, new_cost, effective_ms=None, now_ms=None):
    """Zam önizlemesi: hiçbir şey yazmaz. Kaç geçmiş satırın DEĞİŞMEYECEĞİ,
    kaç satırın yeni maliyetle hesaplanacağı, uyarılar ve engeller."""
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    eff = now if effective_ms is None else int(effective_ms)
    new_cost = _gecerli_maliyet(new_cost)
    pc = conn.execute("SELECT cost_incl_vat FROM product_costs WHERE sku = ?", (sku,)).fetchone()
    if pc is None:
        raise ValueError("Bu SKU için maliyet kaydı yok; önce ürünü ekleyin.")

    history = load_history_safe(conn)
    h = history.get(sku)
    fallback = pc[0]
    cost_then = cost_at(history, sku, eff, fallback=fallback)
    sonraki = [(s, c) for s, c in zip(h[0], h[1]) if s > eff] if h else []

    uyarilar, blocked, block_reason = [], False, None
    if sonraki:
        blocked = True
        block_reason = ("Bu tarihten sonra başka bir maliyet kaydı var "
                        f"({format_ms(sonraki[0][0])}). Önce o kaydı düzenleyin ya da daha geç bir tarih seçin.")
    fark = ((new_cost - cost_then) / cost_then) if cost_then else 0.0
    no_change = cost_then is not None and abs(new_cost - cost_then) <= 1e-9
    if no_change:
        uyarilar.append("Yeni maliyet, seçilen anda geçerli olan maliyetle aynı.")
    if abs(fark) > BUYUK_FARK_ESIGI:
        uyarilar.append(f"Büyük değişim (%{fark * 100:+.0f}): doğru ürün ve doğru fiyat mı?")
    if eff < now - 7 * 24 * 3600 * 1000:
        uyarilar.append("Geçerlilik 7 günden daha eski: o tarihten sonraki siparişlerin kârı değişir.")

    counts = preview_change(conn, sku, effective_ms=eff)
    return {
        "sku": sku,
        "old_cost": cost_then,
        "new_cost": new_cost,
        "change_pct": round(fark * 100, 2),
        "effective_ms": eff,
        "effective_text": format_ms(eff),
        "is_future": eff > now,
        "unchanged_lines": counts["unchanged_lines"],
        "affected_lines": counts["affected_lines"],
        "warnings": uyarilar,
        "no_change": no_change,
        "blocked": blocked,
        "block_reason": block_reason,
    }


def change_cost(conn, sku, new_cost, effective_ms=None, source="manual", note=None, now_ms=None):
    """Zam kaydı. effective_ms geçmiş ya da GELECEK olabilir; öncesindeki siparişlerin
    maliyeti değişmez. product_costs 'güncel (ileriye dönük)' maliyeti ve KDV hariç
    karşılığı (SKU'nun mevcut KDV oranıyla) aynı işlemde güncellenir."""
    d = describe_change(conn, sku, new_cost, effective_ms, now_ms)
    if d["blocked"]:
        raise ValueError(d["block_reason"])
    if d["no_change"]:
        raise ValueError("Yeni maliyet, seçilen anda geçerli olan maliyetle aynı; kayıt eklenmedi.")
    eff, yeni = d["effective_ms"], d["new_cost"]

    if not conn.execute("SELECT 1 FROM product_cost_history WHERE sku = ? LIMIT 1", (sku,)).fetchone():
        cur = conn.execute("SELECT cost_incl_vat FROM product_costs WHERE sku = ?", (sku,)).fetchone()
        conn.execute(
            "INSERT INTO product_cost_history (sku, cost_incl_vat, valid_from_ms, source, note) "
            "VALUES (?, ?, ?, 'backfill', 'Önceki maliyet (geçmiş başlangıcı)')",
            (sku, float(cur[0]), BASLANGIC_MS),
        )
    once = cost_at(load_history(conn), sku, eff - 1)

    conn.execute(
        """INSERT INTO product_cost_history (sku, cost_incl_vat, valid_from_ms, source, note)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(sku, valid_from_ms) DO UPDATE SET
               cost_incl_vat = excluded.cost_incl_vat, source = excluded.source, note = excluded.note""",
        (sku, yeni, eff, source, note),
    )
    rate = vat_rate_for(conn, sku)
    conn.execute(
        "UPDATE product_costs SET cost_incl_vat = ?, cost_excl_vat = ?, "
        "updated_at = datetime('now', 'localtime') WHERE sku = ?",
        (yeni, round(yeni / (1 + rate), 6), sku),
    )

    h = load_history(conn)
    sonra_once = cost_at(h, sku, eff - 1)
    if once is not None and (sonra_once is None or abs(sonra_once - once) > 1e-9):
        raise RuntimeError("Geçmiş maliyet değişecekti, işlem iptal edildi.")
    if abs(cost_at(h, sku, eff) - yeni) > 1e-9:
        raise RuntimeError("Yeni maliyet seçilen anda geçerli olmadı, işlem iptal edildi.")
    d["saved"] = True
    return d


def list_history(conn, sku, now_ms=None):
    """SKU'nun maliyet geçmişi, en yeniden en eskiye."""
    now = int(time.time() * 1000) if now_ms is None else int(now_ms)
    rows = conn.execute(
        "SELECT id, valid_from_ms, cost_incl_vat, source, note, created_at "
        "FROM product_cost_history WHERE sku = ? ORDER BY valid_from_ms DESC",
        (sku,),
    ).fetchall()
    out, current_marked = [], False
    for r in rows:
        gelecek = r[1] > now
        is_current = (not gelecek) and (not current_marked)
        if is_current:
            current_marked = True
        out.append({
            "id": r[0], "valid_from_ms": r[1], "valid_from_text": format_ms(r[1]),
            "cost_incl_vat": r[2], "source": r[3], "note": r[4], "created_at": r[5],
            "is_future": gelecek, "is_current": is_current,
        })
    return out


def correct_history_row(conn, sku, row_id, new_cost, note=None, dry_run=False):
    """HATA DÜZELTMESİ: mevcut bir geçmiş kaydının maliyetini, o kaydın geçerli olduğu
    TÜM dönem için değiştirir (zamdan farklı olarak geçmiş siparişlerin kârı değişir).
    dry_run=True: sadece kaç satırın etkileneceğini döner."""
    new_cost = _gecerli_maliyet(new_cost)
    row = conn.execute(
        "SELECT id, cost_incl_vat, valid_from_ms FROM product_cost_history WHERE id = ? AND sku = ?",
        (row_id, sku),
    ).fetchone()
    if row is None:
        raise ValueError("Geçmiş kaydı bulunamadı.")
    baslangic = row[2]
    sonraki = conn.execute(
        "SELECT MIN(valid_from_ms) FROM product_cost_history WHERE sku = ? AND valid_from_ms > ?",
        (sku, baslangic),
    ).fetchone()[0]
    bitis = sonraki if sonraki is not None else 2 ** 62
    etkilenen = conn.execute(
        """SELECT COUNT(*) FROM order_lines ol
           JOIN orders o ON o.marketplace = ol.marketplace
                        AND o.shipment_package_id = ol.shipment_package_id
           WHERE COALESCE(ol.merchant_sku, ol.barcode) = ?
             AND o.order_date >= ? AND o.order_date < ?""",
        (sku, baslangic, bitis),
    ).fetchone()[0]
    sonuc = {
        "sku": sku, "row_id": row_id, "old_cost": row[1], "new_cost": new_cost,
        "from_text": format_ms(baslangic), "to_text": format_ms(sonraki) if sonraki else "şimdiye kadar",
        "affected_lines": etkilenen, "dry_run": bool(dry_run),
    }
    if dry_run:
        return sonuc

    conn.execute(
        "UPDATE product_cost_history SET cost_incl_vat = ?, source = 'duzeltme', note = ? WHERE id = ?",
        (new_cost, note or "Hata düzeltmesi", row_id),
    )
    son = conn.execute(
        "SELECT id FROM product_cost_history WHERE sku = ? ORDER BY valid_from_ms DESC LIMIT 1", (sku,)
    ).fetchone()
    if son and son[0] == row_id:  # en güncel kayıt düzeltildiyse product_costs da eşitlenir
        rate = vat_rate_for(conn, sku)
        conn.execute(
            "UPDATE product_costs SET cost_incl_vat = ?, cost_excl_vat = ?, "
            "updated_at = datetime('now', 'localtime') WHERE sku = ?",
            (new_cost, round(new_cost / (1 + rate), 6), sku),
        )
    return sonuc
