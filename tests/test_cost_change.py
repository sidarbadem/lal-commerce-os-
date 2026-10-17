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
        CREATE TABLE product_costs (sku TEXT PRIMARY KEY, product_name TEXT, cost_incl_vat REAL,
                                    cost_excl_vat REAL, updated_at TEXT);
        CREATE TABLE orders (marketplace TEXT, shipment_package_id INTEGER, order_date INTEGER,
                             PRIMARY KEY (marketplace, shipment_package_id));
        CREATE TABLE order_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, marketplace TEXT,
                                  shipment_package_id INTEGER, barcode TEXT, merchant_sku TEXT, quantity INTEGER);
    """)
    ch.ensure_table(c)
    yield c
    c.close()


def _sku(c, sku, incl, excl):
    c.execute("INSERT INTO product_costs (sku, product_name, cost_incl_vat, cost_excl_vat) VALUES (?,?,?,?)",
              (sku, sku, incl, excl))
    ch.backfill_from_product_costs(c)


def _siparis(c, spid, tarih_ms, sku):
    c.execute("INSERT INTO orders VALUES ('trendyol', ?, ?)", (spid, tarih_ms))
    c.execute("INSERT INTO order_lines (marketplace, shipment_package_id, barcode, merchant_sku, quantity) "
              "VALUES ('trendyol', ?, ?, ?, 1)", (spid, f"b{spid}", sku))


def test_parse_effective_istanbul():
    assert ch.parse_effective("2026-10-16 23:00") == 1792180800000   # 20:00 UTC
    assert ch.parse_effective("2026-10-16T23:00") == 1792180800000
    assert ch.parse_effective("") is None and ch.parse_effective(None) is None
    with pytest.raises(ValueError):
        ch.parse_effective("dün akşam")
    assert ch.format_ms(1792180800000) == "2026-10-16 23:00"
    assert ch.format_ms(0) == "Başlangıç"


def test_vat_rate_korunur_ve_bozuk_kayitta_varsayilan(conn):
    _sku(conn, "A", 120.0, 100.0)    # %20
    _sku(conn, "B", 110.0, 100.0)    # %10
    _sku(conn, "C", 215.0, 149.17)   # eski bozuk kayıt (%44) -> varsayılan %20
    _sku(conn, "D", 50.0, None)      # KDV hariç yok -> varsayılan %20
    assert ch.vat_rate_for(conn, "A") == 0.20
    assert ch.vat_rate_for(conn, "B") == 0.10
    assert ch.vat_rate_for(conn, "C") == 0.20
    assert ch.vat_rate_for(conn, "D") == 0.20


def test_onizleme_sayilari_ve_uyarilar(conn):
    _sku(conn, "A", 100.0, 100 / 1.2)
    simdi = int(time.time() * 1000)
    _siparis(conn, 1, simdi - 5 * GUN, "A")
    _siparis(conn, 2, simdi - 1 * GUN, "A")
    d = ch.describe_change(conn, "A", 160.0, effective_ms=simdi - 2 * GUN)
    assert d["old_cost"] == 100.0 and d["change_pct"] == 60.0
    assert d["unchanged_lines"] == 1 and d["affected_lines"] == 1
    assert d["is_future"] is False and d["blocked"] is False
    assert any("Büyük değişim" in u for u in d["warnings"])
    assert conn.execute("SELECT COUNT(*) FROM product_cost_history").fetchone()[0] == 1  # yazmadı


def test_zam_gelecek_tarihli_gecmisi_ve_simdiyi_degistirmez(conn):
    _sku(conn, "A", 120.0, 100.0)
    simdi = int(time.time() * 1000)
    _siparis(conn, 1, simdi - 2 * GUN, "A")
    eff = simdi + 2 * 3600 * 1000  # 2 saat sonra
    d = ch.change_cost(conn, "A", 150.0, effective_ms=eff, source="ui", note="zam", now_ms=simdi)
    assert d["is_future"] is True
    h = ch.load_history(conn)
    assert ch.cost_at(h, "A", simdi - 2 * GUN) == 120.0   # geçmiş sipariş eski maliyet
    assert ch.cost_at(h, "A", simdi) == 120.0             # şu an verilen sipariş eski maliyet
    assert ch.cost_at(h, "A", eff) == 150.0               # eff'ten sonrası yeni maliyet
    pc = conn.execute("SELECT cost_incl_vat, cost_excl_vat FROM product_costs WHERE sku='A'").fetchone()
    assert pc[0] == 150.0 and round(pc[1], 4) == 125.0    # KDV hariç = 150/1.2


def test_zam_kdv_orani_korunur(conn):
    _sku(conn, "B", 110.0, 100.0)  # %10 KDV'li ürün
    ch.change_cost(conn, "B", 220.0)
    assert round(conn.execute("SELECT cost_excl_vat FROM product_costs WHERE sku='B'").fetchone()[0], 4) == 200.0


def test_ayni_maliyet_ve_sonrasinda_kayit_varken_reddedilir(conn):
    _sku(conn, "A", 100.0, 100 / 1.2)
    simdi = int(time.time() * 1000)
    with pytest.raises(ValueError):
        ch.change_cost(conn, "A", 100.0, now_ms=simdi)                 # aynı maliyet
    ch.change_cost(conn, "A", 130.0, effective_ms=simdi - 1 * GUN, now_ms=simdi)
    with pytest.raises(ValueError, match="başka bir maliyet kaydı"):
        ch.change_cost(conn, "A", 140.0, effective_ms=simdi - 3 * GUN, now_ms=simdi)  # sonrasında kayıt var
    with pytest.raises(ValueError):
        ch.change_cost(conn, "A", -5.0)
    with pytest.raises(ValueError, match="maliyet kaydı yok"):
        ch.change_cost(conn, "YOK", 10.0)


def test_gecmis_listesi_bayraklari(conn):
    _sku(conn, "A", 100.0, 100 / 1.2)
    simdi = int(time.time() * 1000)
    ch.change_cost(conn, "A", 120.0, effective_ms=simdi - 1 * GUN, now_ms=simdi)
    ch.change_cost(conn, "A", 150.0, effective_ms=simdi + 3600_000, now_ms=simdi)
    liste = ch.list_history(conn, "A", now_ms=simdi)
    assert [r["cost_incl_vat"] for r in liste] == [150.0, 120.0, 100.0]
    assert [r["is_future"] for r in liste] == [True, False, False]
    assert [r["is_current"] for r in liste] == [False, True, False]


def test_hata_duzeltmesi_onizleme_ve_uygulama(conn):
    _sku(conn, "A", 100.0, 100 / 1.2)
    simdi = int(time.time() * 1000)
    _siparis(conn, 1, simdi - 10 * GUN, "A")
    _siparis(conn, 2, simdi - 8 * GUN, "A")
    _siparis(conn, 3, simdi - 1 * GUN, "A")
    ch.change_cost(conn, "A", 130.0, effective_ms=simdi - 5 * GUN, now_ms=simdi)
    base_id = conn.execute("SELECT id FROM product_cost_history WHERE sku='A' AND valid_from_ms=0").fetchone()[0]
    son_id = conn.execute("SELECT id FROM product_cost_history WHERE sku='A' AND valid_from_ms>0").fetchone()[0]

    on = ch.correct_history_row(conn, "A", base_id, 90.0, dry_run=True)
    assert on["affected_lines"] == 2 and on["dry_run"] is True      # sadece ilk dönemin 2 satırı
    assert ch.load_history(conn)["A"][1][0] == 100.0                # önizleme yazmadı

    ch.correct_history_row(conn, "A", base_id, 90.0)
    h = ch.load_history(conn)
    assert ch.cost_at(h, "A", simdi - 9 * GUN) == 90.0              # eski dönem düzeldi
    assert ch.cost_at(h, "A", simdi - 1 * GUN) == 130.0             # sonraki dönem aynı
    assert conn.execute("SELECT cost_incl_vat FROM product_costs WHERE sku='A'").fetchone()[0] == 130.0

    ch.correct_history_row(conn, "A", son_id, 135.0)                # en güncel kayıt -> product_costs de eşitlenir
    assert conn.execute("SELECT cost_incl_vat FROM product_costs WHERE sku='A'").fetchone()[0] == 135.0
    with pytest.raises(ValueError):
        ch.correct_history_row(conn, "A", 99999, 10.0)


def test_record_changes_bekleyen_kayitla_ayni_maliyeti_tekrar_yazmaz(conn):
    _sku(conn, "A", 100.0, 100 / 1.2)
    simdi = int(time.time() * 1000)
    ch.change_cost(conn, "A", 150.0, effective_ms=simdi + 3600_000, now_ms=simdi)  # 1 saat sonra geçerli
    # Ürünler formu aynı yeni maliyetle kaydedilirse değişiklik 'şimdi'ye ÇEKİLMEMELİ
    assert ch.record_changes(conn, [{"sku": "A", "cost_incl_vat": 150.0}], now_ms=simdi) == []
    h = ch.load_history(conn)
    assert ch.cost_at(h, "A", simdi) == 100.0
