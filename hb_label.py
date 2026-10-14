"""Hepsiburada etiketi: SoftHydra markalı TEK etiket (4x6 inç).

build_hb_label(pdf_bytes, order)
    HB'nin resmi barkod/2B kod/yönlendirme bloğunu aynen (1:1, yeniden çizmeden)
    etiketin içine alır; üstüne logo + kargo firması şeridi, altına alıcı / ürünler
    (görselli) / teşekkür kartlarını çizer. order:
      {"order_no", "cargo", "name", "address", "ilce", "il", "phone"(ops.),
       "items": [{"name", "qty", "sku", "imageUrl"}]}
stamp_hb_label(pdf_bytes)
    Sipariş verisi yoksa yedek: HB etiketinin boş alanına yalnız logolu kart basar.

İkisi de beklenmedik sayfa boyutunda orijinal PDF'i aynen döndürür.
Bu dosyadaki metinler YALNIZCA Hepsiburada içindir (Trendyol metni yok).
"""
import io

from pypdf import PdfReader, PdfWriter, Transformation
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas

import ty_label as t

EXPECTED = (288.0, 432.0)   # 4x6 inç
TOL = 6.0
W, H = 288, 432
M = 10
SHIFT = -42                  # HB bloğunu aşağı kaydır: üstte logo şeridi için yer açılır
BLOCK_BOTTOM = 174           # kaydırılmış bloğun alt kenarı (pdf y)
LOW_TOP, LOW_BOT = BLOCK_BOTTOM - 6, 8

THANKS = "Hepsiburada'dan siparişiniz için teşekkür ederiz!"
REVIEW = "Memnun kaldıysanız ürününüzü değerlendirmenizi bekleriz."


def _size_ok(page):
    w, h = float(page.mediabox.width), float(page.mediabox.height)
    return abs(w - EXPECTED[0]) <= TOL and abs(h - EXPECTED[1]) <= TOL and not page.get("/Rotate")


# ---------- tam etiket ----------
def _box(c, x, y, w, h, r=8, lw=1.3):
    c.setLineWidth(lw)
    c.setStrokeColorRGB(*t.K)
    c.roundRect(x, y, w, h, r, stroke=1, fill=0)


def _rows(c, items, x, top, w, floor, nsz=6.4, img=26, badge=14, lines=3):
    """Adet rozeti + ürün görseli + ad. Sığmayan ürünler '+ N ürün daha' olur."""
    y = top
    shown = 0
    for it in items:
        im = t.load_product_image(it.get("imageUrl"))
        tx = x + badge + 4 + (img + 4 if im else 0)
        nm = t._wrap_max(t.product_title(it.get("name")), t._BOLD, nsz, x + w - tx, lines)
        sku = t._clean(it.get("sku"))
        th = len(nm) * (nsz + 1.5) + (8 if sku else 0)
        rh = max(th, img if im else 0) + 5
        reserve = 9 if shown + 1 < len(items) else 0
        if shown and y - rh < floor + reserve:
            break
        c.setFillColorRGB(*t.K)
        c.roundRect(x, y - badge, badge, badge, 4, stroke=0, fill=1)
        t.txt(c, x + badge / 2, y - badge + 4, str(it.get("qty") or 1), t._BOLD, 9, t.WHITE, "c")
        if im:
            t.draw_product_image(c, x + badge + 4, y - img, img, im)
        ty = y - nsz - 0.5
        for s in nm:
            t.txt(c, tx, ty, s, t._BOLD, nsz)
            ty -= nsz + 1.5
        if sku:
            t.txt(c, tx, ty, sku, t._REG, nsz - 1)
        y -= rh
        shown += 1
    if shown < len(items):
        t.txt(c, x, floor, "+ %d ürün daha" % (len(items) - shown), t._BOLD, 6.8)


