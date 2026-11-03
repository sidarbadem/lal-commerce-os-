"""Faz 1 / Aşama 2: nakit hesapları, kartlar, planlı ödemeler ve 13 haftalık nakit akışı.

Elle hesaplanan senaryo (bugün 03.11.2026 Salı; hafta 1 = 04–10.11):
  Başlangıç: Enpara 50.000 (Midas 96.119 borca ayrılmış -> hariç)
  H1  giriş: ikas 7.100 (Cuma 06.11) + TY 10.000 (09.11) + HB tahmini 1.000 (10.11) = 18.100
      çıkış: Enpara ekstre 40.041 (05.11) + İş taksit 18.333,40 (05.11) = 58.374,40
      bakiye 50.000 + 18.100 − 58.374,40 = 9.725,60
  H4  (25.11–01.12): Watalina 217.540 (30.11) + Bağ-Kur 10.156,73 (30.11) -> −217.971,13
  H5  (02–08.12): İş taksit 18.333,40 + ekstrelenmemiş 20,00 (tahmini) -> −236.324,53
  H6  (09–15.12): Anne 40.000 (15.12) -> −276.324,53
  H9  (30.12–05.01): Bağ-Kur 10.156,73 (31.12) + İş taksit 18.333,40 (05.01) -> −304.814,66
  H11 (13–19.01): Anne 40.000 -> −344.814,66
  H13 (27.01–02.02): Bağ-Kur 10.156,73 (31.01) -> −354.971,39
"""
from datetime import date

import pytest

import finance_engine
import nakit
import supplier_ledger as sl
from database import get_connection, save_finance_setting

TODAY = date(2026, 11, 3)


def _seed(conn):
    conn.execute("INSERT INTO cash_accounts (id, ad, tur) VALUES (1, 'Enpara', 'banka')")
    conn.execute("INSERT INTO cash_accounts (id, ad, tur, odeme_gunu) VALUES (2, 'ikas', 'odeme_altyapisi', 4)")
    conn.execute("INSERT INTO cash_accounts (id, ad, tur, borca_ayrilmis) VALUES (3, 'Midas', 'altin', 1)")
    nakit.add_balance(conn, 1, "2026-11-03", 50000)
    nakit.add_balance(conn, 2, "2026-11-03", 7100)
    nakit.add_balance(conn, 3, "2026-11-03", altin_adet=1387, birim_fiyat=69.30)
    conn.execute("INSERT INTO credit_cards (id, ad, limit_tutar, kesim_gunu, son_odeme_gunu) VALUES (1,'Enpara Kart',41000,25,5)")
    conn.execute("INSERT INTO card_statements (kart_id, donem, tutar, son_odeme_tarihi) VALUES (1,'2026-10',40041,'2026-11-05')")
    conn.execute("INSERT INTO credit_cards (id, ad, limit_tutar, kesim_gunu, son_odeme_gunu, guncel_borc, guncel_borc_tarihi) "
                 "VALUES (2,'İş Bankası Kart',114536,25,5,91687,'2026-11-03')")
    conn.execute("INSERT INTO installment_plans (kart_id, aciklama, taksit_tutari, toplam_taksit, kalan_taksit, ilk_odeme_tarihi, sku) "
                 "VALUES (2,'SH-10TF-BG 50 set',18333.40,6,5,'2026-10-05','SH-10TF-BG')")
    conn.execute("INSERT INTO scheduled_payments (aciklama, kategori, tutar, baslangic_tarihi, tekrar, ay_sonu) "
                 "VALUES ('Bağ-Kur','vergi_sgk',10156.73,'2026-11-30','aylik',1)")
    conn.execute("INSERT INTO scheduled_payments (aciklama, kategori, tutar, baslangic_tarihi, tekrar, bitis_tarihi) "
                 "VALUES ('Anne altın borcu','borc_aile',40000,'2026-12-15','aylik','2027-04-15')")
    conn.execute("INSERT INTO tedarikciler (id, ad) VALUES (4, 'Watalina')")
    sl.add_movement(conn, 4, "acilis", 217540, "Watalina ekstresine göre", "2026-10-31", "2026-11-30")
    conn.commit()


@pytest.fixture
def scenario(db, monkeypatch):
    with get_connection() as conn:
        _seed(conn)
    save_finance_setting("min_cash_reserve", 30000)
    monkeypatch.setattr(nakit, "forecast_inputs", lambda conn, today: {
        "weeklySales": {}, "payoutRatio": {}, "cogsRatio": 0.0, "lagDays": {},
        "tyAdsDaily": 0.0, "tyOtherDeductionsDaily": 0.0})
    monkeypatch.setattr(finance_engine, "payout_calendar", lambda **kw: {"days": [
        {"date": "2026-11-01", "byMarketplace": {"hepsiburada": {"lagEstimated": 500.0}}},
        {"date": "2026-11-09", "byMarketplace": {"trendyol": {"estimated": 10000.0}}},
        {"date": "2026-11-10", "byMarketplace": {"hepsiburada": {"lagEstimated": 1000.0}}},
    ], "unplanned": {}})


