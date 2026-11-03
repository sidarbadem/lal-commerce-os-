"""SH-10TF-BG maliyet düzeltmesi (03.11.2026).

Kendi alım: 50 set, fatura 110.000,40 TL KDV dahil -> 2.200,01 TL/set.
LAL'deki 2.575 TL yerine 01.09.2026'dan itibaren 2.200,01 TL geçerli olur.
Öncesindeki siparişlere dokunulmaz. Ağu–Eki taslak aylık raporları yeniden üretilir.

Çalıştırma (proje kökünde): python3 scripts/maliyet_sh10tfbg_duzelt.py
"""
import os, sys, sqlite3, datetime as dt
from zoneinfo import ZoneInfo

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(ROOT); sys.path.insert(0, ROOT)
import database, cost_history as ch, monthly_reports as mr

SKU, YENI = "SH-10TF-BG", 2200.01
EFF = int(dt.datetime(2026, 9, 1, tzinfo=ZoneInfo("Europe/Istanbul")).timestamp() * 1000)
NOT = ("Kendi alım: 50 set, fatura 110.000,40 TL KDV dahil (İş Bankası 6 taksit). "
       "Geçerlilik 01.09.2026 tahmini, fatura tarihiyle teyit edilecek")

yedek = os.path.join("backups", "trendyol_data_20261103_pre_sh10tfbg_maliyet.db")
src = sqlite3.connect(database.DB_PATH); dst = sqlite3.connect(yedek)
src.backup(dst); dst.close(); src.close()
print("Yedek:", yedek)

with database.get_connection() as c:
    d = ch.change_cost(c, SKU, YENI, effective_ms=EFF, source="fatura", note=NOT)
    c.commit()
    print("Maliyet güncellendi:", c.execute(
        "SELECT cost_incl_vat, cost_excl_vat FROM product_costs WHERE sku=?", (SKU,)).fetchone()[:])

for p in ("2026-08", "2026-09", "2026-10"):
    print("Rapor:", mr.generate_report(p, force=True))
print("Tamam.")
