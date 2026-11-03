"""Nakit ve borç yönetimi — Faz 1 / Aşama 2 (03.11.2026).

Tablolar: cash_accounts, cash_balances, credit_cards, card_statements,
installment_plans, scheduled_payments, scheduled_payment_events.

Bu modülün HİÇBİR kaydı kâr-zarar hesabına girmez (finance_engine bunları
okumaz). Planlı ödemeler (sahsi_cekis dahil) yalnızca nakit akışında görünür;
vergi/prim giderleri kâra, fixed_expenses'a girilen kayıtlardan girer.

13 haftalık nakit akışı (forecast_13_weeks):
  Başlangıç = serbest nakit: banka + kasa (+ borca ayrılmamış altın) son
  bakiyeleri. Ödeme altyapısı (ikas) bakiyesi başlangıca katılmaz; bir sonraki
  ödeme gününde giriş olarak gelir. Borca ayrılmış hesaplar (Midas) hariç.
  Kalemler 'kesin' veya 'tahmini' olarak etiketlenir; only_certain=True
  tahmini kalemleri dışarıda bırakır.
"""

import calendar
from collections import defaultdict
from datetime import date, datetime, timedelta

from database import get_connection, get_finance_settings

ACCOUNT_TYPES = ("banka", "odeme_altyapisi", "altin", "kasa")
PAYMENT_CATEGORIES = ("vergi_sgk", "borc_aile", "kart", "tedarikci", "sahsi_cekis", "diger")
CARD_WARN_RATIO = 0.80
FUTURE_SALES_FACTOR = 0.90      # ihtiyat: son 8 haftanın %90'ı
FUTURE_SALES_WEEKS = 8
RATIO_LOOKBACK_DAYS = 90        # hakediş/satış ve maliyet/satış oranı (son 3 ay)
DEDUCTION_LOOKBACK_DAYS = 30    # Trendyol kesintileri (reklam/kargo/platform)


