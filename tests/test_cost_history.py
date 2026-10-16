import sqlite3
import time

import pytest

import cost_history as ch

GUN = 24 * 3600 * 1000


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE product_costs (sku TEXT PRIMARY KEY, cost_incl_vat REAL);
        CREATE TABLE orders (marketplace TEXT, shipment_package_id INTEGER, order_date INTEGER,
                             PRIMARY KEY (marketplace, shipment_package_id));
        CREATE TABLE order_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, marketplace TEXT,
                                  shipment_package_id INTEGER, barcode TEXT, merchant_sku TEXT,
                                  quantity INTEGER);
    """)
    ch.ensure_table(c)
    yield c
    c.close()


def _siparis(c, spid, tarih_ms, sku):
    c.execute("INSERT INTO orders VALUES ('trendyol', ?, ?)", (spid, tarih_ms))
    c.execute("INSERT INTO order_lines (marketplace, shipment_package_id, barcode, merchant_sku, quantity) "
              "VALUES ('trendyol', ?, ?, ?, 1)", (spid, f"b{spid}", sku))


def test_backfill_idempotent(conn):
    conn.execute("INSERT INTO product_costs VALUES ('A', 100.0), ('B', NULL)")
    assert ch.backfill_from_product_costs(conn) == 1  # NULL maliyetli B atlanır
    assert ch.backfill_from_product_costs(conn) == 0
    h = ch.load_history(conn)
    assert h["A"] == ([0], [100.0])
    assert "B" not in h


def test_zam_gecmisi_degistirmez(conn):
    conn.execute("INSERT INTO product_costs VALUES ('A', 1445.0)")
    ch.backfill_from_product_costs(conn)
    simdi = int(time.time() * 1000)
    eski, yeni = simdi - 10 * GUN, simdi + 1000  # yeni sipariş, zamdan sonra

    guncel = ch.apply_cost_change(conn, "A", 1730.0, effective_ms=simdi - 1 * GUN)
    assert guncel == 1730.0

    h = ch.load_history(conn)
    assert ch.cost_at(h, "A", eski, fallback=999) == 1445.0   # geçmiş aynı
    assert ch.cost_at(h, "A", simdi, fallback=999) == 1730.0  # yeni satış yeni maliyet
    assert ch.cost_at(h, "A", yeni, fallback=999) == 1730.0


def test_gecmis_yokken_ilk_zam_mevcut_maliyeti_korur(conn):
    conn.execute("INSERT INTO product_costs VALUES ('A', 500.0)")  # backfill ÇALIŞMADI
    ch.apply_cost_change(conn, "A", 600.0)
    h = ch.load_history(conn)
    assert ch.cost_at(h, "A", 1000) == 500.0  # çok eski sipariş eski maliyetle


def test_yeni_sku_tek_baslangic_kaydi(conn):
    assert ch.apply_cost_change(conn, "YENI", 250.0) == 250.0
    h = ch.load_history(conn)
    assert h["YENI"] == ([0], [250.0])


def test_gelecek_tarih_ve_gecersiz_maliyet_reddedilir(conn):
    conn.execute("INSERT INTO product_costs VALUES ('A', 10.0)")
    with pytest.raises(ValueError):
        ch.apply_cost_change(conn, "A", 20.0, effective_ms=int(time.time() * 1000) + 5 * GUN)
    with pytest.raises(ValueError):
        ch.apply_cost_change(conn, "A", -1.0)
    with pytest.raises(ValueError):
        ch.apply_cost_change(conn, "A", None)


def test_ayni_anda_ikinci_kayit_uzerine_yazar(conn):
    conn.execute("INSERT INTO product_costs VALUES ('A', 10.0)")
    ch.backfill_from_product_costs(conn)
    t = int(time.time() * 1000) - GUN
    ch.apply_cost_change(conn, "A", 20.0, effective_ms=t)
    ch.apply_cost_change(conn, "A", 25.0, effective_ms=t)
    h = ch.load_history(conn)
    assert h["A"] == ([0, t], [10.0, 25.0])


def test_tarih_bilinmiyorsa_fallback(conn):
    assert ch.cost_at({}, "A", None, fallback=42.0) == 42.0
    assert ch.cost_at({"A": ([0], [1.0])}, "A", None, fallback=42.0) == 42.0
    assert ch.cost_at({}, "YOK", 5, fallback=None) is None


def test_onizleme_sayilari(conn):
    conn.execute("INSERT INTO product_costs VALUES ('A', 10.0)")
    simdi = int(time.time() * 1000)
    _siparis(conn, 1, simdi - 5 * GUN, "A")
    _siparis(conn, 2, simdi - 2 * GUN, "A")
    _siparis(conn, 3, simdi + 1000, "A")
    _siparis(conn, 4, simdi - 5 * GUN, "BASKA")
    p = ch.preview_change(conn, "A", effective_ms=simdi - 3 * GUN)
    assert p["unchanged_lines"] == 1 and p["affected_lines"] == 2


def test_record_changes_degismeyen_kayit_eklemez(conn):
    conn.execute("INSERT INTO product_costs VALUES ('A', 100.0)")
    ch.backfill_from_product_costs(conn)
    assert ch.record_changes(conn, [{"sku": "A", "cost_incl_vat": 100.0}]) == []
    assert ch.load_history(conn)["A"] == ([0], [100.0])


def test_record_changes_degisen_maliyet_yeni_kayit_gecmis_ayni(conn):
    conn.execute("INSERT INTO product_costs VALUES ('A', 100.0)")
    ch.backfill_from_product_costs(conn)
    simdi = int(time.time() * 1000)
    assert ch.record_changes(conn, [{"sku": "A", "cost_incl_vat": 120.0}], now_ms=simdi) == ["A"]
    h = ch.load_history(conn)
    assert ch.cost_at(h, "A", simdi - 1) == 100.0
    assert ch.cost_at(h, "A", simdi) == 120.0


def test_record_changes_yeni_sku_ve_bos_maliyet(conn):
    out = ch.record_changes(conn, [{"sku": "YENI", "cost_incl_vat": 50.0},
                                   {"sku": "BOS", "cost_incl_vat": None},
                                   {"sku": None, "cost_incl_vat": 5.0}])
    assert out == []
    h = ch.load_history(conn)
    assert h == {"YENI": ([0], [50.0])}


def test_costbook_ve_load_history_safe():
    c = sqlite3.connect(":memory:")
    assert ch.load_history_safe(c) == {}  # tablo yok -> boş, hata yok
    b = ch.CostBook({"A": 1})
    assert b.get("A") == 1 and b.history == {}
