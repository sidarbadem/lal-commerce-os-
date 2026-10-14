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
    """Adet rozeti + ürün görseli + ad. Önce görselli, sığmazsa görselsiz, sonra tek satır sıkı mod;
    yine sığmayanlar '+ N ürün daha' olur."""
    ims = [t.load_product_image(it.get("imageUrl")) for it in items]
    if len(items) == 1:  # tek ürün: kartta yer var -> daha büyük görsel, ad kesilmesin
        img, lines = 36, 5
    avail = top - floor

    def plan(mode):
        out = []
        for it, im0 in zip(items, ims):
            sku = t._clean(it.get("sku"))
            title = t.product_title(it.get("name"), sku)
            if mode == "C":
                nm = t._wrap_max(("%s · %s" % (sku, title)) if sku else title, t._BOLD, 6.2, w - 12 - 4, 1)
                out.append((12, nm, "", None, 6.2))
                continue
            if mode == "B2":
                nm = t._wrap_max(title, t._BOLD, nsz, w - badge - 4, 2)
                out.append((len(nm) * (nsz + 1.5) + 4, nm, "", None, nsz))
                continue
            im = im0 if mode == "A" else None
            tx_w = w - badge - 4 - (img + 4 if im else 0)
            nm = t._wrap_max(title, t._BOLD, nsz, tx_w, lines if mode == "A" else 2)
            th = len(nm) * (nsz + 1.5) + (9 if sku else 0)
            out.append((max(th, img if im else 0) + 5, nm, sku, im, nsz))
        return out

    chosen = None
    for mode in ("A", "B", "B2", "C"):
        pl = plan(mode)
        if sum(r[0] for r in pl) <= avail:
            chosen = (mode, pl)
            break
    mode, pl = chosen or ("C", plan("C"))
    y = top
    shown = 0
    for it, (rh, nm, sku, im, sz) in zip(items, pl):
        reserve = 9 if shown + 1 < len(items) else 0
        if shown and y - rh < floor + reserve:
            break
        b = badge if mode != "C" else 12
        c.setFillColorRGB(*t.K)
        c.roundRect(x, y - b, b, b, 4 if mode != "C" else 3, stroke=0, fill=1)
        q = str(it.get("qty") or 1)
        qt = ("×" + q) if q != "1" else q
        t.txt(c, x + b / 2, y - b + (4 if mode != "C" else 3), qt, t._BOLD,
              t.fit_size(qt, t._BOLD, 9 if mode != "C" else 8, b - 2, 5.5), t.WHITE, "c")
        tx = x + b + 4 + (img + 4 if im else 0)
        if im:
            t.draw_product_image(c, x + b + 4, y - img, img, im)
        ty = y - sz - 0.5 - (1 if mode == "C" else 0)
        for s in nm:
            t.txt(c, tx, ty, s, t._BOLD, sz)
            ty -= sz + 1.5
        if sku:
            t.txt(c, tx, ty - 0.5, sku, t._BOLD, sz + 0.6)
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
    nm = None
    for nsz in (10.5, 9.5, 8.5, 7.5):
        nm = t._wrap_max(t.tr_title(o.get("name")), t._BOLD, nsz, lw - 16, 2)
        if not nm[-1].endswith("…"):
            break
    else:
        nm = t._wrap_max(t.tr_title(o.get("name")), t._BOLD, 7.5, lw - 16, 3)
    for s in nm:
        t.txt(c, M + 8, ty, s, t._BOLD, nsz)
        ty -= nsz + 1.5
    if o.get("phone"):
        t.txt(c, M + 8, ty, "Tel: " + t.fmt_phone(o["phone"]), t._BOLD, 8)
        ty -= 10
    if t._clean(o.get("address")):
        region_top = y1 + 24  # il/ilçe satırının üstü; adres bunun altına inmez
        for asz, gap in ((7.2, 8.5), (6.4, 7.5), (5.8, 6.8)):
            n = max(1, int((ty - region_top) / gap) + 1)
            al = t._wrap_max(o.get("address"), t._REG, asz, lw - 16, n)
            if not al[-1].endswith("…"):
                break
        for s in al:
            t.txt(c, M + 8, ty, s, t._REG, asz)
            ty -= gap
    ilce, il = t.tr_upper(t._clean(o.get("ilce"))), t.tr_upper(t._clean(o.get("il")))
    region = " / ".join(x for x in (ilce, il) if x)
    if region:
        t.txt(c, M + 8, y1 + 9, region, t._BOLD, t.fit_size(region, t._BOLD, 11, lw - 16, 7))
    # ürünler kartı
    _box(c, rx, y1, rw, r1)
    t._chip(c, "ÜRÜNLER", rx + 8, top - 13)
    tq = sum(int(i.get("qty") or 1) for i in (o.get("items") or []))
    if tq > 1:
        t.txt(c, rx + rw - 7, top - 12, "%d ADET" % tq, t._BOLD, 6.8, t.K, "r")
    _rows(c, o.get("items") or [], rx + 7, top - 24, rw - 12, y1 + 5)
    # teşekkür kartı
    y2 = y1 - 6 - r2
    _box(c, M, y2, W - 2 * M, r2)
    thanks = simpleSplit(THANKS, t._BOLD, 7.8, W - 2 * M - 20)[:2]
    review = simpleSplit(REVIEW, t._REG, 6.6, W - 2 * M - 20)[:2]
    content_h = 9 + 12 + len(thanks) * 9.3 + len(review) * 8.1
    off = max((r2 - content_h) / 2, 4)
    t.draw_stars(c, W / 2, y2 + r2 - off - 4.5, 4.5)
    ty = y2 + r2 - off - 9 - 11
    for s in thanks:
        t.txt(c, W / 2, ty, s, t._BOLD, 7.8, t.K, "c")
        ty -= 9.3
    for s in review:
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
