"""Trendyol kargo etiketi -- 4x6 inç (~100x150 mm) termal etiket (Xprinter XP-490B).

Sayfa 288x432 pt = yazıcının w4h6 boyutu = HB etiket PDF'inin boyutu; böylece
Trendyol ve HB etiketleri aynı PDF'te 1:1 (ölçeksiz) basılır.

build_label_pdf(pkg)   -> tek paket, tek sayfa PDF (eski imza korundu)
build_labels_pdf(pkgs) -> birden çok paket, her paket ayrı sayfa;
                          (pdf_bytes, atlananlar) döner
"""
import io
import os
import re

from reportlab.graphics.barcode import code128
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

PAGE = (288, 432)  # 4x6 inç; 100x150 mm etiket rulosu için w4h6

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
GRAY = (0.35, 0.35, 0.35)

MARGIN = 9
MAX_ADDR_LINES = 5
MAX_NAME_LINES = 2
MAX_ITEM_LINES = 2


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


def _clean(value):
    return re.sub(r"\s+", " ", str(value if value is not None else "")).strip()


def _fit(text, font, size, width):
    text = _clean(text) or "-"
    if pdfmetrics.stringWidth(text, font, size) <= width:
        return text
    while len(text) > 1 and pdfmetrics.stringWidth(text + "…", font, size) > width:
        text = text[:-1]
    return text + "…"


def _wrap_max(text, font, size, width, max_lines):
    """Metni sar; max_lines'ı aşarsa son satırı '…' ile kes."""
    text = _clean(text)
    if not text:
        return ["-"]
    lines = simpleSplit(text, font, size, width) or [text]
    if len(lines) <= max_lines:
        return lines
    kept = lines[:max_lines]
    rest = " ".join(lines[max_lines - 1:])
    kept[-1] = _fit(rest, font, size, width)
    return kept


def _parse(pkg):
    tracking = _clean(pkg.get("cargoTrackingNumber"))
    if not tracking.isdigit():
        raise ValueError("Paketin kargo takip numarası yok veya geçersiz")
    addr = pkg.get("shipmentAddress") or {}
    name = _clean(addr.get("fullName")) or _clean(" ".join(
        str(x) for x in (pkg.get("customerFirstName"), pkg.get("customerLastName")) if x))
    full = _clean(addr.get("fullAddress")) or _clean(" ".join(
        str(x) for x in (addr.get("address1"), addr.get("address2")) if x))
    region = "/".join(x for x in (_clean(addr.get("district")), _clean(addr.get("city"))) if x)
    return {
        "tracking": tracking,
        "name": name,
        "address": full,
        "region": region,
        "order_no": _clean(pkg.get("orderNumber")),
        "items": pkg.get("lines") or [],
    }


def _hline(c, y, x0, x1, width=0.8):
    c.setLineWidth(width)
    c.setStrokeColorRGB(0, 0, 0)
    c.line(x0, y, x1, y)


