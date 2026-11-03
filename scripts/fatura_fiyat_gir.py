#!/usr/bin/env python3
"""Watalina faturası UD12026000000015 (30.09.2026) fiyatlarını maliyet geçmişine girer.

Varsayılan mod ÖNİZLEME: DB'ye hiçbir şey yazmaz. Yazmak için --uygula.
Geçerlilik zamanı İstanbul saatiyle verilir; gelecekteki bir zaman da olabilir
(sipariş maliyeti sipariş tarihine göre seçildiği için, o ana kadarki siparişler
eski maliyetle, sonrakiler yeni maliyetle hesaplanır).

Kullanım (proje kökünde, canlı DB'ye yazar; önce yedek al):
    venv/bin/python3 scripts/fatura_fiyat_gir.py
    venv/bin/python3 scripts/fatura_fiyat_gir.py --uygula
    venv/bin/python3 scripts/fatura_fiyat_gir.py --gecerlilik "2026-10-16 23:00" --uygula
"""
import argparse
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # proje kökü
import cost_history as ch
import database

TZ = ZoneInfo("Europe/Istanbul")
VARSAYILAN_GECERLILIK = "2026-10-16 23:00"
NOT = "Watalina fatura UD12026000000015 (30.09.2026)"
UYARI_ESIGI = 0.40  # bu orandan büyük değişimler ⚠ ile işaretlenir

