"""Hepsiburada etiketi: SoftHydra markalı TEK etiket (4x6 inç).

build_hb_label(pdf_bytes, order)
    HB'nin resmi barkod/2B kod/yönlendirme bloğunu aynen (1:1, yeniden çizmeden)
    etiketin içine alır; üstüne logo + kargo firması şeridi, altına alıcı / ürünler
    (görselli) / teşekkür kartlarını çizer. order:
      {"order_no", "cargo", "name", "address", "ilce", "il", "phone"(ops.),
       "items": [{"name", "qty", "sku", "imageUrl"}]}
stamp_hb_label(pdf_bytes)
    Sipariş verisi yoksa yedek: HB etiketinin boş alanına yalnız logolu kart basar.

HB etiketi 4x6 değilse (ör. Aras Kargo etiketi büyük/kare sayfanın köşesinde gelir)
sayfadaki içeriğin sınırı bulunur, o blok 4x6 etiketin içine sığdırılır; tasarım aynı.
Bu dosyadaki metinler YALNIZCA Hepsiburada içindir (Trendyol metni yok).
"""
import io

from pypdf import PdfReader, PdfWriter, Transformation
from pypdf.generic import ContentStream, RectangleObject
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


# ---------- 4x6 olmayan HB sayfaları: içerik sınırı + sığdırma ----------
def _mul(a, b):
    """PDF afin çarpımı (önce a, sonra b)."""
    return (a[0] * b[0] + a[1] * b[2], a[0] * b[1] + a[1] * b[3],
            a[2] * b[0] + a[3] * b[2], a[2] * b[1] + a[3] * b[3],
            a[4] * b[0] + a[5] * b[2] + b[4], a[4] * b[1] + a[5] * b[3] + b[5])


def _pt(m, x, y):
    return (x * m[0] + y * m[2] + m[4], x * m[1] + y * m[3] + m[5])


def _nums(ops):
    out = []
    for v in ops:
        try:
            out.append(float(v))
        except Exception:
            return None
    return out


