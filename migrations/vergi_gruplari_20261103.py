"""
migrations/vergi_gruplari_20261103.py
-------------------------------------
TEK SEFERLİK migration (Faz 1 / Aşama 1).

- vat_payment, vat_withholding   -> group 'vat_cash' (KDV: nakit çıkışı, kâr kalemi değil)
- provisional_tax                -> group 'income_tax_prepayment'
- tax_withholding (0003 muhtasar) -> group 'business', ad "Muhtasar (hizmet stopajı)"
- finance_settings tablosu + income_tax_provision_rate = 0.20 (yoksa)

Yeni kurulumlarda init_db() bu değerlerle başlar; bu script mevcut DB içindir.

KULLANIM (proje kökünde, önce yedek: backups/ altına):
    python3 migrations/vergi_gruplari_20261103.py            # dry-run
    python3 migrations/vergi_gruplari_20261103.py --apply
"""
import argparse
import os
import sqlite3
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import database  # noqa: E402

CHANGES = [
    ("vat_payment", "vat_cash", None),
    ("vat_withholding", "vat_cash", None),
    ("provisional_tax", "income_tax_prepayment", None),
    ("tax_withholding", "business", "Muhtasar (hizmet stopajı)"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--db", default=os.path.join(ROOT, "trendyol_data.db"))
    args = ap.parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    for key, group, name in CHANGES:
        row = conn.execute("SELECT display_name, group_name, vat_rate FROM expense_type_settings WHERE type_key=?",
                           (key,)).fetchone()
        if row is None:
            print("YOK: %s" % key)
            continue
        print("%-16s %s -> %s%s (vat_rate=%s)" % (key, row["group_name"], group,
                                                   " / ad: %s" % name if name else "", row["vat_rate"]))
        if args.apply:
            conn.execute("UPDATE expense_type_settings SET group_name=?, display_name=COALESCE(?, display_name) "
                         "WHERE type_key=?", (group, name, key))
    if args.apply:
        conn.execute("""CREATE TABLE IF NOT EXISTS finance_settings (
            setting_key TEXT PRIMARY KEY, value TEXT NOT NULL,
            updated_at TEXT DEFAULT (datetime('now', 'localtime')))""")
        for k, v in database.FINANCE_SETTING_DEFAULTS.items():
            conn.execute("INSERT OR IGNORE INTO finance_settings (setting_key, value) VALUES (?, ?)", (k, str(v)))
        conn.commit()
        print("UYGULANDI.")
    else:
        print("dry-run: değişiklik yazılmadı (--apply ile uygula).")


if __name__ == "__main__":
    main()
