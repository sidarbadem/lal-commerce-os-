#!/usr/bin/env python3
"""LAL referans rakam dökümü (SALT OKUNUR, DB'ye yazmaz).

Amaç: maliyet geçmişi değişikliğinden ÖNCE ve SONRA aynı donmuş DB üzerinde
kâr/KDV/borç rakamlarını döküp birebir karşılaştırmak.

Kullanım (proje kökünde, venv açıkken):
    python3 scripts/snapshot_profit.py backups/trendyol_data_yedek_20261015.db onceki.json
    # ... kod değişikliği ...
    python3 scripts/snapshot_profit.py backups/trendyol_data_yedek_20261015.db sonraki.json
    cmp onceki.json sonraki.json && echo "AYNI" || diff onceki.json sonraki.json | head -50

NOT: DB yolu argüman olarak verilir; canlı DB'yi (sync yazıyor) KULLANMAYIN,
yedek kopyasını kullanın, yoksa yeni hakedişler yüzünden rakamlar kayar.
"""
import json
import sqlite3
import sys
from datetime import datetime, timedelta

if len(sys.argv) != 3:
    sys.exit("Kullanım: python3 scripts/snapshot_profit.py <db_yolu> <cikti.json>")

DB_YOLU, CIKTI = sys.argv[1], sys.argv[2]

import os as _os, sys as _sys
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))  # proje kökü
import database  # noqa: E402

database.DB_PATH = DB_YOLU  # get_connection() bu global'i çağrı anında okur

import finance_engine as fe  # noqa: E402


def guvenli(fonksiyon, *args, **kwargs):
    try:
        return fonksiyon(*args, **kwargs)
    except Exception as e:  # hatayı da kayda geçir, karşılaştırmada görünsün
        return {"HATA": f"{type(e).__name__}: {e}"}


def sql(conn, sorgu):
    return [dict(r) for r in conn.execute(sorgu).fetchall()]


raw = sqlite3.connect(DB_YOLU)
raw.row_factory = sqlite3.Row

ilk_ms, son_ms = raw.execute(
    "SELECT MIN(order_date), MAX(order_date) FROM orders WHERE order_date IS NOT NULL"
).fetchone()
ilk = datetime.fromtimestamp(ilk_ms / 1000).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
son = datetime.fromtimestamp(son_ms / 1000)

sonuc = {"db": DB_YOLU, "aylik_ozet": {}, "tum_zamanlar": None, "monthly_profit": None, "sql": {}}

# Ay ay kâr özeti (ham dict'in tamamı kaydedilir)
ay = ilk
while ay <= son:
    sonraki = (ay.replace(day=28) + timedelta(days=4)).replace(day=1)
    bitis = sonraki - timedelta(seconds=1)
    sonuc["aylik_ozet"][ay.strftime("%Y-%m")] = guvenli(
        fe.compute_profit_summary, start_dt=ay, end_dt=bitis
    )
    ay = sonraki

# Tüm zamanlar (KDV alanları dahil toplamlar burada)
sonuc["tum_zamanlar"] = guvenli(fe.compute_profit_summary, start_dt=ilk, end_dt=son + timedelta(days=1))

# Aylık grafik fonksiyonu
sonuc["monthly_profit"] = guvenli(fe.monthly_profit, ilk, son + timedelta(days=1))

# Doğrudan SQL toplamları (büyüme sayfası ve toptancı borcu mantığına denk)
sonuc["sql"]["borc_hareketleri"] = sql(
    raw,
    "SELECT tedarikci_id, tip, COUNT(*) AS adet, ROUND(SUM(tutar),2) AS toplam "
    "FROM tedarikci_borc_hareketleri GROUP BY 1,2 ORDER BY 1,2",
)
# Maliyet geçmişi tablosu varsa SİPARİŞ TARİHİNE göre geçerli maliyet (büyüme sayfasıyla
# aynı mantık); yoksa (eski DB) güncel product_costs maliyeti.
_gecmis_var = raw.execute(
    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='product_cost_history'"
).fetchone()
if _gecmis_var:
    _birim = ("COALESCE((SELECT h.cost_incl_vat FROM product_cost_history h "
              "WHERE h.sku = COALESCE(ol.merchant_sku, ol.barcode) AND h.valid_from_ms <= o.order_date "
              "ORDER BY h.valid_from_ms DESC LIMIT 1), pc.cost_incl_vat, 0)")
else:
    _birim = "COALESCE(pc.cost_incl_vat,0)"
sonuc["sql"]["sku_maliyet_toplami"] = sql(
    raw,
    "SELECT COALESCE(ol.merchant_sku, ol.barcode) AS sku, SUM(ol.quantity) AS adet, "
    f"ROUND(SUM({_birim} * COALESCE(ol.quantity,0)),2) AS maliyet "
    "FROM order_lines ol "
    "JOIN orders o ON o.marketplace=ol.marketplace AND o.shipment_package_id=ol.shipment_package_id "
    "LEFT JOIN product_costs pc ON pc.sku = COALESCE(ol.merchant_sku, ol.barcode) "
    "GROUP BY 1 ORDER BY 1",
)
sonuc["sql"]["manuel_siparis_kalemleri"] = sql(
    raw,
    "SELECT sku, SUM(quantity) AS adet, ROUND(SUM(quantity*unit_cost),2) AS maliyet "
    "FROM manuel_siparis_kalemleri GROUP BY 1 ORDER BY 1",
)

with open(CIKTI, "w", encoding="utf-8") as f:
    json.dump(sonuc, f, ensure_ascii=False, indent=1, sort_keys=True, default=str)

hatali = [k for k, v in sonuc["aylik_ozet"].items() if isinstance(v, dict) and "HATA" in v]
print(f"Yazıldı: {CIKTI}")
print(f"Ay sayısı: {len(sonuc['aylik_ozet'])} | hatalı ay: {hatali or 'yok'}")
if isinstance(sonuc["tum_zamanlar"], dict) and "HATA" in sonuc["tum_zamanlar"]:
    print("UYARI tum_zamanlar:", sonuc["tum_zamanlar"]["HATA"])
