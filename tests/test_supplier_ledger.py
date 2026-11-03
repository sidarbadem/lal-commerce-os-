"""Faz 1 / Aşama 2: tedarikçi (Watalina) borç defteri — alış/iade, kendi stok, vade, mutabakat."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import supplier_ledger as sl
from database import get_connection, upsert_order_lines, upsert_orders

TZ = ZoneInfo("Europe/Istanbul")


def _ms(y, m, d, h=12):
    return int(datetime(y, m, d, h, tzinfo=TZ).timestamp() * 1000)


def _setup(conn, kendi_kalan=None, sayim_ms=None):
    conn.execute("INSERT INTO tedarikciler (id, ad) VALUES (4, 'Watalina')")
    conn.execute("INSERT INTO product_costs (sku, cost_incl_vat, tedarikci_id) VALUES ('A', 100, 4)")
    conn.execute("INSERT INTO product_costs (sku, cost_incl_vat, tedarikci_id, kendi_stok_kalan, kendi_stok_sayim_ms) "
                 "VALUES ('OWN', 2200.01, 4, ?, ?)", (kendi_kalan, sayim_ms))
    conn.commit()


def _order(spid, sku, qty, when, status="Delivered", mp="trendyol"):
    upsert_orders([{
        "shipment_package_id": spid, "marketplace": mp, "order_number": f"O{spid}", "order_date": when,
        "status": status, "customer": "T", "cargo_provider": "X",
        "gross_amount": 100.0 * qty, "discount_amount": 0.0, "net_amount": 100.0 * qty}])
    upsert_order_lines([{
        "shipment_package_id": spid, "marketplace": mp, "barcode": sku, "merchant_sku": sku,
        "product_name": sku, "quantity": qty, "line_unit_price": 100.0, "commission_rate": 10.0}])


def _moves(conn, tip=None):
    q = "SELECT * FROM tedarikci_borc_hareketleri" + (" WHERE tip=?" if tip else "")
    return [dict(r) for r in conn.execute(q, (tip,) if tip else ())]


def test_purchase_written_once_with_due_date(db):
    with get_connection() as conn:
        _setup(conn)
    _order(1, "A", 2, _ms(2026, 11, 2))
    _order(1, "A", 2, _ms(2026, 11, 2))  # tekrar senkron
    with get_connection() as conn:
        sl.reconcile(conn)
        alis = _moves(conn, "alis")
    assert len(alis) == 1
    assert alis[0]["tutar"] == 200.0
    assert alis[0]["vade_tarihi"] == "2026-12-31"
    assert alis[0]["islem_tarihi"] == "2026-11-02"


def test_orders_before_ledger_start_ignored(db):
    with get_connection() as conn:
        _setup(conn)
    _order(1, "A", 1, _ms(2026, 10, 31, 23))
    with get_connection() as conn:
        assert _moves(conn, "alis") == []


def test_cancellation_reverses_and_claim_rejection_restores(db):
    with get_connection() as conn:
        _setup(conn)
    _order(1, "A", 1, _ms(2026, 11, 3), mp="hepsiburada")
    _order(1, "A", 1, _ms(2026, 11, 3), status="ClaimCreated", mp="hepsiburada")
    with get_connection() as conn:
        assert sl.balance(conn, 4) == 0
        assert len(_moves(conn, "iade")) == 1
    _order(1, "A", 1, _ms(2026, 11, 3), status="Delivered", mp="hepsiburada")  # talep reddedildi
    with get_connection() as conn:
        assert _moves(conn, "iade") == []
        assert sl.balance(conn, 4) == 100.0


def test_own_stock_consumed_first_then_supplier(db):
    with get_connection() as conn:
        _setup(conn, kendi_kalan=2, sayim_ms=_ms(2026, 11, 1, 0))
    _order(1, "OWN", 1, _ms(2026, 11, 2))
    _order(2, "OWN", 2, _ms(2026, 11, 3))  # 1 kendi stoktan, 1 Watalina'dan
    with get_connection() as conn:
        alis = _moves(conn, "alis")
        kalan = conn.execute("SELECT kendi_stok_kalan FROM product_costs WHERE sku='OWN'").fetchone()[0]
    assert kalan == 0
    assert len(alis) == 1 and alis[0]["tutar"] == pytest.approx(2200.01)
    _order(1, "OWN", 1, _ms(2026, 11, 2), status="Returned")  # kendi stoktan satılan iade -> stoğa döner
    with get_connection() as conn:
        assert conn.execute("SELECT kendi_stok_kalan FROM product_costs WHERE sku='OWN'").fetchone()[0] == 1


def test_sales_before_count_date_do_not_consume_own_stock(db):
    with get_connection() as conn:
        _setup(conn, kendi_kalan=14, sayim_ms=_ms(2026, 11, 3, 18))
    _order(1, "OWN", 1, _ms(2026, 11, 2))  # sayımdan önce: 14'e zaten yansımış
    with get_connection() as conn:
        assert conn.execute("SELECT kendi_stok_kalan FROM product_costs WHERE sku='OWN'").fetchone()[0] == 14
        assert _moves(conn, "alis") == []


def test_orphan_placeholder_purchase_removed(db):
    with get_connection() as conn:
        _setup(conn)
    _order(-5, "A", 1, _ms(2026, 11, 2), mp="hepsiburada")
    with get_connection() as conn:
        assert len(_moves(conn, "alis")) == 1
        conn.execute("DELETE FROM order_lines WHERE shipment_package_id=-5")
        conn.commit()
        sl.reconcile(conn)
        assert _moves(conn, "alis") == []


def test_opening_payment_due_buckets_fifo(db):
    with get_connection() as conn:
        _setup(conn)
        sl.add_movement(conn, 4, "acilis", 217540, "Watalina ekstresine göre", "2026-10-31", "2026-11-30")
    _order(1, "A", 3, _ms(2026, 11, 2))
    with get_connection() as conn:
        sl.add_movement(conn, 4, "odeme", 17540, "kısmi", "2026-11-20")
        b = sl.due_buckets(conn, 4, today=date(2026, 11, 3))
        assert b == {"vadesiGecmis": 0.0, "buAy": 200000.0, "gelecekAy": 300.0, "sonrasi": 0.0}
        assert sl.balance(conn, 4) == 200300.0


def test_month_due_override_and_invoice_reconciliation(db):
    with get_connection() as conn:
        _setup(conn)
    _order(1, "A", 1, _ms(2026, 11, 2))
    with get_connection() as conn:
        sl.set_month_due(conn, 4, "2026-11", "2027-01-02")
        conn.commit()
    _order(2, "A", 1, _ms(2026, 11, 5))
    with get_connection() as conn:
        assert {m["vade_tarihi"] for m in _moves(conn, "alis")} == {"2027-01-02"}
        sl.set_invoice(conn, 4, "2026-11", 250.0)
        rec = sl.reconciliation(conn, 4)
    assert rec == [{"ay": "2026-11", "sistem": 200.0, "fatura": 250.0, "fark": 50.0, "aciklama": None}]
    with get_connection() as conn:
        assert sl.balance(conn, 4) == 200.0  # fark otomatik düzeltilmez


def test_manual_movement_validation(db):
    with get_connection() as conn:
        _setup(conn)
        with pytest.raises(ValueError):
            sl.add_movement(conn, 4, "alis", 1, "", "2026-11-01")
        with pytest.raises(ValueError):
            sl.add_movement(conn, 4, "odeme", -5, "", "2026-11-01")
