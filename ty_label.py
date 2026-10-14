"""Trendyol kargo etiketi -- 4x6 inç (100x150 mm) termal etiket (Xprinter XP-490B).

Sayfa 288x432 pt = yazıcının w4h6 boyutu = Hepsiburada etiket PDF'inin boyutu;
Trendyol ve HB etiketleri aynı PDF'te ölçeksiz (1:1) basılır.

  build_label_pdf(pkg)   -> tek paket, tek sayfa PDF
  build_labels_pdf(pkgs) -> her paket ayrı sayfa; (pdf_bytes, atlananlar)

Marka ayrımı: bu dosyadaki her metin YALNIZCA Trendyol etiketi içindir.
Hepsiburada etiketine basılan metinler hb_label.py'dedir.
"""
import io
import math
import os
import re

import time

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
from reportlab.graphics import renderPDF
from reportlab.graphics.barcode import code128, qr
from reportlab.graphics.shapes import Drawing
from reportlab.lib.utils import ImageReader, simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PAGE = (288, 432)  # 4x6 inç

_HERE = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.environ.get("LAL_LABEL_LOGO") or os.path.join(
    _HERE, "static", "img", "softhydra-label-logo.png")
# Trendyol mağaza sayfası (Mağaza Tasarımı > Paylaş): müşteri "Ürünlerini Değerlendir"
# bileşeninden aldığı ürünleri puanlar. QR'ı değiştirmek için .env: LAL_TY_REVIEW_URL
REVIEW_QR_URL = os.environ.get("LAL_TY_REVIEW_URL") or "https://ty.gl/6key5sehqbgi2"

