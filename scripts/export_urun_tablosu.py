import os, sqlite3, time
from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.abspath(os.path.join(HERE, "..", "trendyol_data.db"))
OUT = os.path.abspath(os.path.join(HERE, "..", "urun_tablosu.xlsx"))

con = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)  # salt okunur
con.row_factory = sqlite3.Row
q = lambda sql, p=(): con.execute(sql, p).fetchall()
now_ms = int(time.time() * 1000)

costs = {r["sku"]: r for r in q("SELECT * FROM product_costs")}
hist = {r["sku"]: r["cost_incl_vat"] for r in q(
    "SELECT sku, cost_incl_vat FROM product_cost_history h WHERE valid_from_ms = "
    "(SELECT MAX(valid_from_ms) FROM product_cost_history WHERE sku=h.sku AND valid_from_ms<=?)",
    (now_ms,))}
stock = {(r["marketplace"], r["sku"]): r for r in q("SELECT * FROM product_stock")}
vat_rows = q("SELECT * FROM vat_settings")
default_vat = vat_rows[0]["vat_rate"] if vat_rows else None

# Pazaryeri bazında son sipariş satırından fiyat / komisyon / barkod / ad
last = {}
for r in q("SELECT id, marketplace, COALESCE(merchant_sku, barcode) AS sku, barcode, product_name, "
           "line_unit_price, commission_rate FROM order_lines ORDER BY id"):
    d = last.setdefault((r["marketplace"], r["sku"]), {})
    for k in ("barcode", "product_name", "line_unit_price", "commission_rate"):
        if r[k] is not None:
            d[k] = r[k]

# Ortalama kargo: sadece tek kalemli paketler
cargo = {r["sku"]: r["a"] for r in q(
    "WITH single AS (SELECT marketplace, shipment_package_id FROM order_lines "
    "GROUP BY marketplace, shipment_package_id HAVING COUNT(*)=1) "
    "SELECT COALESCE(l.merchant_sku, l.barcode) AS sku, AVG(c.amount) AS a "
    "FROM order_lines l JOIN single s ON s.marketplace=l.marketplace AND s.shipment_package_id=l.shipment_package_id "
    "JOIN cargo_costs c ON c.marketplace=l.marketplace AND c.shipment_package_id=l.shipment_package_id "
    "WHERE c.amount IS NOT NULL GROUP BY 1")}

skus = sorted(set(costs) | {k[1] for k in stock})
TY, HB = "trendyol", "hepsiburada"
cols = ["SKU", "Ürün adı", "Barkod", "Trendyol content ID", "Hepsiburada ürün kodu",
        "Alış (KDV hariç)", "Alış (KDV dahil)", "KDV oranı",
        "Satış: Trendyol", "Satış: Hepsiburada", "Satış: softhydra.com",
        "Komisyon: Trendyol", "Komisyon: Hepsiburada", "Ort. kargo maliyeti",
        "Stok: Trendyol", "Stok: Hepsiburada"]
money = {6, 7, 9, 10, 11, 14}
pct = {8, 12, 13}

rows = []
for s in skus:
    c = costs.get(s)
    ty, hb = last.get((TY, s), {}), last.get((HB, s), {})
    name = (c["product_name"] if c else None) or ty.get("product_name") or hb.get("product_name")
    incl = hist.get(s) or (c["cost_incl_vat"] if c else None)
    vat = None
    if c and c["cost_incl_vat"] and c["cost_excl_vat"]:
        vat = round(c["cost_incl_vat"] / c["cost_excl_vat"] - 1, 2)
    vat = vat if vat is not None else default_vat
    excl = round(incl / (1 + vat), 2) if incl and vat is not None else None
    sty, shb = stock.get((TY, s)), stock.get((HB, s))
    barcode = (sty["barcode"] if sty else None) or ty.get("barcode")
    hbcode = hb.get("barcode") or (shb["barcode"] if shb else None)
    rate = lambda d: d["commission_rate"] / 100 if d.get("commission_rate") is not None else None
    price = lambda d: round(d["line_unit_price"], 2) if d.get("line_unit_price") is not None else None
    rows.append([s, name, barcode, None, hbcode, excl, incl, vat,
                 price(ty), price(hb), None, rate(ty), rate(hb),
                 round(cargo[s], 2) if s in cargo else None,
                 sty["quantity"] if sty else None, shb["quantity"] if shb else None])

wb = Workbook(); ws = wb.active; ws.title = "Ürünler"
ws.append(cols)
for r in rows:
    ws.append(r)
for cell in ws[1]:
    cell.font = Font(bold=True)
ws.freeze_panes = "A2"
ws.auto_filter.ref = ws.dimensions
for i, h in enumerate(cols, 1):
    letter = get_column_letter(i)
    ws.column_dimensions[letter].width = 42 if i == 2 else max(14, len(h) + 4)
    for row in ws.iter_rows(min_row=2, min_col=i, max_col=i):
        for cell in row:
            if i in money: cell.number_format = '#,##0.00 "₺"'
            elif i == 8: cell.number_format = "0%"
            elif i in pct: cell.number_format = "0.0%"
wb.save(OUT)

print("Ürün sayısı:", len(rows))
for i, h in enumerate(cols):
    n = sum(1 for r in rows if r[i] is None)
    if n: print("  boş %-24s %d" % (h, n))
print("Kaydedildi:", OUT)
