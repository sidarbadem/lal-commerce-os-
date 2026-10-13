"""Hepsiburada etiketine SoftHydra logosu + Hepsiburada teşekkür kartı basar.

HB'nin hazır PDF'indeki hiçbir öğe (barkod, 2B kod, yönlendirme kodları) silinmez
veya taşınmaz; kart yalnızca etiketin alt yarısındaki (paketleme fişi) boş alana
biner. Sayfa boyutu beklenenden farklıysa orijinal PDF aynen döner.

Bu dosyadaki metinler YALNIZCA Hepsiburada içindir (Trendyol metni yok).
"""
import io

from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

import ty_label as t

EXPECTED = (288.0, 432.0)  # 4x6 inç; HB etiketi bu boyutta gelir
TOL = 6.0

# Kart: paketleme fişinin sağ alt boş alanı (PDF koordinatı, sol-alt orijin)
CARD_X, CARD_Y, CARD_W, CARD_H = 137, 8, 145, 108


def _overlay_page(width, height):
    t._ensure_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    c.setLineWidth(1.2)
    c.setStrokeColorRGB(0, 0, 0)
    c.roundRect(CARD_X, CARD_Y, CARD_W, CARD_H, 8, stroke=1, fill=0)
    pad = 8
    t.draw_logo(c, CARD_X + pad, CARD_Y + CARD_H - pad - 36, CARD_W - 2 * pad, 36)
    t.draw_stars(c, CARD_X + CARD_W / 2, CARD_Y + CARD_H - pad - 36 - 11, 5)
    ty = CARD_Y + CARD_H - pad - 36 - 28
    for s in simpleSplit("Hepsiburada'dan siparişiniz için teşekkür ederiz!", t._BOLD, 8, CARD_W - 2 * pad)[:3]:
        t.txt(c, CARD_X + CARD_W / 2, ty, s, t._BOLD, 8, t.K, "c")
        ty -= 9.5
    for s in simpleSplit("Memnun kaldıysanız ürününüzü değerlendirmenizi bekleriz.",
                         t._REG, 6.8, CARD_W - 2 * pad)[:2]:
        t.txt(c, CARD_X + CARD_W / 2, ty - 2, s, t._REG, 6.8, t.K, "c")
        ty -= 8
    c.showPage()
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def stamp_hb_label(pdf_bytes):
    """HB etiket PDF'ine kartı basar. Beklenmedik boyutta ise aynen döner."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages:
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        if abs(w - EXPECTED[0]) <= TOL and abs(h - EXPECTED[1]) <= TOL and not page.get("/Rotate"):
            page.merge_page(_overlay_page(w, h))
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