_FONTS = (
    ("/System/Library/Fonts/Supplemental/Arial.ttf",
     "/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    ("/Library/Fonts/Arial.ttf", "/Library/Fonts/Arial Bold.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
)
_REG, _BOLD = "LalLabel", "LalLabel-Bold"
_ready = False
K = (0, 0, 0)
WHITE = (1, 1, 1)
M = 10


def _ensure_fonts():
    global _ready
    if _ready:
        return
    for reg, bold in _FONTS:
        if os.path.exists(reg) and os.path.exists(bold):
            pdfmetrics.registerFont(TTFont(_REG, reg))
            pdfmetrics.registerFont(TTFont(_BOLD, bold))
            _ready = True
            return
    raise RuntimeError("Türkçe karakter destekli yazı tipi bulunamadı")


# ---------- ortak yardımcılar (hb_label.py de kullanır) ----------
def tr_upper(s):
    """Türkçe büyük harf: i->İ, ı->I."""
    return (s or "").replace("i", "İ").replace("ı", "I").upper()


def fmt_phone(p):
    d = "".join(ch for ch in str(p or "") if ch.isdigit())
    if len(d) == 10:
        d = "0" + d
    if len(d) == 11 and d.startswith("0"):
        return "%s %s %s %s" % (d[:4], d[4:7], d[7:9], d[9:])
    return str(p or "").strip()


def _clean(value):
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()


def product_title(value):
    """Ürün adı: baştaki '|' / '-' artıkları (marka alanı boş gelen Trendyol adları) atılır."""
    return re.sub(r"^[\s|\-–—]+", "", _clean(value))


def _fit(text, font, size, width):
    text = _clean(text) or "-"
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while len(text) > 1 and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def _wrap_max(text, font, size, width, max_lines):
    text = _clean(text)
    if not text:
        return ["-"]
    lines = simpleSplit(text, font, size, width) or [text]
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    kept[-1] = _fit(" ".join(lines[max_lines - 1:]), font, size, width)
    return kept


def fit_size(s, font, size, width, mn=8):
    while size > mn and pdfmetrics.stringWidth(s, font, size) > width:
        size -= 0.5
    return size


def txt(c, x, y, s, font=_REG, size=10, color=K, align="l"):
    c.setFillColorRGB(*color)
    c.setFont(font, size)
    {"l": c.drawString, "r": c.drawRightString, "c": c.drawCentredString}[align](x, y, s)


def draw_logo(c, x, y, max_w, max_h):
    """SoftHydra logosu (siyah-beyaz PNG); dosya yoksa yazı logosu."""
    if LOGO_PATH and os.path.exists(LOGO_PATH):
        img = ImageReader(LOGO_PATH)
        iw, ih = img.getSize()
        s = min(max_w / iw, max_h / ih)
        c.drawImage(img, x, y + (max_h - ih * s) / 2, iw * s, ih * s, mask="auto")
        return
    txt(c, x, y + max_h * 0.3, "SoftHydra", _BOLD, fit_size("SoftHydra", _BOLD, max_h * 0.7, max_w, 9))


def _star(c, cx, cy, r):
    pts = []
    for i in range(10):
        a = math.pi / 2 + i * math.pi / 5
        rad = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    p = c.beginPath()
    p.moveTo(*pts[0])
    for q in pts[1:]:
        p.lineTo(*q)
    p.close()
    c.setFillColorRGB(*K)
    c.drawPath(p, stroke=0, fill=1)


def draw_stars(c, cx, cy, r=5, gap=3):
    total = 5 * 2 * r + 4 * gap
    x = cx - total / 2 + r
    for _ in range(5):
        _star(c, x, cy, r)
        x += 2 * r + gap


def _barcode(c, x, top, w, h, tracking, max_bw=2.4):
    bw = max_bw
    while True:
        bc = code128.Code128(tracking, barWidth=bw, barHeight=h, quiet=False)
        if bc.width <= w or bw <= 0.7:
            break
        bw -= 0.05
    c.setFillColorRGB(0, 0, 0)
    bc.drawOn(c, x + (w - bc.width) / 2, top - h)
    return top - h



# ---------- kargo firması + ürün görseli ----------
IMAGE_TIMEOUT = 4          # sn; görsel indirilemezse etiket görselsiz basılır
_IMG_CACHE = {}            # url -> PIL 'L' görsel (yalnızca başarılılar)
_IMG_FAIL = {}             # url -> başarısız deneme zamanı (5 dk tekrar denenmez)


def cargo_label(name):
    """Kargo firması adı: 'Trendyol Express Marketplace' -> 'Trendyol Express'."""
    n = _clean(name)
    return re.sub(r"\s+marketplace$", "", n, flags=re.I)


def load_product_image(src):
    """Ürün görselini gri PIL görseli olarak döner (URL, dosya yolu veya bytes).
    Yoksa / indirilemezse None -> etiket görselsiz çizilir; hiçbir zaman hata fırlatmaz."""
    if not src:
        return None
    key = src if isinstance(src, str) else None
    if key and key in _IMG_CACHE:
        return _IMG_CACHE[key]
    if key and time.time() - _IMG_FAIL.get(key, 0) < 300:
        return None
    try:
        if isinstance(src, (bytes, bytearray)):
            data = bytes(src)
        elif str(src).startswith(("http://", "https://")):
            import urllib.request
            req = urllib.request.Request(src, headers={"User-Agent": "Mozilla/5.0 LAL-label"})
            with urllib.request.urlopen(req, timeout=IMAGE_TIMEOUT) as resp:
                data = resp.read(3_000_000)
        else:
            with open(src, "rb") as fh:
                data = fh.read(3_000_000)
        img = Image.open(io.BytesIO(data))
        img.load()
        rgba = img.convert("RGBA")
        bg = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        bg.alpha_composite(rgba)
        out = bg.convert("L")
    except Exception:
        if key:
            _IMG_FAIL[key] = time.time()
        return None
    if key:
        if len(_IMG_CACHE) > 200:
            _IMG_CACHE.clear()
        _IMG_CACHE[key] = out
    return out


def _atkinson(img):
    """Atkinson dither (hatanın yalnız 6/8'ini yayar): açık alanlar temiz beyaz, koyu alanlar
    net siyah kalır; küçük (12 mm) termal baskıda Floyd-Steinberg'den çok daha okunaklıdır."""
    w, h = img.size
    px = [float(v) for v in img.tobytes()]
    for y in range(h):
        row = y * w
        for x in range(w):
            old = px[row + x]
            new = 255.0 if old > 127.0 else 0.0
            err = (old - new) / 8.0
            px[row + x] = new
            if x + 1 < w:
                px[row + x + 1] += err
            if x + 2 < w:
                px[row + x + 2] += err
            if y + 1 < h:
                nrow = row + w
                if x > 0:
                    px[nrow + x - 1] += err
                px[nrow + x] += err
                if x + 1 < w:
                    px[nrow + x + 1] += err
            if y + 2 < h:
                px[row + 2 * w + x] += err
    return Image.frombytes("L", (w, h), bytes(int(v) for v in px))


def draw_product_image(c, x, y, size, img):
    """(x, y) sol-alt. Görseli kareye sığdırır, 203 dpi'de keskinleştirip dither'layarak
    (termal yazıcı yalnız siyah/beyaz basar) ince çerçeveyle çizer."""
    n = max(int(round(size * 203 / 72)), 24)
    g = img
    bbox = ImageOps.invert(g).point(lambda v: 255 if v > 24 else 0).getbbox()
    if bbox:  # beyaz kenar boşluklarını at -> ürün kareyi daha çok doldurur
        pad = max(2, int(0.03 * max(g.size)))
        g = g.crop((max(bbox[0] - pad, 0), max(bbox[1] - pad, 0),
                    min(bbox[2] + pad, g.width), min(bbox[3] + pad, g.height)))
    g.thumbnail((n, n), Image.LANCZOS)
    g = ImageOps.autocontrast(g, cutoff=1)
    g = ImageEnhance.Contrast(g).enhance(1.3)
    g = g.filter(ImageFilter.UnsharpMask(radius=1.2, percent=140, threshold=2))
    sq = Image.new("L", (n, n), 255)
    sq.paste(g, ((n - g.width) // 2, (n - g.height) // 2))
    c.drawImage(ImageReader(_atkinson(sq)), x, y, size, size)
    c.setLineWidth(0.8)
    c.setStrokeColorRGB(*K)
    c.rect(x, y, size, size, stroke=1, fill=0)


def draw_header(c, order_no, cargo, top, logo_h=34):
    """Üst şerit: solda logo, sağda KARGO firması (siyah hap) + sipariş no."""
    W = PAGE[0]
    draw_logo(c, M, top - logo_h, 130, logo_h)
    right = W - M
    if cargo:
        pre = "KARGO "
        size = fit_size(cargo, _BOLD, 11, 112, 7)
        w = pdfmetrics.stringWidth(pre, _REG, 6) + pdfmetrics.stringWidth(cargo, _BOLD, size) + 18
        c.setFillColorRGB(*K)
        c.roundRect(right - w, top - 20, w, 20, 10, stroke=0, fill=1)
        x = right - w + 9
        txt(c, x, top - 13, pre, _REG, 6, WHITE)
        txt(c, x + pdfmetrics.stringWidth(pre, _REG, 6), top - 14, cargo, _BOLD, size, WHITE)
        txt(c, right, top - 32, "Sipariş: " + order_no, _BOLD, 8, K, "r")
    else:
        pw = pdfmetrics.stringWidth(order_no, _BOLD, 9) + 18
        c.setFillColorRGB(*K)
        c.roundRect(right - pw, top - 24, pw, 18, 9, stroke=0, fill=1)
        txt(c, right - pw / 2, top - 18, order_no, _BOLD, 9, WHITE, "c")


def _qr(c, x, y, size, data):
    w = qr.QrCodeWidget(data)
    b = w.getBounds()
    d = Drawing(size, size, transform=[size / (b[2] - b[0]), 0, 0, size / (b[3] - b[1]), 0, 0])
    d.add(w)
    renderPDF.draw(d, c, x, y)


def _chip(c, label, x, y):
    w = pdfmetrics.stringWidth(label, _BOLD, 6.5) + 14
    c.setFillColorRGB(*K)
    c.roundRect(x, y - 3.5, w, 12, 6, stroke=0, fill=1)
    txt(c, x + 7, y, label, _BOLD, 6.5, WHITE)


# ---------- paket verisi ----------
def _parse(pkg):
    tracking = _clean(pkg.get("cargoTrackingNumber"))
    if not tracking.isdigit():
        raise ValueError("Paketin kargo takip numarası yok veya geçersiz")
    addr = pkg.get("shipmentAddress") or {}
    name = _clean(addr.get("fullName")) or _clean(" ".join(
        str(x) for x in (pkg.get("customerFirstName"), pkg.get("customerLastName")) if x))
    full = _clean(addr.get("fullAddress")) or _clean(" ".join(
        str(x) for x in (addr.get("address1"), addr.get("address2")) if x))
    ilce = tr_upper(_clean(addr.get("district")))
    il = tr_upper(_clean(addr.get("city")))
    return {
        "tracking": tracking,
        "name": name,
        "phone": fmt_phone(addr.get("phone")),
        "address": full,
        "ilce": ilce,
        "il": il,
        "region": " / ".join(x for x in (ilce, il) if x),
        "order_no": _clean(pkg.get("orderNumber")),
        "cargo": cargo_label(pkg.get("cargoProviderName")),
        "items": pkg.get("lines") or [],
    }


# ---------- çizim ----------
def _draw_label(c, d):
    W, H = PAGE
    iw = W - 2 * M
    y = H - M

    # üst: logo + kargo firması + sipariş no
    draw_header(c, d["order_no"], d["cargo"], y)
    y -= 42
    note = ("Kargo şirketinin dikkatine, bu bir trendyol.com gönderisidir. "
            "Trendyol anlaşmasına uygun işlem yapabilirsiniz.")
    for s in simpleSplit(note, _REG, 6.3, iw)[:2]:
        txt(c, M, y, s, _REG, 6.3)
        y -= 7.5
    y -= 2

    # kargo barkodu kartı
    c.setLineWidth(1.4)
    c.setStrokeColorRGB(*K)
    ch = 78
    c.roundRect(M, y - ch, iw, ch, 9, stroke=1, fill=0)
    _chip(c, "KARGO BARKODU", M + 9, y - 14)
    yb = _barcode(c, M + 9, y - 22, iw - 18, 40, d["tracking"])
    txt(c, W / 2, yb - 14, d["tracking"], _BOLD, 14, K, "c")
    y -= ch + 6

    # alıcı kartı (yüksekliği içeriğe göre)
    name_lines = _wrap_max(d["name"], _BOLD, 13.5, iw - 18, 1)
    addr_lines = _wrap_max(d["address"], _REG, 10, iw - 18, 3)
    ah = 28 + 15 * len(name_lines) + (14 if d["phone"] else 0) + 12 * len(addr_lines) + 23
    c.roundRect(M, y - ah, iw, ah, 9, stroke=1, fill=0)
    _chip(c, "ALICI", M + 9, y - 14)
    ty = y - 31
    for s in name_lines:
        txt(c, M + 9, ty, s, _BOLD, 13.5)
        ty -= 15
    if d["phone"]:
        txt(c, M + 9, ty, "Tel: " + d["phone"], _BOLD, 10.5)
        ty -= 14
    for s in addr_lines:
        txt(c, M + 9, ty, s, _REG, 10)
        ty -= 12
    if d["region"]:
        txt(c, M + 9, y - ah + 10, d["region"], _BOLD, fit_size(d["region"], _BOLD, 15, iw - 18, 10))
    y -= ah + 6

    # alt: teşekkür + QR kartı (Trendyol)
    th = 52
    c.roundRect(M, M, iw, th, 9, stroke=1, fill=0)
    qr_size = 44
    text_w = iw - 18 - qr_size - 8
    draw_stars(c, M + 9 + 28, M + th - 12, 5)
    ty = M + th - 26
    for s in simpleSplit("Trendyol'dan siparişiniz için teşekkür ederiz!", _BOLD, 8, text_w)[:2]:
        txt(c, M + 9, ty, s, _BOLD, 8)
        ty -= 9.5
    for s in simpleSplit("Memnun kaldıysanız QR kodu okutup ürününüzü değerlendirebilirsiniz.",
                         _REG, 6.8, text_w)[:2]:
        txt(c, M + 9, ty - 1, s, _REG, 6.8)
        ty -= 8
    if REVIEW_QR_URL:
        _qr(c, W - M - 9 - qr_size, M + (th - qr_size) / 2, qr_size, REVIEW_QR_URL)

    # ürünler kartı (kalan alan): adet rozeti + ürün görseli + ad
    ph = y - (M + th + 6)
    c.roundRect(M, y - ph, iw, ph, 9, stroke=1, fill=0)
    _chip(c, "ÜRÜNLER", M + 9, y - 14)
    row_top = y - 26
    floor = y - ph + 5
    items = d["items"]
    iw_text = iw - 18
    imgs = [load_product_image(ln.get("imageUrl")) for ln in items]

    def plan(mode):
        """mode A: görselli | B: görselsiz 2 satır | C: tek satır sıkı. [(satır yüksekliği, ad satırları, kod, görsel)]"""
        out = []
        for ln, im in zip(items, imgs):
            code = _clean(ln.get("stockCode") or ln.get("merchantSku"))
            title = product_title(ln.get("productName"))
            if mode == "C":
                nm = _wrap_max(("%s · %s" % (code, title)) if code else title, _BOLD, 7.5, iw_text - 25, 1)
                out.append((14.5, nm, "", None))
                continue
            use_img = im if mode == "A" else None
            tx_w = iw_text - 25 - (39 if use_img else 0)
            nm = _wrap_max(title, _BOLD, 8, tx_w, 3 if (use_img and len(items) == 1) else 2)
            th = len(nm) * 9.5 + (9 if code else 0)
            out.append((max(th, 34 if use_img else 0) + 5, nm, code, use_img))
        return out

    avail = row_top - floor
    chosen = None
    for mode in ("A", "B", "C"):
        rows = plan(mode)
        if sum(r[0] for r in rows) <= avail:
            chosen = (mode, rows)
            break
    if chosen is None:
        chosen = ("C", plan("C"))
    mode, rows = chosen
    shown = 0
    for ln, (row_h, nm, code, img) in zip(items, rows):
        reserve = 10 if shown + 1 < len(items) else 0
        if shown and row_top - row_h < floor + reserve:
            break
        qty = str(ln.get("quantity") or 1)
        bw, bh, bf = (22, 20, 12) if mode != "C" else (20, 12, 9)
        c.setFillColorRGB(*K)
        c.roundRect(M + 9, row_top - bh, bw, bh, 5 if mode != "C" else 4, stroke=0, fill=1)
        txt(c, M + 9 + bw / 2, row_top - bh + (6 if mode != "C" else 3.5), qty, _BOLD, bf, WHITE, "c")
        text_x = M + 9 + 25 + (39 if img else 0)
        if img:
            draw_product_image(c, M + 9 + 25, row_top - 34, 34, img)
        ty = row_top - (7 if mode != "C" else 8.8)
        for s_ in nm:
            txt(c, text_x, ty, s_, _BOLD, 8 if mode != "C" else 7.5)
            ty -= 9.5
        if code:
            txt(c, text_x, ty, code, _REG, 7)
        row_top -= row_h
        shown += 1
    if shown < len(items):
        txt(c, M + 9, floor, "+ %d ürün daha (pakette)" % (len(items) - shown), _BOLD, 7.5)


def build_label_pdf(pkg):
    """Tek paket -> tek sayfa 4x6 inç PDF."""
    _ensure_fonts()
    d = _parse(pkg)
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGE)
    c.setTitle("Trendyol kargo etiketi %s" % d["order_no"])
    _draw_label(c, d)
    c.showPage()
    c.save()
    return buf.getvalue()


def build_labels_pdf(pkgs):
    """Birden çok paket -> her biri ayrı sayfa. (pdf_bytes, atlananlar)."""
    _ensure_fonts()
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=PAGE)
    c.setTitle("Trendyol kargo etiketleri")
    skipped = []
    done = 0
    for pkg in pkgs:
        try:
            d = _parse(pkg)
        except ValueError as exc:
            skipped.append({"order_no": _clean(pkg.get("orderNumber")), "reason": str(exc)})
            continue
        _draw_label(c, d)
        c.showPage()
        done += 1
    if not done:
        raise ValueError("Üretilecek geçerli etiket yok")
    c.save()
    return buf.getvalue(), skipped