# SKU: KDV DAHİL birim maliyet (faturadaki KDV hariç birim fiyat x 1,2)
FIYATLAR = {
    "SFHY-3-GRS": 1730.0,
    "SH-10L-SA-5M": 720.0,
    "SH-3F-10-5M-GAC": 390.0,
    "SH-304KM-01": 365.0,
    "SH-FILTER-3LU-10INC": 140.0,
    "SH-PAC-MP-01": 175.0,
    "SH-SILIFOZ-01": 180.0,
    "TL-RO122": 745.0,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--uygula", action="store_true")
    ap.add_argument("--gecerlilik", default=VARSAYILAN_GECERLILIK,
                    help='"YYYY-MM-DD SS:DD" (İstanbul saati)')
    a = ap.parse_args()

    eff_dt = datetime.strptime(a.gecerlilik, "%Y-%m-%d %H:%M").replace(tzinfo=TZ)
    eff = int(eff_dt.timestamp() * 1000)
    now = int(time.time() * 1000)
    simdi = datetime.now(TZ)
    gelecek = eff > now

    print(f"Şu an (İstanbul)      : {simdi:%Y-%m-%d %H:%M}")
    print(f"Geçerlilik başlangıcı : {eff_dt:%Y-%m-%d %H:%M}"
          + (f"  (GELECEK, {(eff - now) // 60000} dk sonra)" if gelecek else "  (geçmiş)"))
    print(f"Mod                   : {'UYGULA (DB yazılır)' if a.uygula else 'ÖNİZLEME (DB yazılmaz)'}\n")

    with database.get_connection() as c:
        ch.ensure_table(c)

        # Koruma: sipariş zamanları gerçek epoch mu? (Trendyol İstanbul-saati-UTC kayması)
        mx = c.execute("SELECT MAX(order_date) FROM orders").fetchone()[0]
        if mx and mx > now + 5 * 60 * 1000:
            sys.exit("DUR: en yeni sipariş tarihi şu andan ileride görünüyor "
                     "(epoch kayması olabilir). Hiçbir şey yazılmadı.")

        urunler, eksik = {}, []
        for sku in FIYATLAR:
            r = c.execute(
                "SELECT sku, product_name, cost_incl_vat, cost_excl_vat FROM product_costs WHERE sku = ?",
                (sku,),
            ).fetchone()
            (urunler.__setitem__(sku, r) if r else eksik.append(sku))
        if eksik:
            sys.exit(f"DUR: product_costs'ta bulunamayan SKU: {eksik}. Hiçbir şey yazılmadı.")

        history = ch.load_history(c)
        print(f"{'SKU':22s} {'ŞİMDİ':>9s} {'YENİ':>9s} {'FARK':>8s}  "
              f"{'ESKİ KALAN SATIR':>16s} {'YENİ MALİYETLİ':>14s}")
        isaretli = []
        for sku, yeni in FIYATLAR.items():
            r = urunler[sku]
            eski = r["cost_incl_vat"]
            fark = (yeni - eski) / eski if eski else 0.0
            p = ch.preview_change(c, sku, effective_ms=eff)
            isaret = ""
            if abs(fark) > UYARI_ESIGI:
                isaret = "  ⚠ büyük fark: SKU eşleşmesini doğrula"
                isaretli.append(sku)
            gecmis_maliyet = ch.cost_at(history, sku, now, fallback=eski)
            if abs(gecmis_maliyet - eski) > 1e-9:
                isaret += "  ⚠ geçmiş tablosu ile product_costs uyuşmuyor"
            print(f"{sku:22s} {eski:9.2f} {yeni:9.2f} {fark * 100:+7.1f}%  "
                  f"{p['unchanged_lines']:16d} {p['affected_lines']:14d}{isaret}")
        print()

        if not a.uygula:
            print("Önizleme bitti, hiçbir şey yazılmadı. Uygulamak için --uygula ekle.")
            return

        # --- UYGULA (tek işlem: hata olursa hiçbiri yazılmaz) ---
        yazilan = 0
        for sku, yeni in FIYATLAR.items():
            r = urunler[sku]
            eski = r["cost_incl_vat"]
            satir = c.execute(
                "SELECT cost_incl_vat FROM product_cost_history WHERE sku = ? AND valid_from_ms = ?",
                (sku, eff),
            ).fetchone()
            if abs(eski - yeni) < 1e-9 and satir is not None and abs(satir[0] - yeni) < 1e-9:
                print(f"[ATLA] {sku}: zaten girilmiş")
                continue

            if sku not in history:  # geçmişi olmayan SKU: eski maliyeti başlangıç kaydı yap
                c.execute(
                    "INSERT OR IGNORE INTO product_cost_history "
                    "(sku, cost_incl_vat, valid_from_ms, source, note) VALUES (?, ?, 0, 'backfill', 'Önceki maliyet')",
                    (sku, eski),
                )
            once = ch.cost_at(ch.load_history(c), sku, eff - 1)

            c.execute(
                """INSERT INTO product_cost_history (sku, cost_incl_vat, valid_from_ms, source, note)
                   VALUES (?, ?, ?, 'fatura', ?)
                   ON CONFLICT(sku, valid_from_ms) DO UPDATE SET
                       cost_incl_vat = excluded.cost_incl_vat, source = excluded.source, note = excluded.note""",
                (sku, yeni, eff, NOT),
            )
            # KDV hariç da aynı anda güncellenir: motor KDV oranını incl/excl'den türetiyor
            c.execute(
                "UPDATE product_costs SET cost_incl_vat = ?, cost_excl_vat = ?, "
                "updated_at = datetime('now', 'localtime') WHERE sku = ?",
                (yeni, round(yeni / 1.2, 6), sku),
            )

            h = ch.load_history(c)
            sonra_eff = ch.cost_at(h, sku, eff)
            sonra_once = ch.cost_at(h, sku, eff - 1)
            if sonra_eff is None or abs(sonra_eff - yeni) > 1e-9:
                raise RuntimeError(f"{sku}: eff anında maliyet {sonra_eff}, beklenen {yeni}. "
                                   "(Sonrasında başka bir geçmiş kaydı var mı?) Hiçbir şey yazılmadı.")
            if once is not None and (sonra_once is None or abs(sonra_once - once) > 1e-9):
                raise RuntimeError(f"{sku}: geçmiş maliyet değişti ({once} -> {sonra_once}). Hiçbir şey yazılmadı.")
            print(f"[OK ] {sku}: {eski:.2f} -> {yeni:.2f}  (öncesi {once:.2f} aynı kaldı)")
            yazilan += 1

        print(f"\n{yazilan} kalem yazıldı.")
        if gelecek:
            print("\nÖNEMLİ: Geçerlilik ileride. Ürünler sayfası yeni maliyeti şimdiden gösterir ama "
                  f"{eff_dt:%H:%M}'a kadar siparişler eski maliyetle hesaplanır.\n"
                  "Bu 8 SKU'yu o saate kadar formdan KAYDETME: kaydedersen değişiklik o andan itibaren başlar.")
        if isaretli:
            print(f"\n⚠ Büyük farklı kalemler: {', '.join(isaretli)} (SKU eşleşmesini bir kez daha kontrol et).")


if __name__ == "__main__":
    main()
