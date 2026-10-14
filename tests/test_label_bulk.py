"""Etiketler: Trendyol (ty_label), Hepsiburada tek etiket (hb_label), rota yardımcıları."""
import io

import pytest
from PIL import Image
from pypdf import PdfReader
from reportlab.pdfgen import canvas

import hb_label
import ty_label


def _pkg(order="11701725483", tracking="7330037943973969", n_lines=1, phone="05321234567",
         district="Sarıyer", city="İstanbul", cargo="Trendyol Express Marketplace"):
    return {
        "orderNumber": order,
        "cargoTrackingNumber": tracking,
        "cargoProviderName": cargo,
        "shipmentAddress": {
            "fullName": "Enis Behiç Ülkümen",
            "phone": phone,
            "fullAddress": "Profesör Muammer Aksoy caddesi No48/1 Poaş bayi",
            "district": district,
            "city": city,
        },
        "lines": [
            {"productName": "SoftHydra PAE RO-122 Çelik Su Arıtma Tankı - 8 Litre", "quantity": 2,
             "stockCode": "RO122-8L"}
            for _ in range(n_lines)
        ],
    }


def _pages(pdf):
    return PdfReader(io.BytesIO(pdf)).pages


def _size_mm(page):
    return (float(page.mediabox.width) * 25.4 / 72, float(page.mediabox.height) * 25.4 / 72)


def _hb_like_pdf(size=(288, 432), marker="HB-KARGO-BARKODU"):
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=size)
    c.drawString(20, size[1] - 30, marker)
    c.showPage()
    c.save()
    return buf.getvalue()


def _fake_image():
    img = Image.new("L", (80, 80), 255)
    for x in range(20, 60):
        for y in range(20, 60):
            img.putpixel((x, y), 40)
    return img


def _hb_order(**kw):
    o = {
        "order_no": "4468782688", "cargo": "hepsiJET", "name": "Ali Osman Şen",
        "address": "Bahçelievler Mah. Belde Sk. Bina No: 66 Daire No: 3 Kat: 3",
        "ilce": "Merkez", "il": "Bilecik",
        "items": [{"name": "SoftHydra PAE RO-122 Çelik Su Arıtma Tankı - 8 Litre", "qty": 2, "sku": "RO122-8L"}],
    }
    o.update(kw)
    return o


# --- Trendyol ---
def test_single_label_is_one_4x6_page():
    pages = _pages(ty_label.build_label_pdf(_pkg()))
    assert len(pages) == 1
    w, h = _size_mm(pages[0])
    assert abs(w - 101.6) < 0.5 and abs(h - 152.4) < 0.5


def test_single_label_rejects_missing_tracking():
    with pytest.raises(ValueError):
        ty_label.build_label_pdf(_pkg(tracking=""))
    with pytest.raises(ValueError):
        ty_label.build_label_pdf(_pkg(tracking="abc"))


def test_many_lines_still_one_page():
    assert len(_pages(ty_label.build_label_pdf(_pkg(n_lines=12)))) == 1


def test_bulk_one_page_per_valid_package_and_reports_skipped():
    pdf, skipped = ty_label.build_labels_pdf([_pkg("A"), _pkg("B", tracking=""), _pkg("C")])
    assert len(_pages(pdf)) == 2
    assert [s["order_no"] for s in skipped] == ["B"]


def test_bulk_without_any_valid_package_raises():
    with pytest.raises(ValueError):
        ty_label.build_labels_pdf([_pkg(tracking="")])


def test_turkish_uppercase_region_and_phone():
    assert ty_label.tr_upper("izmir") == "İZMİR"
    assert ty_label.tr_upper("Bilecik Merkez") == "BİLECİK MERKEZ"
    assert ty_label.tr_upper("Sarıyer") == "SARIYER"
    assert ty_label.fmt_phone("05321234567") == "0532 123 45 67"
    assert ty_label.fmt_phone("5321234567") == "0532 123 45 67"
    assert ty_label.fmt_phone(None) == ""


def test_trendyol_label_text_is_trendyol_only():
    text = _pages(ty_label.build_label_pdf(_pkg()))[0].extract_text()
    assert "Trendyol" in text
    assert "Hepsiburada" not in text
    assert "SARIYER / İSTANBUL" in text
    assert "0532 123 45 67" in text


def test_missing_phone_prints_no_tel_line():
    text = _pages(ty_label.build_label_pdf(_pkg(phone=None)))[0].extract_text()
    assert "Tel:" not in text