_PAINT = {b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"}
_FILL_ONLY = {b"f", b"F", b"f*"}


def _ink_points(stream, resources, reader, ctm, page_area, depth=0):
    """Sayfada gerçekten görünen öğelerin (yol, metin, görsel) köşe noktaları."""
    pts = []
    try:
        ops = ContentStream(stream, reader).operations
    except Exception:
        return pts
    xobjs = {}
    try:
        xobjs = (resources or {}).get("/XObject") or {}
        xobjs = xobjs.get_object() if hasattr(xobjs, "get_object") else xobjs
    except Exception:
        xobjs = {}
    stack = []
    path = []
    white = False
    tm = tlm = (1, 0, 0, 1, 0, 0)
    fs, lead = 10.0, 0.0
    for operands, op in ops:
        if op == b"q":
            stack.append((ctm, white))
        elif op == b"Q":
            if stack:
                ctm, white = stack.pop()
        elif op == b"cm":
            n = _nums(operands)
            if n and len(n) == 6:
                ctm = _mul(tuple(n), ctm)
        elif op in (b"g", b"rg", b"k", b"sc", b"scn"):
            n = _nums(operands) or []
            if op == b"k":
                white = bool(n) and all(v <= 0.02 for v in n)
            else:
                white = bool(n) and all(v >= 0.98 for v in n)
        elif op in (b"m", b"l"):
            n = _nums(operands)
            if n:
                path.append(_pt(ctm, n[0], n[1]))
        elif op in (b"c", b"v", b"y"):
            n = _nums(operands)
            if n:
                path.append(_pt(ctm, n[-2], n[-1]))
        elif op == b"re":
            n = _nums(operands)
            if n and len(n) == 4:
                x, y, w, h = n
                path += [_pt(ctm, x, y), _pt(ctm, x + w, y), _pt(ctm, x, y + h), _pt(ctm, x + w, y + h)]
        elif op in _PAINT:
            if path and not (white and op in _FILL_ONLY):
                xs = [p[0] for p in path]
                ys = [p[1] for p in path]
                if (max(xs) - min(xs)) * (max(ys) - min(ys)) < 0.8 * page_area:  # sayfa zemini değil
                    pts += path
            path = []
        elif op == b"n":
            path = []
        elif op == b"BT":
            tm = tlm = (1, 0, 0, 1, 0, 0)
        elif op == b"Tf":
            n = _nums(operands[1:])
            if n:
                fs = abs(n[0]) or fs
        elif op == b"TL":
            n = _nums(operands)
            if n:
                lead = n[0]
        elif op in (b"Td", b"TD"):
            n = _nums(operands)
            if n:
                if op == b"TD":
                    lead = -n[1]
                tlm = _mul((1, 0, 0, 1, n[0], n[1]), tlm)
                tm = tlm
        elif op == b"Tm":
            n = _nums(operands)
            if n and len(n) == 6:
                tm = tlm = tuple(n)
        elif op in (b"T*", b"'", b'"'):
            tlm = _mul((1, 0, 0, 1, 0, -lead), tlm)
            tm = tlm
        if op in (b"Tj", b"TJ", b"'", b'"'):
            arg = operands[-1] if operands else b""
            if op == b"TJ":
                n_ch = sum(len(x) for x in arg if isinstance(x, (str, bytes)))
            else:
                n_ch = len(arg) if isinstance(arg, (str, bytes)) else 1
            w = fs * 0.55 * max(n_ch, 1)
            m = _mul(tm, ctm)
            pts += [_pt(m, 0, -fs * 0.2), _pt(m, w, fs)]
            tm = _mul((1, 0, 0, 1, w, 0), tm)
        elif op == b"INLINE IMAGE":
            pts += [_pt(ctm, 0, 0), _pt(ctm, 1, 1)]
        elif op == b"Do" and operands:
            try:
                xo = xobjs[operands[0]].get_object()
            except Exception:
                continue
            sub = xo.get("/Subtype")
            if sub == "/Image":
                pts += [_pt(ctm, 0, 0), _pt(ctm, 1, 0), _pt(ctm, 0, 1), _pt(ctm, 1, 1)]
            elif sub == "/Form" and depth < 4:
                fm = tuple(float(v) for v in (xo.get("/Matrix") or (1, 0, 0, 1, 0, 0)))
                pts += _ink_points(xo, xo.get("/Resources") or resources, reader,
                                   _mul(fm, ctm), page_area, depth + 1)
    return pts


def content_bbox(page, reader=None, pad=3.0):
    """Sayfadaki içeriğin sınır kutusu (x0, y0, x1, y1); bulunamazsa sayfanın tamamı."""
    mb = page.mediabox
    px0, py0, px1, py1 = float(mb.left), float(mb.bottom), float(mb.right), float(mb.top)
    full = (px0, py0, px1, py1)
    try:
        contents = page.get_contents()
        if contents is None:
            return full
        pts = _ink_points(contents, page.get("/Resources"), reader,
                          (1, 0, 0, 1, 0, 0), (px1 - px0) * (py1 - py0))
    except Exception:
        return full
    if not pts:
        return full
    x0 = max(px0, min(p[0] for p in pts) - pad)
    y0 = max(py0, min(p[1] for p in pts) - pad)
    x1 = min(px1, max(p[0] for p in pts) + pad)
    y1 = min(py1, max(p[1] for p in pts) + pad)
    if x1 - x0 < 20 or y1 - y0 < 20:
        return full
    return (x0, y0, x1, y1)


def _fit_into(page, reader, box, max_scale=2.0):
    """Sayfanın içerik bloğunu box=(x, y, w, h) içine (oran korunarak, üste yaslı) yerleştirir,
    sayfayı 4x6 yapar. Yerleşen bloğun (x0, y0, x1, y1) kutusunu döndürür."""
    if page.get("/Rotate"):
        page.transfer_rotation_to_content()
    bx0, by0, bx1, by1 = content_bbox(page, reader)
    bw, bh = bx1 - bx0, by1 - by0
    x, y, w, h = box
    s = min(w / bw, h / bh, max_scale)
    dx = x + (w - bw * s) / 2
    dy = y + h - bh * s
    page.add_transformation(Transformation().translate(-bx0, -by0).scale(s, s).translate(dx, dy))
    rect = RectangleObject([0, 0, W, H])
    page.mediabox = rect
    page.cropbox = rect
    for k in ("/TrimBox", "/BleedBox", "/ArtBox"):
        if k in page:
            del page[k]
    return (dx, dy, dx + bw * s, dy + bh * s)


def _mask(c, keep):
    """keep dışındaki her şeyi beyazla örter (sığdırılan sayfanın taşan kısımları)."""
    kx0, ky0, kx1, ky1 = keep
    c.setFillColorRGB(1, 1, 1)
    c.rect(0, ky1, W, H - ky1, stroke=0, fill=1)
    c.rect(0, 0, W, ky0, stroke=0, fill=1)
    c.rect(0, 0, kx0, H, stroke=0, fill=1)
    c.rect(kx1, 0, W - kx1, H, stroke=0, fill=1)


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
        img, lines = int(max(26, min(60, top - floor - 8))), 6
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
            ibw = t.image_box(im, img, w * 0.4)[0] if im else 0
            tx_w = w - badge - 4 - (ibw + 4 if im else 0)
            nm = t._wrap_max(title, t._BOLD, nsz, tx_w, lines if mode == "A" else 2)
            th = len(nm) * (nsz + 1.5) + (9 if sku else 0)
            out.append((max(th, t.image_box(im, img, w * 0.4)[1] if im else 0) + 5, nm, sku, im, nsz))
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
        tx = x + b + 4
        if im:
            ibw, _ = t.draw_product_image(c, x + b + 4, y - img, img, im, w * 0.4)
            tx += ibw + 4
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


def _full_overlay(o, keep=None):
    t._ensure_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(W, H))
    if keep:
        _mask(c, keep)
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
        else:  # ör. Aras Kargo: büyük sayfanın köşesindeki blok -> 4x6 içine
            keep = _fit_into(out_page, reader, (M, BLOCK_BOTTOM, W - 2 * M, H + SHIFT - BLOCK_BOTTOM))
            out_page.merge_page(_full_overlay(order, keep))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


# ---------- yedek: yalnız logolu kart ----------
CARD_X, CARD_Y, CARD_W, CARD_H = 137, 8, 145, 108


def _card_overlay(width, height, keep=None):
    t._ensure_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=(width, height))
    if keep:
        _mask(c, keep)
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
        else:
            top = CARD_Y + CARD_H + 6
            keep = _fit_into(out_page, reader, (M, top, W - 2 * M, H - M - top))
            out_page.merge_page(_card_overlay(W, H, keep))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