def _draw_label(c, d):
    W, H = PAGE
    M = MARGIN
    inner = W - 2 * M
    y = H - M

    # --- Üst bant: marka + kargo şirketi notu
    c.setFillColorRGB(0, 0, 0)
    c.setFont(_BOLD, 13)
    c.drawString(M, y - 11, "trendyol")
    c.setFont(_BOLD, 7)
    c.drawRightString(W - M, y - 11, "KARGO ETİKETİ")
    c.setFont(_REG, 6.3)
    note = ("Kargo şirketinin dikkatine, bu bir trendyol.com gönderisidir. "
            "Trendyol anlaşmasına uygun işlem yapabilirsiniz.")
    ny = y - 21
    for t in simpleSplit(note, _REG, 6.3, inner)[:2]:
        c.drawString(M, ny, t)
        ny -= 7.5
    y = ny - 1
    _hline(c, y, M, W - M)

    # --- Barkod (en büyük öğe) + takip no
    bar_h = 64
    bw = 2.2
    while True:
        bc = code128.Code128(d["tracking"], barWidth=bw, barHeight=bar_h, quiet=False)
        if bc.width <= inner or bw <= 0.7:
            break
        bw -= 0.05
    bc.drawOn(c, M + (inner - bc.width) / 2, y - 8 - bar_h)
    y = y - 8 - bar_h
    c.setFont(_BOLD, 14)
    c.drawCentredString(W / 2, y - 15, d["tracking"])
    y = y - 22
    _hline(c, y, M, W - M, 1.2)

    # --- Alıcı
    c.setFillColorRGB(*GRAY)
    c.setFont(_BOLD, 7)
    c.drawString(M, y - 11, "ALICI")
    c.setFillColorRGB(0, 0, 0)
    ty = y - 25
    c.setFont(_BOLD, 12)
    for t in _wrap_max(d["name"], _BOLD, 12, inner, MAX_NAME_LINES):
        c.drawString(M, ty, t)
        ty -= 14
    c.setFont(_REG, 9.5)
    for t in _wrap_max(d["address"], _REG, 9.5, inner, MAX_ADDR_LINES):
        c.drawString(M, ty, t)
        ty -= 11.5
    if d["region"]:
        ty -= 1
        c.setFont(_BOLD, 11.5)
        c.drawString(M, ty, _fit(d["region"], _BOLD, 11.5, inner))
        ty -= 14
    c.setFont(_BOLD, 8.5)
    c.drawString(M, ty, "Sipariş No: ")
    c.setFont(_REG, 8.5)
    c.drawString(M + pdfmetrics.stringWidth("Sipariş No: ", _BOLD, 8.5), ty,
                 d["order_no"] or "-")
    y = ty - 7
    _hline(c, y, M, W - M)

    # --- Ürünler (kalan alana sığdığı kadar)
    c.setFillColorRGB(*GRAY)
    c.setFont(_BOLD, 7)
    c.drawString(M, y - 11, "ÜRÜNLER")
    c.setFillColorRGB(0, 0, 0)
    iy = y - 23
    floor = M + 2
    items = d["items"]
    shown = 0
    for i, ln in enumerate(items, 1):
        qty = ln.get("quantity") or 1
        prefix = "%sx " % qty
        pw = pdfmetrics.stringWidth(prefix, _BOLD, 8.5)
        name_lines = _wrap_max(ln.get("productName"), _BOLD, 8.5, inner - pw, MAX_ITEM_LINES)
        need = len(name_lines) * 10 + 10 + 5
        remaining = len(items) - i
        reserve = 10 if remaining > 0 else 0
        if iy - need < floor + reserve:
            break
        c.setFont(_BOLD, 8.5)
        c.drawString(M, iy, prefix)
        for t in name_lines:
            c.drawString(M + pw, iy, t)
            iy -= 10
        code = _clean(ln.get("stockCode") or ln.get("merchantSku"))
        extra = " / ".join(x for x in (_clean(ln.get("productColor")),
                                       _clean(ln.get("productSize"))) if x and x != "-")
        meta = "Stok Kodu: %s" % (code or "-")
        if extra:
            meta += "   %s" % extra
        c.setFillColorRGB(*GRAY)
        c.setFont(_REG, 7.5)
        c.drawString(M + pw, iy, _fit(meta, _REG, 7.5, inner - pw))
        c.setFillColorRGB(0, 0, 0)
        iy -= 15
        shown += 1
    if shown < len(items):
        c.setFont(_BOLD, 8)
        c.drawString(M, floor + 1, "+ %d ürün daha (pakette)" % (len(items) - shown))


def build_label_pdf(pkg):
    """Tek paket -> tek sayfa 100x150 mm PDF."""
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
    """Birden çok paket -> her biri ayrı sayfa.

    Döner: (pdf_bytes, atlananlar) -- atlananlar [{"order_no", "reason"}].
    Hiç etiket üretilemezse ValueError.
    """
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