def test_trendyol_label_shows_cargo_company_without_marketplace_suffix():
    text = _pages(ty_label.build_label_pdf(_pkg()))[0].extract_text()
    assert "KARGO" in text and "Trendyol Express" in text
    assert "Marketplace" not in text
    assert ty_label.cargo_label("Trendyol Express Marketplace") == "Trendyol Express"
    assert ty_label.cargo_label("hepsiJET") == "hepsiJET"
    assert ty_label.cargo_label(None) == ""


def test_trendyol_label_without_cargo_still_builds():
    text = _pages(ty_label.build_label_pdf(_pkg(cargo="")))[0].extract_text()
    assert "KARGO" in text  # yalnız 'KARGO BARKODU' kartı; şerit çıkmaz
    assert "Trendyol Express" not in text


def test_product_image_is_drawn_when_available(monkeypatch):
    base = len(_pages(ty_label.build_label_pdf(_pkg()))[0].images)
    pkg = _pkg()
    pkg["lines"][0]["imageUrl"] = "http://x/y.png"
    monkeypatch.setattr(ty_label, "load_product_image", lambda src: _fake_image())
    with_img = len(_pages(ty_label.build_label_pdf(pkg))[0].images)
    assert with_img == base + 1


def test_missing_or_broken_image_does_not_break_label():
    assert ty_label.load_product_image(None) is None
    assert ty_label.load_product_image("/yok/boyle/bir/dosya.png") is None
    assert ty_label.load_product_image(b"bu bir resim degil") is None
    pkg = _pkg()
    pkg["lines"][0]["imageUrl"] = "/yok/boyle/bir/dosya.png"
    assert len(_pages(ty_label.build_label_pdf(pkg))) == 1


# --- Hepsiburada ---
def test_hb_stamp_keeps_original_and_adds_hepsiburada_text():
    out = hb_label.stamp_hb_label(_hb_like_pdf())
    pages = _pages(out)
    assert len(pages) == 1
    text = pages[0].extract_text()
    assert "HB-KARGO-BARKODU" in text and "Hepsiburada" in text and "Trendyol" not in text


def test_hb_stamp_leaves_unexpected_page_size_untouched():
    out = hb_label.stamp_hb_label(_hb_like_pdf(size=(595, 842)))
    assert "Hepsiburada" not in _pages(out)[0].extract_text()


def test_hb_full_label_has_cargo_recipient_region_and_original_block():
    out = hb_label.build_hb_label(_hb_like_pdf(), _hb_order())
    pages = _pages(out)
    assert len(pages) == 1
    w, h = _size_mm(pages[0])
    assert abs(w - 101.6) < 0.5 and abs(h - 152.4) < 0.5
    text = pages[0].extract_text()
    assert "HB-KARGO-BARKODU" in text            # HB'nin kendi bloğu korunur
    assert "hepsiJET" in text and "KARGO" in text
    assert "Ali Osman Şen" in text
    assert "MERKEZ / BİLECİK" in text
    assert "Hepsiburada'dan" in text
    assert "Trendyol" not in text
    assert "Tel:" not in text                    # telefon verilmiyor -> satır yok


def test_hb_full_label_prints_phone_only_if_given():
    text = _pages(hb_label.build_hb_label(_hb_like_pdf(), _hb_order(phone="05321234567")))[0].extract_text()
    assert "Tel: 0532 123 45 67" in text


def test_hb_full_label_draws_product_image(monkeypatch):
    plain = len(_pages(hb_label.build_hb_label(_hb_like_pdf(), _hb_order()))[0].images)
    order = _hb_order()
    order["items"][0]["imageUrl"] = "http://x/y.png"
    monkeypatch.setattr(ty_label, "load_product_image", lambda src: _fake_image())
    assert len(_pages(hb_label.build_hb_label(_hb_like_pdf(), order))[0].images) == plain + 1


def test_hb_full_label_many_items_does_not_overflow():
    order = _hb_order(items=[{"name": "Ürün %d" % i, "qty": 1, "sku": "S%d" % i} for i in range(9)])
    text = _pages(hb_label.build_hb_label(_hb_like_pdf(), order))[0].extract_text()
    assert "ürün daha" in text


def test_hb_full_label_leaves_unexpected_page_size_untouched():
    text = _pages(hb_label.build_hb_label(_hb_like_pdf(size=(595, 842)), _hb_order()))[0].extract_text()
    assert "Hepsiburada" not in text


# --- rota yardımcıları ---
def _routes():
    return pytest.importorskip("blueprints.paketlenecekler_routes")