def ensure_schema(conn):
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS cash_accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad TEXT NOT NULL UNIQUE,
            tur TEXT NOT NULL CHECK(tur IN {ACCOUNT_TYPES}),
            para_birimi TEXT NOT NULL DEFAULT 'TRY',
            borca_ayrilmis INTEGER NOT NULL DEFAULT 0,
            odeme_gunu INTEGER,            -- odeme_altyapisi: Python weekday (Cuma=4)
            aktif INTEGER NOT NULL DEFAULT 1,
            notlar TEXT
        );
        CREATE TABLE IF NOT EXISTS cash_balances (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hesap_id INTEGER NOT NULL REFERENCES cash_accounts(id),
            tarih TEXT NOT NULL,
            bakiye REAL NOT NULL,
            altin_adet REAL,
            birim_fiyat REAL,
            birim_maliyet REAL,
            notlar TEXT,
            created_at TEXT DEFAULT (datetime('now', 'localtime'))
        );
        CREATE TABLE IF NOT EXISTS credit_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ad TEXT NOT NULL UNIQUE,
            limit_tutar REAL NOT NULL,
            kesim_gunu INTEGER NOT NULL,
            son_odeme_gunu INTEGER NOT NULL,
            guncel_borc REAL,
            guncel_borc_tarihi TEXT,
            notlar TEXT
        );
        CREATE TABLE IF NOT EXISTS card_statements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kart_id INTEGER NOT NULL REFERENCES credit_cards(id),
            donem TEXT NOT NULL,
            tutar REAL NOT NULL,
            son_odeme_tarihi TEXT NOT NULL,
            odendi INTEGER NOT NULL DEFAULT 0,
            odeme_tarihi TEXT,
            UNIQUE(kart_id, donem)
        );
        CREATE TABLE IF NOT EXISTS installment_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kart_id INTEGER NOT NULL REFERENCES credit_cards(id),
            aciklama TEXT NOT NULL,
            taksit_tutari REAL NOT NULL,
            toplam_taksit INTEGER NOT NULL,
            kalan_taksit INTEGER NOT NULL,
            ilk_odeme_tarihi TEXT NOT NULL,
            sku TEXT,
            notlar TEXT
        );
        CREATE TABLE IF NOT EXISTS scheduled_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            aciklama TEXT NOT NULL,
            kategori TEXT NOT NULL CHECK(kategori IN {PAYMENT_CATEGORIES}),
            tutar REAL NOT NULL,
            baslangic_tarihi TEXT NOT NULL,
            tekrar TEXT NOT NULL DEFAULT 'yok' CHECK(tekrar IN ('yok','aylik')),
            ay_sonu INTEGER NOT NULL DEFAULT 0,
            bitis_tarihi TEXT,
            durum TEXT NOT NULL DEFAULT 'aktif' CHECK(durum IN ('aktif','pasif')),
            notlar TEXT,
            tutar_bekleniyor INTEGER NOT NULL DEFAULT 0   -- 1: tutar henüz belli değil (ör. muhasebeciden)
        );
        CREATE TABLE IF NOT EXISTS scheduled_payment_amounts (
            odeme_id INTEGER NOT NULL REFERENCES scheduled_payments(id),
            plan_tarihi TEXT NOT NULL,
            tutar REAL NOT NULL,
            PRIMARY KEY (odeme_id, plan_tarihi)
        );
        CREATE TABLE IF NOT EXISTS scheduled_payment_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            odeme_id INTEGER NOT NULL REFERENCES scheduled_payments(id),
            plan_tarihi TEXT NOT NULL,
            durum TEXT NOT NULL CHECK(durum IN ('odendi','ertelendi','iptal')),
            yeni_tarih TEXT,
            UNIQUE(odeme_id, plan_tarihi)
        );
    """)


# ------------------------------------------------------------ tarih yardımcıları

def _d(x):
    return x if isinstance(x, date) else date.fromisoformat(str(x)[:10])


def add_months(d, n, day=None, month_end=False):
    idx = d.year * 12 + (d.month - 1) + n
    y, m = idx // 12, idx % 12 + 1
    last = calendar.monthrange(y, m)[1]
    if month_end:
        return date(y, m, last)
    return date(y, m, min(day or d.day, last))


def month_end(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def next_weekday(d, weekday):
    """d veya sonrasındaki ilk 'weekday' günü."""
    return d + timedelta(days=(weekday - d.weekday()) % 7)


# ------------------------------------------------------------ hesaplar

def latest_balances(conn):
    rows = conn.execute("""
        SELECT a.*, b.tarih AS bakiye_tarihi, b.bakiye, b.altin_adet, b.birim_fiyat, b.birim_maliyet
        FROM cash_accounts a
        LEFT JOIN cash_balances b ON b.id = (
            SELECT id FROM cash_balances WHERE hesap_id = a.id ORDER BY tarih DESC, id DESC LIMIT 1)
        WHERE a.aktif = 1 ORDER BY a.id""").fetchall()
    return [dict(r) for r in rows]


def free_cash(accounts):
    """Serbest nakit: banka + kasa + borca ayrılmamış altın. Ödeme altyapısı
    bakiyesi henüz hesaba geçmediği için ayrı (giriş olarak) sayılır."""
    return round(sum((a["bakiye"] or 0) for a in accounts
                     if not a["borca_ayrilmis"] and a["tur"] in ("banka", "kasa", "altin")), 2)


def add_balance(conn, hesap_id, tarih, bakiye=None, altin_adet=None, birim_fiyat=None,
                birim_maliyet=None, notlar=None):
    _d(tarih)
    if bakiye is None:
        if altin_adet is None or birim_fiyat is None:
            raise ValueError("bakiye ya da altın adedi + birim fiyat gerekli")
        bakiye = round(float(altin_adet) * float(birim_fiyat), 2)
    cur = conn.execute("""INSERT INTO cash_balances (hesap_id, tarih, bakiye, altin_adet, birim_fiyat, birim_maliyet, notlar)
                          VALUES (?,?,?,?,?,?,?)""",
                       (hesap_id, tarih, float(bakiye), altin_adet, birim_fiyat, birim_maliyet, notlar))
    return cur.lastrowid


# ------------------------------------------------------------ kartlar

def installment_schedule(plan):
    """Kalan taksitlerin ödeme tarihleri: ilk ödeme + k ay, ödenmiş olanlar atlanır."""
    first = _d(plan["ilk_odeme_tarihi"])
    paid = plan["toplam_taksit"] - plan["kalan_taksit"]
    return [add_months(first, k, day=first.day) for k in range(paid, plan["toplam_taksit"])]


def next_statement_payment(card, today):
    """Bugünden sonraki ilk hesap kesiminin son ödeme tarihi."""
    cut = date(today.year, today.month, min(card["kesim_gunu"], calendar.monthrange(today.year, today.month)[1]))
    if today > cut:
        cut = add_months(cut, 1, day=card["kesim_gunu"])
    pay = add_months(cut, 1, day=card["son_odeme_gunu"]) if card["son_odeme_gunu"] <= cut.day else \
        date(cut.year, cut.month, min(card["son_odeme_gunu"], calendar.monthrange(cut.year, cut.month)[1]))
    return pay


def card_overview(conn, today=None):
    today = today or date.today()
    out = []
    for c in conn.execute("SELECT * FROM credit_cards ORDER BY id").fetchall():
        c = dict(c)
        unpaid = [dict(s) for s in conn.execute(
            "SELECT * FROM card_statements WHERE kart_id=? AND odendi=0 ORDER BY son_odeme_tarihi", (c["id"],))]
        plans = [dict(p) for p in conn.execute(
            "SELECT * FROM installment_plans WHERE kart_id=? AND kalan_taksit>0", (c["id"],))]
        remaining_inst = sum(p["taksit_tutari"] * p["kalan_taksit"] for p in plans)
        unpaid_total = sum(s["tutar"] for s in unpaid)
        used = c["guncel_borc"] if c["guncel_borc"] is not None else unpaid_total + remaining_inst
        ratio = used / c["limit_tutar"] if c["limit_tutar"] else None
        unbilled = 0.0
        if c["guncel_borc"] is not None:
            unbilled = max(0.0, c["guncel_borc"] - unpaid_total - remaining_inst)
        c.update({
            "kullanilan": round(used, 2),
            "kullanilabilir": round(c["limit_tutar"] - used, 2),
            "dolulukOrani": round(ratio, 4) if ratio is not None else None,
            "uyari": bool(ratio is not None and ratio > CARD_WARN_RATIO),
            "odenmemisEkstreler": unpaid,
            "taksitPlanlari": [dict(p, kalanTutar=round(p["taksit_tutari"] * p["kalan_taksit"], 2),
                                    sonrakiTarih=(installment_schedule(p) or [None])[0])
                               for p in plans],
            "kalanTaksitToplami": round(remaining_inst, 2),
            "ekstrelenmemis": round(unbilled, 2),
            "ekstrelenmemisOdeme": next_statement_payment(c, today).isoformat() if unbilled else None,
        })
        out.append(c)
    return out


def card_alerts(conn):
    return [{"kart": c["ad"], "dolulukOrani": c["dolulukOrani"], "kullanilan": c["kullanilan"],
             "limit": c["limit_tutar"]} for c in card_overview(conn) if c["uyari"]]


def pay_installment(conn, plan_id):
    conn.execute("UPDATE installment_plans SET kalan_taksit = kalan_taksit - 1 WHERE id=? AND kalan_taksit>0", (plan_id,))


def mark_statement_paid(conn, statement_id, tarih=None, odendi=True):
    conn.execute("UPDATE card_statements SET odendi=?, odeme_tarihi=? WHERE id=?",
                 (1 if odendi else 0, (tarih or date.today().isoformat()) if odendi else None, statement_id))


# ------------------------------------------------------------ planlı ödemeler

def payment_occurrences(p, start, end, events=None):
    """Bir planlı ödemenin [start, end] aralığına düşen, ödenmemiş/iptal
    edilmemiş taksitleri: [(plan_tarihi, efektif_tarih)]. Ertelenen taksit
    yeni tarihinde sayılır. start öncesine düşen ödenmemiş taksitler sayılmaz
    (geçmiş ayları biriktirmemek için; ödenmediyse ertele ile ileri alınır)."""
    events = events or {}
    first = _d(p["baslangic_tarihi"])
    stop = _d(p["bitis_tarihi"]) if p.get("bitis_tarihi") else None
    if p["tekrar"] == "yok":
        dates = [first]
    else:
        dates, k = [], 0
        horizon = end + timedelta(days=366)  # ileri ertelenmiş taksitler için pay
        while True:
            d = add_months(first, k, day=first.day, month_end=bool(p["ay_sonu"]))
            if (stop and d > stop) or d > horizon:
                break
            dates.append(d)
            k += 1
    out = []
    for d in dates:
        ev = events.get(d.isoformat())
        if ev and ev["durum"] in ("odendi", "iptal"):
            continue
        eff = _d(ev["yeni_tarih"]) if ev and ev["durum"] == "ertelendi" and ev.get("yeni_tarih") else d
        if start <= eff <= end:
            out.append((d, eff))
    return out


def migrate_scheduled_amounts(conn):
    cols = [r[1] for r in conn.execute("PRAGMA table_info(scheduled_payments)")]
    if cols and "tutar_bekleniyor" not in cols:
        conn.execute("ALTER TABLE scheduled_payments ADD COLUMN tutar_bekleniyor INTEGER NOT NULL DEFAULT 0")
    ensure_schema(conn)


def occurrence_amount(p, plan_date, overrides):
    """Taksit tutarı: o tarih için girilmiş tutar > sabit tutar; tutarı
    beklenen ödemede girilmemişse None (toplama katılmaz)."""
    v = overrides.get(plan_date.isoformat())
    if v is not None:
        return v
    return None if p.get("tutar_bekleniyor") else p["tutar"]


def set_occurrence_amount(conn, odeme_id, plan_tarihi, tutar):
    _d(plan_tarihi)
    conn.execute("""INSERT INTO scheduled_payment_amounts (odeme_id, plan_tarihi, tutar) VALUES (?,?,?)
                    ON CONFLICT(odeme_id, plan_tarihi) DO UPDATE SET tutar=excluded.tutar""",
                 (odeme_id, plan_tarihi, float(tutar)))


def hb_ads_weekly(conn, today):
    """HB reklam bakiyesi yüklemeleri hakedişten düşülmez (ayrı ödenir):
    son 3 tamamlanmış ayın fixed_expenses (ads_hb) ortalamasından haftalık tutar."""
    first = date(today.year, today.month, 1)
    start = add_months(first, -3, day=1)
    months = [add_months(start, k, day=1).strftime("%Y-%m") for k in range(3)]
    days = (first - start).days
    labels = [r[0] for r in conn.execute("SELECT alias FROM expense_type_aliases WHERE type_key='ads_hb'")]
    if not labels:
        return 0.0, months
    q = ",".join("?" for _ in labels)
    total = conn.execute(f"SELECT COALESCE(SUM(amount),0) FROM fixed_expenses WHERE label IN ({q}) "
                         f"AND month IN ({','.join('?' for _ in months)})", [*labels, *months]).fetchone()[0]
    return round(total / days * 7, 2) if days else 0.0, months


def set_payment_event(conn, odeme_id, plan_tarihi, durum, yeni_tarih=None):
    _d(plan_tarihi)
    if durum == "ertelendi":
        _d(yeni_tarih)
    conn.execute("""INSERT INTO scheduled_payment_events (odeme_id, plan_tarihi, durum, yeni_tarih) VALUES (?,?,?,?)
                    ON CONFLICT(odeme_id, plan_tarihi) DO UPDATE SET durum=excluded.durum, yeni_tarih=excluded.yeni_tarih""",
                 (odeme_id, plan_tarihi, durum, yeni_tarih))


# ------------------------------------------------------------ satış tahmini girdileri

def _order_sales(conn, start_ms, end_ms):
    """(marketplace) -> KDV dahil satış: iptal/iade hariç siparişlerin net tutarı.
    HB placeholder (negatif id) ile gerçek paket aynı sipariş numarasını taşır;
    sipariş başına gerçek paketler tercih edilir."""
    from supplier_ledger import _excluded
    per_order = defaultdict(lambda: {"real": 0.0, "ph": 0.0})
    for r in conn.execute("""SELECT marketplace, order_number, shipment_package_id, status, net_amount
                             FROM orders WHERE order_date BETWEEN ? AND ?""", (start_ms, end_ms)):
        if _excluded(r["marketplace"], r["status"]):
            continue
        b = per_order[(r["marketplace"], r["order_number"])]
        b["real" if (r["shipment_package_id"] or 0) > 0 else "ph"] += r["net_amount"] or 0.0
    out = defaultdict(float)
    for (mp, _), b in per_order.items():
        out[mp] += b["real"] or b["ph"]
    return dict(out)


def _ms(d):
    return int(datetime(d.year, d.month, d.day).timestamp() * 1000)


def forecast_inputs(conn, today):
    """Gelecek satış tahmini için oranlar (hepsi son dönem verisinden)."""
    import cost_history
    import finance_engine
    from supplier_ledger import _excluded

    end = _ms(today)  # bugün hariç (gün bitmedi)
    weekly = _order_sales(conn, end - FUTURE_SALES_WEEKS * 7 * 86400000, end - 1)
    ratio_start = end - RATIO_LOOKBACK_DAYS * 86400000
    sales90 = _order_sales(conn, ratio_start, end - 1)
    summary = finance_engine.compute_profit_summary(
        start_dt=datetime.fromtimestamp(ratio_start / 1000), end_dt=datetime.fromtimestamp((end - 1) / 1000),
        include_settlement_only=False)
    payout_ratio = {}
    for mp, s in sales90.items():
        nh = (summary["by_marketplace"].get(mp) or {}).get("netHakedis")
        payout_ratio[mp] = round(nh / s, 4) if (nh and s) else None

    # Watalina maliyet oranı (KDV dahil maliyet / KDV dahil satış), son 3 ay
    history = cost_history.load_history_safe(conn)
    costs = {r["sku"]: r["cost_incl_vat"] for r in conn.execute("SELECT sku, cost_incl_vat FROM product_costs")}
    cogs = 0.0
    for r in conn.execute("""SELECT o.marketplace, o.status, o.order_date, l.quantity, COALESCE(l.merchant_sku,l.barcode) sku,
                                    l.shipment_package_id
                             FROM order_lines l JOIN orders o ON o.marketplace=l.marketplace AND o.shipment_package_id=l.shipment_package_id
                             WHERE o.order_date BETWEEN ? AND ?""", (ratio_start, end - 1)):
        if _excluded(r["marketplace"], r["status"]) or (r["shipment_package_id"] or 0) < 0:
            continue
        c = cost_history.cost_at(history, r["sku"], r["order_date"], fallback=costs.get(r["sku"]))
        cogs += (c or 0) * (r["quantity"] or 0)
    total90 = sum(sales90.values())
    cogs_ratio = round(cogs / total90, 4) if total90 else 0.0

    # Gecikme: sipariş -> settlement işlem tarihi (teslim) + compute_actual_payout_lag_days (işlem -> ödeme)
    lag_tx = {}
    for r in conn.execute("""SELECT s.marketplace, AVG((s.transaction_date - o.order_date) / 86400000.0) AS g, COUNT(*) n
                             FROM settlements s JOIN orders o ON o.marketplace=s.marketplace AND o.order_number=s.order_number
                             WHERE s.transaction_date IS NOT NULL AND o.order_date BETWEEN ? AND ?
                               AND s.transaction_date >= o.order_date
                             GROUP BY s.marketplace""", (ratio_start, end - 1)):
        lag_tx[r["marketplace"]] = r["g"]
    actual = finance_engine.compute_actual_payout_lag_days()
    lag = {}
    for mp in set(weekly) | set(sales90):
        pay = ((actual.get(mp) or {}).get("sale") or {}).get("averageLagDays")
        if pay is None:
            pay = finance_engine._AVG_PAYOUT_LAG_DAYS.get(mp, {}).get("sale", 35)
        lag[mp] = round((lag_tx.get(mp) or 0) + pay, 1)

    # Trendyol kesintileri (reklam + kargo + platform vb.; komisyon faturası
    # hariç — komisyon hakedişten zaten düşülü): son 30 gün günlük ortalama
    ded = conn.execute("""SELECT
            SUM(CASE WHEN lower(COALESCE(raw_transaction_type,'')) LIKE '%reklam%' THEN COALESCE(debt,0)-COALESCE(credit,0) ELSE 0 END) ads,
            SUM(CASE WHEN lower(COALESCE(raw_transaction_type,'')) LIKE '%reklam%' THEN 0 ELSE COALESCE(debt,0)-COALESCE(credit,0) END) other
        FROM other_financials WHERE marketplace='trendyol' AND transaction_type='DeductionInvoices'
          AND lower(COALESCE(raw_transaction_type,'')) NOT LIKE '%komisyon%' AND transaction_date BETWEEN ? AND ?""",
                       (end - DEDUCTION_LOOKBACK_DAYS * 86400000, end - 1)).fetchone()
    return {
        "weeklySales": {mp: round(v / FUTURE_SALES_WEEKS * FUTURE_SALES_FACTOR, 2) for mp, v in weekly.items()},
        "payoutRatio": payout_ratio,
        "cogsRatio": cogs_ratio,
        "lagDays": lag,
        "tyAdsDaily": round((ded["ads"] or 0) / DEDUCTION_LOOKBACK_DAYS, 2),
        "tyOtherDeductionsDaily": round((ded["other"] or 0) / DEDUCTION_LOOKBACK_DAYS, 2),
    }


def _pending_order_payouts(conn, today, inputs):
    """Sipariş var ama henüz hiç hakediş (settlement) kaydı yok -> tahmini giriş."""
    from supplier_ledger import _excluded
    import finance_engine
    since = _ms(today) - 60 * 86400000
    settled = {(r[0], r[1]) for r in conn.execute(
        "SELECT DISTINCT marketplace, order_number FROM settlements WHERE order_number IS NOT NULL")}
    per_order = {}
    for r in conn.execute("""SELECT marketplace, order_number, shipment_package_id, status, net_amount, order_date
                             FROM orders WHERE order_date >= ?""", (since,)):
        mp = r["marketplace"]
        if mp not in ("trendyol", "hepsiburada") or _excluded(mp, r["status"]) or (mp, r["order_number"]) in settled:
            continue
        b = per_order.setdefault((mp, r["order_number"]), {"real": 0.0, "ph": 0.0, "date": r["order_date"]})
        b["real" if (r["shipment_package_id"] or 0) > 0 else "ph"] += r["net_amount"] or 0.0
    out = []
    for (mp, _), b in per_order.items():
        ratio = inputs["payoutRatio"].get(mp)
        if not ratio:
            continue
        od = datetime.fromtimestamp(b["date"] / 1000)
        pay = finance_engine._round_up_to_payout_day(od + timedelta(days=inputs["lagDays"].get(mp, 35)), mp).date()
        out.append((mp, pay, (b["real"] or b["ph"]) * ratio))
    return out


# ------------------------------------------------------------ 13 hafta

def forecast_13_weeks(today=None, weeks=13, only_certain=False, conn=None):
    if conn is None:
        with get_connection() as c:
            return forecast_13_weeks(today, weeks, only_certain, c)
    import finance_engine
    import supplier_ledger

    today = today or date.today()
    start = today + timedelta(days=1)
    end = start + timedelta(days=7 * weeks - 1)
    settings = get_finance_settings()
    reserve = settings.get("min_cash_reserve", 0) or 0
    items = []

    def add(d, yon, kalem, tutar, tahmini, aciklama="", bekleniyor=False):
        if not bekleniyor and abs(tutar) < 0.005:
            return
        late = d < start
        items.append({"tarih": max(d, start).isoformat(), "yon": yon, "kalem": kalem,
                      "tutar": None if bekleniyor else round(tutar, 2), "tahmini": bool(tahmini),
                      "bekleniyor": bool(bekleniyor),
                      "aciklama": aciklama + (" (vadesi geçmiş, ilk haftaya alındı)" if late else "")})

    accounts = latest_balances(conn)
    opening = free_cash(accounts)
    for a in accounts:
        if a["tur"] == "odeme_altyapisi" and not a["borca_ayrilmis"] and (a["bakiye"] or 0) > 0:
            base = max(start, _d(a["bakiye_tarihi"]) + timedelta(days=1)) if a["bakiye_tarihi"] else start
            day = next_weekday(base, a["odeme_gunu"]) if a["odeme_gunu"] is not None else base
            add(day, "giris", a["ad"], a["bakiye"], False, "Ödeme altyapısı bakiyesi")

    # Pazaryeri hakedişleri (pazaryerinin bildirdiği tarih = kesin; gecikme tahmini = tahmini)
    cal = finance_engine.payout_calendar(start_dt=datetime.combine(start, datetime.min.time()),
                                         end_dt=datetime.combine(end, datetime.max.time()))
    # Pazaryeri panelinden alınan (scraper ya da elle girilen) gelecek ödeme
    # listesi varsa o pazaryeri için: listenin son gününe kadar settlement
    # bazlı tahminler kullanılmaz (liste tam ödeme planıdır); gecikme
    # ortalamasıyla üretilen tahminler hiç kullanılmaz (aynı satırlar panel
    # listesinde zaten var). Panel tutarları kesintiler düşülmüş nettir.
    import external_payout_db
    official_cutoff = {}
    for e in external_payout_db.get_estimates():
        d = datetime.fromtimestamp(e["payment_date"] / 1000).date()
        if d >= start:
            official_cutoff[e["marketplace"]] = max(d, official_cutoff.get(e["marketplace"], d))
    overdue_skipped = 0.0
    names = {"trendyol": "Trendyol", "hepsiburada": "Hepsiburada"}
    for day in cal["days"]:
        d = _d(day["date"])
        for mp, b in (day.get("byMarketplace") or {}).items():
            official = b.get("official") or 0
            planned = b.get("estimated") or 0
            lag = b.get("lagEstimated") or 0
            if d < start:
                overdue_skipped += lag
                continue
            if d > end:
                continue
            cut = official_cutoff.get(mp)
            if cut:
                lag = 0.0
                if d <= cut:
                    planned = 0.0
            add(d, "giris", f"{names.get(mp, mp)} hakediş", official, False, "Pazaryeri paneli (gelecek ödemeler)")
            add(d, "giris", f"{names.get(mp, mp)} hakediş", planned, False, "Pazaryerinin bildirdiği ödeme")
            add(d, "giris", f"{names.get(mp, mp)} hakediş", lag, True, "Ödeme tarihi henüz verilmemiş satırlar (gecikme ortalaması)")

    inputs = forecast_inputs(conn, today)
    hb_ads, hb_ads_months = hb_ads_weekly(conn, today)
    inputs["hbAdsWeekly"] = hb_ads
    for mp, d, amt in _pending_order_payouts(conn, today, inputs):
        if d <= end:
            add(d, "giris", f"{names.get(mp, mp)} hakediş", amt, True, "Hakediş kaydı oluşmamış siparişler")

    # Gelecek satışlar: haftalık satış × hakediş oranı, sipariş + gecikme sonrası ödenir;
    # tedarikçi alımı = satış × maliyet oranı, vadesi M+1 ay sonu.
    for w in range(weeks):
        mid = start + timedelta(days=7 * w + 3)
        total_sales = 0.0
        for mp, s in inputs["weeklySales"].items():
            total_sales += s
            ratio = inputs["payoutRatio"].get(mp)
            if not ratio or mp not in names:
                continue
            pay = finance_engine._round_up_to_payout_day(
                datetime.combine(mid, datetime.min.time()) + timedelta(days=inputs["lagDays"].get(mp, 35)), mp).date()
            if pay <= end:
                add(pay, "giris", f"{names[mp]} hakediş", s * ratio, True, "Gelecek satış tahmini")
        due = supplier_ledger.default_due(mid)
        if due <= end:
            add(due, "cikis", "Watalina", total_sales * inputs["cogsRatio"], True, "Gelecek satışların alımı (tahmini)")
        ws = start + timedelta(days=7 * w)
        ty_cut = official_cutoff.get("trendyol")
        ty_days = 7 if not ty_cut else max(0, min(7, ((ws + timedelta(days=6)) - ty_cut).days))
        add(ws, "cikis", "Trendyol reklam kesintisi", inputs["tyAdsDaily"] * ty_days, True,
            "Son 30 günün ortalaması" + (" (panel ödemelerinde düşülü günler hariç)" if ty_days < 7 else ""))
        add(ws, "cikis", "Trendyol kargo/platform kesintisi",
            inputs["tyOtherDeductionsDaily"] * ty_days, True, "Son 30 günün ortalaması")
        add(ws, "cikis", "Hepsiburada reklam bakiyesi", hb_ads, True,
            f"Son 3 ay ortalaması ({hb_ads_months[0]}–{hb_ads_months[-1]}); hakedişten düşülmez, ayrı yüklenir")

    # Kartlar
    for c in card_overview(conn, today):
        stmt_dates = set()
        for s in c["odenmemisEkstreler"]:
            d = _d(s["son_odeme_tarihi"])
            stmt_dates.add((d.year, d.month))
            if d <= end:
                add(d, "cikis", f"{c['ad']} ekstre", s["tutar"], False, f"Dönem {s['donem']}")
        for p in c["taksitPlanlari"]:
            for d in installment_schedule(p):
                if d <= end and (d.year, d.month) not in stmt_dates:
                    add(d, "cikis", f"{c['ad']} taksit", p["taksit_tutari"], False, p["aciklama"])
        if c["ekstrelenmemis"] and c["ekstrelenmemisOdeme"]:
            d = _d(c["ekstrelenmemisOdeme"])
            if d <= end:
                add(d, "cikis", f"{c['ad']} ekstre", c["ekstrelenmemis"], True, "Ekstrelenmemiş harcama")

    # Tedarikçi borcu (vadesine göre açık bakiye)
    for t in conn.execute("SELECT id, ad FROM tedarikciler").fetchall():
        for due, amt in supplier_ledger.open_obligations(conn, t["id"]):
            d = _d(due)
            if d <= end:
                add(d, "cikis", t["ad"], amt, False, f"Vade {d.strftime('%d.%m.%Y')}")

    # Planlı ödemeler
    for p in conn.execute("SELECT * FROM scheduled_payments WHERE durum='aktif'").fetchall():
        p = dict(p)
        events = {e["plan_tarihi"]: dict(e) for e in conn.execute(
            "SELECT * FROM scheduled_payment_events WHERE odeme_id=?", (p["id"],))}
        overrides = {r["plan_tarihi"]: r["tutar"] for r in conn.execute(
            "SELECT plan_tarihi, tutar FROM scheduled_payment_amounts WHERE odeme_id=?", (p["id"],))}
        for plan_d, eff in payment_occurrences(p, start, end, events):
            amt = occurrence_amount(p, plan_d, overrides)
            label = {"sahsi_cekis": "Şahsi çekiş"}.get(p["kategori"], p["kategori"])
            if amt is None:
                add(eff, "cikis", p["aciklama"], 0, False, (p.get("notlar") or "Tutar bekleniyor"), bekleniyor=True)
            else:
                add(eff, "cikis", p["aciklama"], amt, False, label)

    if only_certain:
        items = [i for i in items if not i["tahmini"]]

    rows = []
    bal = opening
    for w in range(weeks):
        ws, we = start + timedelta(days=7 * w), start + timedelta(days=7 * w + 6)
        wi = [i for i in items if ws.isoformat() <= i["tarih"] <= we.isoformat()]
        gin = sum(i["tutar"] for i in wi if i["yon"] == "giris" and i["tutar"] is not None)
        cik = sum(i["tutar"] for i in wi if i["yon"] == "cikis" and i["tutar"] is not None)
        bal += gin - cik
        rows.append({
            "hafta": w + 1, "baslangic": ws.isoformat(), "bitis": we.isoformat(),
            "giris": round(gin, 2), "cikis": round(cik, 2), "net": round(gin - cik, 2),
            "girisTahmini": round(sum(i["tutar"] for i in wi if i["yon"] == "giris" and i["tahmini"]), 2),
            "cikisTahmini": round(sum(i["tutar"] for i in wi if i["yon"] == "cikis" and i["tahmini"]), 2),
            "tutariBekleyen": [i["kalem"] for i in wi if i["bekleniyor"]],
            "bakiye": round(bal, 2), "rezervAlti": bal < reserve,
            "kalemler": sorted(wi, key=lambda i: (i["tarih"], i["yon"], i["kalem"])),
        })
    return {
        "bugun": today.isoformat(), "baslangicBakiyesi": opening, "rezerv": reserve,
        "yalnizcaKesin": only_certain, "haftalar": rows, "girdiler": inputs,
        "hesaplar": accounts, "gecikmisTahminiHaricTutulan": round(overdue_skipped, 2),
        "panelOdemeSonTarihi": {k: v.isoformat() for k, v in official_cutoff.items()},
        "borcaAyrilmis": round(sum((a["bakiye"] or 0) for a in accounts if a["borca_ayrilmis"]), 2),
    }


def hb_overdue_estimates(today=None):
    """HB mutabakatı: ödeme tarihi bildirilmemiş, gecikme ortalamasıyla tahmin
    edilen tarihi bugünden önce kalmış (ödendiği görünmeyen) hakediş satırları,
    tahmini ödeme gününe göre gruplu."""
    import finance_engine
    today = today or date.today()
    lag = finance_engine._AVG_PAYOUT_LAG_DAYS.get("hepsiburada", {})
    groups = {}
    with get_connection() as conn:
        rows = conn.execute("""SELECT raw_transaction_type, transaction_type, seller_revenue, debt, credit,
                                      commission_amount, transaction_date, order_number
                               FROM settlements WHERE marketplace='hepsiburada' AND payment_date IS NULL
                                 AND transaction_date IS NOT NULL""").fetchall()
    for r in rows:
        cat = finance_engine._categorize("hepsiburada", r["raw_transaction_type"], r["transaction_type"])
        if cat == "other":
            continue
        net = finance_engine._payout_row_net("hepsiburada", r["raw_transaction_type"], r["seller_revenue"],
                                             r["debt"], r["credit"], r["commission_amount"], r["transaction_type"])
        tx = datetime.fromtimestamp(r["transaction_date"] / 1000)
        est = finance_engine._round_up_to_payout_day(
            tx + timedelta(days=lag.get("return" if cat == "return" else "sale", 35)), "hepsiburada").date()
        if est > today:
            continue
        g = groups.setdefault(est, {"tahminiOdeme": est.isoformat(), "tutar": 0.0, "satir": 0,
                                    "siparisler": set(), "islemIlk": tx.date(), "islemSon": tx.date()})
        g["tutar"] += net
        g["satir"] += 1
        g["siparisler"].add(r["order_number"])
        g["islemIlk"] = min(g["islemIlk"], tx.date())
        g["islemSon"] = max(g["islemSon"], tx.date())
    out = []
    for k in sorted(groups):
        g = groups[k]
        out.append({"tahminiOdeme": g["tahminiOdeme"], "tutar": round(g["tutar"], 2), "satir": g["satir"],
                    "siparis": len(g["siparisler"]), "islemDonemi": [g["islemIlk"].isoformat(), g["islemSon"].isoformat()]})
    return {"items": out, "toplam": round(sum(i["tutar"] for i in out), 2)}
