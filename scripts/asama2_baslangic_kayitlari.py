#!/usr/bin/env python3
"""Faz 1 / Aşama 2 başlangıç kayıtları (03.11.2026, kullanıcı onaylı değerler).

Varsayılan: yazılacak satırları LİSTELER, DB'ye yazmaz. Yazmak için --apply.
Önce yedek: sqlite3 trendyol_data.db ".backup backups/<ad>.db"

Kullanım (proje kökünde): python3 scripts/asama2_baslangic_kayitlari.py [--apply]
"""
import argparse
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT)
sys.path.insert(0, ROOT)

import database  # noqa: E402
import supplier_ledger  # noqa: E402

WATALINA = "Watalina"
OWN_SKU = "SH-10TF-BG"

ACCOUNTS = [
    # ad, tur, borca_ayrilmis, odeme_gunu, notlar
    ("Enpara", "banka", 0, None, None),
    ("ikas", "odeme_altyapisi", 0, 4, "Ödeme günü Cuma"),
    ("Midas", "altin", 1, None, "Anne altın borcuna ayrılmış; serbest nakde dahil değil"),
]
BALANCES = [
    # hesap, tarih, bakiye, altin_adet, birim_fiyat, birim_maliyet, notlar
    ("Enpara", "2026-11-03", 56360.10, None, None, None, "Bugünkü HB ödemesi dahil"),
    ("ikas", "2026-11-03", 7100.00, None, None, None, "06.11.2026 Cuma hesaba geçecek"),
    ("Midas", "2026-11-03", None, 1387, 69.30, 71.16, "13,87 g"),
]
CARDS = [
    # ad, limit, kesim, son_odeme, guncel_borc, tarih, notlar
    ("Enpara Kart", 41000.00, 25, 5, None, None, None),
    ("İş Bankası Kart", 114536.00, 25, 5, 91687.00, "2026-11-03",
     "Kullanılabilir 22.849; 91.666,70 TL'si SH-10TF-BG taksitleri. Ayrı Kasım ekstresi yok."),
]
STATEMENTS = [("Enpara Kart", "2026-11", 40041.00, "2026-11-05")]
INSTALLMENTS = [("İş Bankası Kart", "SH-10TF-BG 50 set alımı", 18333.40, 6, 5, "2026-10-05", OWN_SKU)]
SCHEDULED = [
    # aciklama, kategori, tutar, baslangic, tekrar, ay_sonu, bitis, notlar
    ("Bağ-Kur", "vergi_sgk", 10156.73, "2026-11-30", "aylik", 1, None, None),
    ("Anne altın borcu", "borc_aile", 40000.00, "2026-12-15", "aylik", 0, "2027-04-15",
     "kalan 6 Cumhuriyet altını, Midas'taki 13,87 g düşülecek, son ödeme altın fiyatına göre değişir"),
]
OPENING = (217540.00, "2026-10-31", "2026-11-30", "Watalina ekstresine göre (31.10.2026, KDV dahil, Ekim alımları)")
OWN_STOCK = 14
MIN_RESERVE = 30000.0


def plan(conn):
    t = conn.execute("SELECT id FROM tedarikciler WHERE ad=?", (WATALINA,)).fetchone()
    if not t:
        raise SystemExit("Watalina tedarikçisi yok")
    skus = [r["sku"] for r in conn.execute("SELECT sku FROM product_costs WHERE sku IS NOT NULL ORDER BY sku")]
    print(f"[product_costs] tedarikci_id = {t['id']} ({WATALINA}) -> {len(skus)} SKU")
    print(f"[product_costs] {OWN_SKU}: kendi_stok_kalan = {OWN_STOCK}, kendi_stok_sayim_ms = şimdi")
    a, islem, vade, acik = OPENING
    print(f"[tedarikci_borc_hareketleri] acilis {a:,.2f} TL, islem {islem}, vade {vade}, '{acik}'")
    for r in ACCOUNTS:
        print(f"[cash_accounts] {r}")
    for r in BALANCES:
        print(f"[cash_balances] {r}" + (f" -> bakiye {r[3] * r[4]:,.2f}" if r[2] is None else ""))
    for r in CARDS:
        print(f"[credit_cards] {r}")
    for r in STATEMENTS:
        print(f"[card_statements] {r} ödenmedi")
    for r in INSTALLMENTS:
        print(f"[installment_plans] {r}")
    for r in SCHEDULED:
        print(f"[scheduled_payments] {r}")
    print(f"[finance_settings] min_cash_reserve = {MIN_RESERVE}")
    return t["id"], skus


