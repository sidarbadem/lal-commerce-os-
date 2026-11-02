# LAL Commerce OS

Flask + SQLite (trendyol_data.db) + Redis + Celery. Trendyol ve Hepsiburada siparis/finans paneli.

## Calistirma
- Once: source venv/bin/activate
- Uygulama: python3 app.py (port 5050)
- Test: pytest -q (her degisiklikten sonra calistir, gecmeden commit atma)

## Kurallar
- Turkce ve kisa yaz, rapor degil cozum ver.
- DB'yi degistiren her islemden once (migration, toplu update, backfill) onay iste.
- Backend/yapisal commitler ile gorsel/frontend commitlerini ayri tut.
- Yapisal degisiklikte README'yi ayni committe guncelle.
- Aylik rakamlar siparis tarihine gore hesaplanir (order_date), hakedis tarihine gore degil.
- Trendyol epoch zamanlari Europe/Istanbul; normalize_trendyol_epoch_ms() kullan.
- .env ve *.db asla commitlenmez.