def test_hb_label_order_maps_fields_from_order_items(monkeypatch):
    pr = _routes()
    items = [{
        "packageNumber": "PKG1", "orderNumber": "4468782688", "cargoCompany": "hepsiJET",
        "customerName": "Müşteri A", "name": "Ürün 1", "quantity": 2, "merchantSKU": "SKU-1",
        "shippingAddress": {"name": "Ali Osman Şen", "address": "Bahçelievler Mah. Belde Sk. 66",
                            "town": "Merkez", "district": "Bahçelievler", "city": "Bilecik", "phoneNumber": ""},
    }, {"packageNumber": "BASKA", "orderNumber": "9"}]
    monkeypatch.setattr(pr, "_hb_items_cached", lambda core: items)
    monkeypatch.setattr(pr, "_label_images", lambda skus: {"SKU-1": "http://img/1.jpg"})
    order = pr._hb_label_order(object(), "PKG1")
    assert order["order_no"] == "4468782688" and order["cargo"] == "hepsiJET"
    assert order["name"] == "Ali Osman Şen"
    assert order["ilce"] == "Merkez" and order["il"] == "Bilecik"
    assert order["phone"] == ""
    assert order["items"] == [{"name": "Ürün 1", "qty": 2, "sku": "SKU-1", "imageUrl": "http://img/1.jpg"}]


def test_hb_label_order_unknown_package_returns_none(monkeypatch):
    pr = _routes()

    class Core:
        def fetch_all_hb_packages(self, a, b):
            return []

    monkeypatch.setattr(pr, "_hb_items_cached", lambda core: [])
    assert pr._hb_label_order(Core(), "YOK") is None


def test_enrich_ty_images_sets_image_url_per_line(monkeypatch):
    pr = _routes()
    monkeypatch.setattr(pr, "_label_images", lambda skus: {"A": "http://img/a.jpg"})
    pkg = {"lines": [{"merchantSku": "A"}, {"barcode": "B"}]}
    pr._enrich_ty_images(pkg)
    assert pkg["lines"][0]["imageUrl"] == "http://img/a.jpg"
    assert pkg["lines"][1]["imageUrl"] is None


def test_hb_label_order_falls_back_to_order_detail_for_address(monkeypatch):
    pr = _routes()
    packed_item = {"packageNumber": "PKG2", "orderNumber": "4623107497", "cargoCompany": "hepsiJET",
                   "customerName": "Hesap Sahibi", "productName": "Tank", "quantity": 1, "merchantSku": "RO122-8L"}

    class Core:
        HB_ORDERS_PATH = "/orders/merchantid/abc"

        def fetch_all_hb_packages(self, a, b):
            return []

        def hepsiburada_get(self, path, params):
            assert path == "/orders/merchantid/abc/ordernumber/4623107497"
            return {"items": [{"shippingAddress": {"name": "Rumeysa Yönter", "address": "Petrol Cd. Özkent 91 Sitesi D Blok",
                                                   "town": "Sincan", "city": "Ankara"}}]}

    monkeypatch.setattr(pr, "_hb_items_cached", lambda core: [packed_item])
    monkeypatch.setattr(pr, "_label_images", lambda skus: {})
    order = pr._hb_label_order(Core(), "PKG2")
    assert order["name"] == "Rumeysa Yönter"
    assert order["address"].startswith("Petrol Cd.")
    assert order["ilce"] == "Sincan" and order["il"] == "Ankara"


def test_hb_label_order_detail_failure_still_returns_order(monkeypatch):
    pr = _routes()
    packed_item = {"packageNumber": "PKG3", "orderNumber": "1", "cargoCompany": "hepsiJET",
                   "customerName": "Hesap Sahibi", "name": "Tank", "quantity": 1, "merchantSKU": "X"}

    class Core:
        HB_ORDERS_PATH = "/orders/merchantid/abc"

        def hepsiburada_get(self, path, params):
            raise RuntimeError("404")

    monkeypatch.setattr(pr, "_hb_items_cached", lambda core: [packed_item])
    monkeypatch.setattr(pr, "_label_images", lambda skus: {})
    order = pr._hb_label_order(Core(), "PKG3")
    assert order["name"] == "Hesap Sahibi" and order["address"] == "" and order["il"] == ""


def test_hb_full_label_without_address_has_no_dash_placeholder():
    text = _pages(hb_label.build_hb_label(_hb_like_pdf(), _hb_order(address="", ilce="", il="")))[0].extract_text()
    assert "ALICI" in text and "Ali Osman Şen" in text
    lines = [ln.strip() for ln in text.splitlines()]
    assert "-" not in lines


def test_product_title_strips_leading_pipe():
    assert ty_label.product_title("| Daire Tipi Tesisat") == "Daire Tipi Tesisat"
    assert ty_label.product_title("Softhydra | Daire Tipi") == "Softhydra | Daire Tipi"
    assert ty_label.product_title(None) == ""