def _draw_lower(c, o):
    top = LOW_TOP
    r1, r2 = 104, 50
    lw = 122
    rx = M + lw + 6
    rw = W - M - rx
    y1 = top - r1
    # alıcı kartı
    _box(c, M, y1, lw, r1)
    t._chip(c, "ALICI", M + 8, top - 13)
    ty = top - 29
    for s in t._wrap_max(o.get("name"), t._BOLD, 10.5, lw - 16, 2):
        t.txt(c, M + 8, ty, s, t._BOLD, 10.5)
        ty -= 12
    if o.get("phone"):
        t.txt(c, M + 8, ty, "Tel: " + t.fmt_phone(o["phone"]), t._BOLD, 8)
        ty -= 10
    if t._clean(o.get("address")):
        for s in t._wrap_max(o.get("address"), t._REG, 7.2, lw - 16, 5 if not o.get("phone") else 4):
            t.txt(c, M + 8, ty, s, t._REG, 7.2)
            ty -= 8.5
    ilce, il = t.tr_upper(t._clean(o.get("ilce"))), t.tr_upper(t._clean(o.get("il")))
    region = " / ".join(x for x in (ilce, il) if x)
    if region:
        t.txt(c, M + 8, y1 + 9, region, t._BOLD, t.fit_size(region, t._BOLD, 11, lw - 16, 7))
    # ürünler kartı
    _box(c, rx, y1, rw, r1)
    t._chip(c, "ÜRÜNLER", rx + 8, top - 13)
    _rows(c, o.get("items") or [], rx + 7, top - 24, rw - 12, y1 + 5)
    # teşekkür kartı
    y2 = y1 - 6 - r2
    _box(c, M, y2, W - 2 * M, r2)
    t.draw_stars(c, W / 2, y2 + r2 - 10, 4.5)
    ty = y2 + r2 - 22
    for s in simpleSplit(THANKS, t._BOLD, 7.8, W - 2 * M - 20)[:2]:
        t.txt(c, W / 2, ty, s, t._BOLD, 7.8, t.K, "c")
        ty -= 9.3
    for s in simpleSplit(REVIEW, t._REG, 6.6, W - 2 * M - 20)[:2]:
        t.txt(c, W / 2, ty, s, t._REG, 6.6, t.K, "c")
        ty -= 8.1


def _full_overlay(o):
    t._ensure_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, 0, W, BLOCK_BOTTOM - 1, stroke=0, fill=1)   # HB'nin eski alt bölümünü kapat
    t.draw_header(c, t._clean(o.get("order_no")), t.cargo_label(o.get("cargo")), H - 8, 30)
    _draw_lower(c, o)
    c.showPage()
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def build_hb_label(pdf_bytes, order):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages:
        out_page = writer.add_page(page)
        if _size_ok(page):
            out_page.add_transformation(Transformation().translate(0, SHIFT))
            out_page.merge_page(_full_overlay(order))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ---------- yedek: yalnız logolu kart ----------
CARD_X, CARD_Y, CARD_W, CARD_H = 137, 8, 145, 108


def _card_overlay(width, height):
    t._ensure_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    _box(c, CARD_X, CARD_Y, CARD_W, CARD_H, 8, 1.2)
    pad = 8
    t.draw_logo(c, CARD_X + pad, CARD_Y + CARD_H - pad - 36, CARD_W - 2 * pad, 36)
    t.draw_stars(c, CARD_X + CARD_W / 2, CARD_Y + CARD_H - pad - 36 - 11, 5)
    ty = CARD_Y + CARD_H - pad - 36 - 28
    for s in simpleSplit(THANKS, t._BOLD, 8, CARD_W - 2 * pad)[:3]:
        t.txt(c, CARD_X + CARD_W / 2, ty, s, t._BOLD, 8, t.K, "c")
        ty -= 9.5
    for s in simpleSplit(REVIEW, t._REG, 6.8, CARD_W - 2 * pad)[:2]:
        t.txt(c, CARD_X + CARD_W / 2, ty - 2, s, t._REG, 6.8, t.K, "c")
        ty -= 8
    c.showPage()
    c.save()
    buf.seek(0)
    return PdfReader(buf).pages[0]


def stamp_hb_label(pdf_bytes):
    reader = PdfReader(io.BytesIO(pdf_bytes))
    writer = PdfWriter()
    for page in reader.pages:
        out_page = writer.add_page(page)
        if _size_ok(page):
            out_page.merge_page(_card_overlay(float(page.mediabox.width), float(page.mediabox.height)))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
