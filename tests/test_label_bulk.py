"""ty_label: 4x6 inç Trendyol etiketi (tekli + toplu)."""
import io

import pytest
from pypdf import PdfReader

import ty_label


def _pkg(order="11701725483", tracking="7330037943973969", n_lines=1):
    return {
        "orderNumber": order,
        "cargoTrackingNumber": tracking,
        "shipmentAddress": {
            "fullName": "Enis Behiç Ülkümen",
            "fullAddress": "Profesör Muammer Aksoy caddesi No48/1 Poaş bayi İskenderun Hatay",
            "district": "İskenderun",
            "city": "Hatay",
        },
        "lines": [
            {"productName": "SoftHydra PAE RO-122 Çelik Su Arıtma Tankı - 8 Litre", "quantity": 2,
             "stockCode": "RO122-8L"}
            for _ in range(n_lines)
        ],
    }


def _size_mm(page):
    return (float(page.mediabox.width) * 25.4 / 72, float(page.mediabox.height) * 25.4 / 72)


def test_single_label_is_one_4x6_page():
    pdf = ty_label.build_label_pdf(_pkg())
    pages = PdfReader(io.BytesIO(pdf)).pages
    assert len(pages) == 1
    w, h = _size_mm(pages[0])
    assert abs(w - 101.6) < 0.5 and abs(h - 152.4) < 0.5


def test_single_label_rejects_missing_tracking():
    with pytest.raises(ValueError):
        ty_label.build_label_pdf(_pkg(tracking=""))
    with pytest.raises(ValueError):
        ty_label.build_label_pdf(_pkg(tracking="abc"))


def test_many_lines_still_one_page():
    pdf = ty_label.build_label_pdf(_pkg(n_lines=12))
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 1


def test_bulk_one_page_per_valid_package_and_reports_skipped():
    pdf, skipped = ty_label.build_labels_pdf(
        [_pkg("A"), _pkg("B", tracking=""), _pkg("C")])
    assert len(PdfReader(io.BytesIO(pdf)).pages) == 2
    assert [s["order_no"] for s in skipped] == ["B"]


def test_bulk_without_any_valid_package_raises():
    with pytest.raises(ValueError):
        ty_label.build_labels_pdf([_pkg(tracking="")])
