import database
import finance_engine as fe


def test_overhead_excludes_commission_invoices_from_platform_fee():
    other = {"trendyol": {
        "DeductionInvoices": {"net": 1000.0},
        "_kargo_within_deduction_invoices": {"net": 200.0},
        "_komisyon_within_deduction_invoices": {"net": 500.0},
        "Stoppage": {"net": 10.0},
    }}
    overhead, _ = fe._compute_overhead_by_marketplace(other, {}, ["trendyol"])
    assert overhead["trendyol"]["platform_fee"] == 300.0
    # Stopaj mahsup olarak ayrıdır; yalnızca 300 TL KDV hariç hizmet kesintisi
    # faaliyet kârına gider.
    assert overhead["trendyol"]["total"] == 300.0


def test_load_other_totals_separates_commission_invoices(db):
    rows = [
        ("t1", "trendyol", None, "DeductionInvoices", "Komisyon Faturası",
         "01 Eylül - 07 Eylül arası Trendyol hakediş tutarı", 400.0, 0.0, 1788000000000),
        ("t2", "trendyol", None, "DeductionInvoices", "Reklam Bedeli",
         "Satıcı Reklamı Satın Alma", 100.0, 0.0, 1788000000000),
    ]
    with database.get_connection() as conn:
        for r in rows:
            conn.execute(
                "INSERT INTO other_financials (id, marketplace, shipment_package_id, transaction_type, "
                "raw_transaction_type, description, debt, credit, transaction_date) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", r)
        conn.commit()
        totals = fe._load_other_financial_totals(conn, 1787000000000, 1789000000000)
    t = totals["trendyol"]
    assert t["DeductionInvoices"]["net"] == 500.0
    assert t["_komisyon_within_deduction_invoices"]["net"] == 400.0
    assert "_kargo_within_deduction_invoices" not in t