def apply(conn, tid):
    import nakit
    conn.execute("UPDATE product_costs SET tedarikci_id=? WHERE sku IS NOT NULL", (tid,))
    conn.execute("UPDATE product_costs SET kendi_stok_kalan=?, kendi_stok_sayim_ms=? WHERE sku=?",
                 (OWN_STOCK, int(time.time() * 1000), OWN_SKU))
    a, islem, vade, acik = OPENING
    if not conn.execute("SELECT 1 FROM tedarikci_borc_hareketleri WHERE tedarikci_id=? AND tip='acilis'", (tid,)).fetchone():
        supplier_ledger.add_movement(conn, tid, "acilis", a, acik, islem, vade)
    ids = {}
    for ad, tur, borca, gun, notlar in ACCOUNTS:
        conn.execute("INSERT OR IGNORE INTO cash_accounts (ad, tur, borca_ayrilmis, odeme_gunu, notlar) VALUES (?,?,?,?,?)",
                     (ad, tur, borca, gun, notlar))
        ids[ad] = conn.execute("SELECT id FROM cash_accounts WHERE ad=?", (ad,)).fetchone()[0]
    for ad, tarih, bakiye, adet, fiyat, maliyet, notlar in BALANCES:
        if not conn.execute("SELECT 1 FROM cash_balances WHERE hesap_id=? AND tarih=?", (ids[ad], tarih)).fetchone():
            nakit.add_balance(conn, ids[ad], tarih, bakiye, adet, fiyat, maliyet, notlar)
    cids = {}
    for ad, lim, kesim, odeme, borc, tarih, notlar in CARDS:
        conn.execute("""INSERT OR IGNORE INTO credit_cards (ad, limit_tutar, kesim_gunu, son_odeme_gunu, guncel_borc,
                        guncel_borc_tarihi, notlar) VALUES (?,?,?,?,?,?,?)""", (ad, lim, kesim, odeme, borc, tarih, notlar))
        cids[ad] = conn.execute("SELECT id FROM credit_cards WHERE ad=?", (ad,)).fetchone()[0]
    for kart, donem, tutar, son in STATEMENTS:
        conn.execute("INSERT OR IGNORE INTO card_statements (kart_id, donem, tutar, son_odeme_tarihi) VALUES (?,?,?,?)",
                     (cids[kart], donem, tutar, son))
    for kart, acik, tutar, toplam, kalan, ilk, sku in INSTALLMENTS:
        if not conn.execute("SELECT 1 FROM installment_plans WHERE kart_id=? AND aciklama=?", (cids[kart], acik)).fetchone():
            conn.execute("""INSERT INTO installment_plans (kart_id, aciklama, taksit_tutari, toplam_taksit, kalan_taksit,
                            ilk_odeme_tarihi, sku) VALUES (?,?,?,?,?,?,?)""", (cids[kart], acik, tutar, toplam, kalan, ilk, sku))
    for acik, kat, tutar, bas, tekrar, ay_sonu, bitis, notlar in SCHEDULED:
        if not conn.execute("SELECT 1 FROM scheduled_payments WHERE aciklama=?", (acik,)).fetchone():
            conn.execute("""INSERT INTO scheduled_payments (aciklama, kategori, tutar, baslangic_tarihi, tekrar, ay_sonu,
                            bitis_tarihi, notlar) VALUES (?,?,?,?,?,?,?,?)""", (acik, kat, tutar, bas, tekrar, ay_sonu, bitis, notlar))
    conn.commit()
    database.save_finance_setting("min_cash_reserve", MIN_RESERVE)
    print("reconcile:", supplier_ledger.reconcile(conn))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    if args.apply:
        database.init_db()  # Aşama 2 tablolarını/migration'larını uygular (idempotent)
    with database.get_connection() as conn:
        tid, _ = plan(conn)
        if args.apply:
            apply(conn, tid)
            print("YAZILDI.")
        else:
            print("Önizleme: yazmak için --apply")


if __name__ == "__main__":
    main()