def test_forecast_matches_hand_calculation(scenario):
    f = nakit.forecast_13_weeks(today=TODAY)
    w = {r["hafta"]: r for r in f["haftalar"]}
    assert f["baslangicBakiyesi"] == 50000
    assert f["borcaAyrilmis"] == pytest.approx(96119.10)
    assert w[1]["baslangic"] == "2026-11-04" and w[13]["bitis"] == "2027-02-02"
    assert w[1]["giris"] == pytest.approx(18100) and w[1]["cikis"] == pytest.approx(58374.40)
    assert w[1]["bakiye"] == pytest.approx(9725.60)
    assert w[1]["rezervAlti"] is True
    assert w[4]["bakiye"] == pytest.approx(-217971.13)
    assert w[5]["cikisTahmini"] == pytest.approx(20.00)
    assert w[5]["bakiye"] == pytest.approx(-236324.53)
    assert w[6]["bakiye"] == pytest.approx(-276324.53)
    assert w[9]["bakiye"] == pytest.approx(-304814.66)
    assert w[11]["bakiye"] == pytest.approx(-344814.66)
    assert w[13]["bakiye"] == pytest.approx(-354971.39)
    assert f["gecikmisTahminiHaricTutulan"] == 500.0


def test_only_certain_filter_drops_estimates(scenario):
    f = nakit.forecast_13_weeks(today=TODAY, only_certain=True)
    assert f["haftalar"][0]["giris"] == pytest.approx(17100)
    assert f["haftalar"][12]["bakiye"] == pytest.approx(-355951.39)  # HB tahmini 1.000 ve ekstrelenmemiş 20 hariç


def test_paid_statement_and_postponed_payment(scenario):
    with get_connection() as conn:
        nakit.mark_statement_paid(conn, 1, "2026-11-05")
        nakit.set_payment_event(conn, 2, "2026-12-15", "ertelendi", "2027-01-05")
        nakit.pay_installment(conn, 1)
        conn.commit()
    f = nakit.forecast_13_weeks(today=TODAY)
    w = {r["hafta"]: r for r in f["haftalar"]}
    assert w[1]["cikis"] == pytest.approx(0)          # ekstre ödendi, Kasım taksiti ödendi
    assert w[6]["cikis"] == pytest.approx(0)          # Anne 15.12 -> 05.01'e ertelendi
    assert any(i["kalem"] == "Anne altın borcu" and i["tarih"] == "2027-01-05" for i in w[9]["kalemler"])


def test_card_utilisation_warning(scenario):
    with get_connection() as conn:
        cards = {c["ad"]: c for c in nakit.card_overview(conn, TODAY)}
        alerts = nakit.card_alerts(conn)
    assert cards["Enpara Kart"]["kullanilan"] == 40041 and cards["Enpara Kart"]["uyari"]
    assert cards["İş Bankası Kart"]["dolulukOrani"] == pytest.approx(91687 / 114536, abs=1e-4)
    assert cards["İş Bankası Kart"]["ekstrelenmemis"] == pytest.approx(20.0)
    assert cards["İş Bankası Kart"]["ekstrelenmemisOdeme"] == "2026-12-05"
    assert {a["kart"] for a in alerts} == {"Enpara Kart", "İş Bankası Kart"}


def test_installment_skipped_when_statement_exists_for_month(scenario):
    with get_connection() as conn:
        conn.execute("INSERT INTO card_statements (kart_id, donem, tutar, son_odeme_tarihi) VALUES (2,'2026-11',18400,'2026-12-05')")
        conn.commit()
    f = nakit.forecast_13_weeks(today=TODAY)
    w5 = f["haftalar"][4]["kalemler"]
    assert [i["kalem"] for i in w5 if "İş" in i["kalem"]].count("İş Bankası Kart taksit") == 0


def test_month_end_recurrence_and_end_date():
    p = {"baslangic_tarihi": "2026-11-30", "tekrar": "aylik", "ay_sonu": 1, "bitis_tarihi": None}
    occ = nakit.payment_occurrences(p, date(2026, 11, 4), date(2027, 3, 1))
    assert [e.isoformat() for _, e in occ] == ["2026-11-30", "2026-12-31", "2027-01-31", "2027-02-28"]
    p = {"baslangic_tarihi": "2026-12-15", "tekrar": "aylik", "ay_sonu": 0, "bitis_tarihi": "2027-04-15"}
    occ = nakit.payment_occurrences(p, date(2026, 11, 4), date(2027, 12, 31))
    assert len(occ) == 5


def test_scheduled_payments_never_touch_profit(scenario):
    with get_connection() as conn:
        conn.execute("INSERT INTO scheduled_payments (aciklama, kategori, tutar, baslangic_tarihi) "
                     "VALUES ('Şahsi', 'sahsi_cekis', 25000, '2026-11-10')")
        conn.commit()
    from datetime import datetime
    t = finance_engine.compute_profit_summary(start_dt=datetime(2026, 11, 1), end_dt=datetime(2026, 11, 30, 23, 59),
                                              include_period_expenses=True)["totals"]
    assert t["realNetProfit"] == 0 and t["businessExpenses"] == 0
    f = nakit.forecast_13_weeks(today=TODAY)
    assert any(i["kalem"] == "Şahsi" for i in f["haftalar"][0]["kalemler"])


def test_api_endpoints(scenario, client):
    from conftest import auth_headers
    h = auth_headers()
    assert client.get("/nakit", headers=h).status_code == 200
    assert client.get("/api/nakit/akis?yalnizca_kesin=1", headers=h).get_json()["yalnizcaKesin"] is True
    assert len(client.get("/api/nakit/uyarilar", headers=h).get_json()["kartlar"]) == 2
    r = client.post("/api/nakit/planli", json={"aciklama": "x", "kategori": "yok", "tutar": 1,
                                                "baslangic_tarihi": "2026-11-10"}, headers=h)
    assert r.status_code == 400
    s = client.get("/api/tedarikciler/4/ozet", headers=h).get_json()
    assert s["bakiye"] == 217540 and s["vade"]["buAy"] == 217540
