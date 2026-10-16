import sqlite3

import database


def _db(rows):
    c = sqlite3.connect(":memory:")
    c.execute(
        "CREATE TABLE product_costs (sku TEXT PRIMARY KEY, cost_incl_vat REAL, "
        "cost_excl_vat REAL, updated_at TEXT)"
    )
    c.executemany(
        "INSERT INTO product_costs (sku, cost_incl_vat, cost_excl_vat, updated_at) VALUES (?,?,?, 'T0')",
        rows,
    )
    return c


def _oku(c):
    return {
        r[0]: (r[1], r[2], r[3])
        for r in c.execute("SELECT sku, cost_incl_vat, cost_excl_vat, updated_at FROM product_costs")
    }


BOZUK = [
    ("SH-PHM-001", 215.0, 149.1666667),
    ("SH-TDS-01", 215.0, 149.1666667),
    ("SH-8IN1-METER", 1215.0, 843.3333333),
    ("SH-10TF-BG", 2575.0, 1787.5),
]


def test_dort_sku_duzelir_incl_ve_updated_at_degismez():
    c = _db(BOZUK)
    database._migrate_fix_cost_excl_vat(c)
    got = _oku(c)
    assert round(got["SH-PHM-001"][1], 4) == 179.1667
    assert round(got["SH-TDS-01"][1], 4) == 179.1667
    assert round(got["SH-8IN1-METER"][1], 4) == 1012.5
    assert round(got["SH-10TF-BG"][1], 4) == 2145.8333
    for sku, (incl, _excl, upd) in got.items():
        assert incl == dict((s, i) for s, i, _ in BOZUK)[sku]  # maliyet dahil değişmedi
        assert upd == "T0"                                      # updated_at'e dokunulmadı


def test_diger_skular_dokunulmaz():
    # %10 KDV'li ürün ve listedeki 4 SKU dışındaki sapmalı satır olduğu gibi kalır
    c = _db(BOZUK + [("BASKA-10", 110.0, 100.0), ("BASKA-SAPMA", 500.0, 300.0), ("BOS", 10.0, None)])
    database._migrate_fix_cost_excl_vat(c)
    got = _oku(c)
    assert got["BASKA-10"][1] == 100.0
    assert got["BASKA-SAPMA"][1] == 300.0
    assert got["BOS"][1] is None


def test_idempotent():
    c = _db(BOZUK)
    database._migrate_fix_cost_excl_vat(c)
    ilk = _oku(c)
    database._migrate_fix_cost_excl_vat(c)
    assert _oku(c) == ilk


def test_zaten_dogru_satira_dokunmaz():
    c = _db([("SH-TDS-01", 215.0, 215.0 / 1.2)])
    database._migrate_fix_cost_excl_vat(c)
    assert _oku(c)["SH-TDS-01"][1] == 215.0 / 1.2
