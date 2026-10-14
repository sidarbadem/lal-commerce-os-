import json
import logging
import os
import secrets
import threading
import time
from datetime import datetime, timedelta

from flask import Blueprint, Response, jsonify, render_template, request

import hb_write_client as hbw
import ty_write_client as tyw

bp = Blueprint("paketlenecekler_routes", __name__)
logger = logging.getLogger(__name__)

_CACHE = {"ts": 0.0, "data": None}
_CACHE_TTL = 60
_DUE_KEYS = (
    "dueDate", "deliveryDueDate", "shipmentDueDate",
    "shippingDueDate", "maxShippingDate", "cargoDueDate",
)


def _core():
    import sync_core
    return sync_core


def _writes_enabled():
    return os.getenv("LAL_WRITES_ENABLED", "0").strip() == "1"


def _hb_iso_to_ms(value):
    if not value:
        return None
    return _core()._hb_iso_to_epoch_ms(value)


def _amount(value):
    if isinstance(value, dict):
        value = value.get("amount")
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first_due(objs, iso_to_ms):
    for obj in objs:
        for key in _DUE_KEYS:
            ms = iso_to_ms(obj.get(key))
            if ms:
                return ms
    return None


def _flag(objs, key):
    return not any(o.get(key) is False for o in objs)


def hb_unpacked(items, iso_to_ms):
    grouped = {}
    for it in items:
        if it.get("packageNumber"):
            continue
        if (it.get("status") or "").lower() != "open":
            continue
        order_number = it.get("orderNumber")
        if not order_number:
            continue
        grouped.setdefault(order_number, []).append(it)
    rows = []
    for order_number, lines in grouped.items():
        first = lines[0]
        rows.append({
            "marketplace": "hepsiburada",
            "state": "unpacked",
            "order_number": str(order_number),
            "package_id": None,
            "customer": first.get("customerName") or first.get("recipientName") or "",
            "order_date_ms": iso_to_ms(first.get("orderDate")),
            "due_ms": _first_due(lines, iso_to_ms),
            "cargo": first.get("cargoCompany") or first.get("cargoCompanyName") or "",
            "total": sum((_amount(ln.get("totalPrice")) or 0) for ln in lines),
            "can_pack": _flag(lines, "canCreatePackage"),
            "cargo_changable": _flag(lines, "isCargoChangable"),
            "lines": [
                {
                    "id": ln.get("id"),
                    "name": ln.get("name") or ln.get("productName") or "",
                    "sku": ln.get("merchantSKU") or ln.get("merchantSku") or "",
                    "qty": ln.get("quantity") or 1,
                }
                for ln in lines
            ],
        })
    return rows


def hb_packed(pkgs, iso_to_ms):
    rows = []
    for p in pkgs:
        if (p.get("status") or "").lower() != "open":
            continue
        items = p.get("items") or []
        first = items[0] if items else {}
        rows.append({
            "marketplace": "hepsiburada",
            "state": "packed",
            "order_number": str(first.get("orderNumber") or p.get("orderNumber") or ""),
            "package_id": p.get("packageNumber") or p.get("id"),
            "customer": p.get("customerName") or "",
            "order_date_ms": iso_to_ms(p.get("orderDate")),
            "due_ms": _first_due([p] + items, iso_to_ms),
            "cargo": p.get("cargoCompany") or "",
            "total": _amount(p.get("totalPrice")),
            "can_pack": True,
            "cargo_changable": True,
            "lines": [
                {
                    "id": it.get("lineItemId") or it.get("id"),
                    "name": it.get("productName") or it.get("name") or "",
                    "sku": it.get("merchantSku") or it.get("merchantSKU") or "",
                    "qty": it.get("quantity") or 1,
                }
                for it in items
            ],
        })
    return rows


def ty_created(pkgs, fix_ms):
    rows = []
    for p in pkgs:
        status = p.get("status") or p.get("shipmentPackageStatus") or ""
        if status and status.lower() != "created":
            continue
        customer = " ".join(
            x for x in (p.get("customerFirstName"), p.get("customerLastName")) if x
        )
        rows.append({
            "marketplace": "trendyol",
            "state": "created",
            "order_number": str(p.get("orderNumber") or ""),
            "package_id": p.get("id"),
            "customer": customer,
            "order_date_ms": fix_ms(p.get("orderDate")),
            "due_ms": fix_ms(p.get("agreedDeliveryDate")),
            "cargo": p.get("cargoProviderName") or "",
            "total": _amount(p.get("packageGrandTotalPrice") or p.get("packageTotalPrice")),
            "lines": [
                {
                    "name": ln.get("productName") or "",
                    "id": ln.get("lineId"),
                    "sku": ln.get("merchantSku") or ln.get("barcode") or "",
                    "qty": ln.get("quantity") or 1,
                }
                for ln in (p.get("lines") or [])
            ],
        })
    return rows


def _ty_fixer(core):
    fn = getattr(core, "normalize_trendyol_epoch_ms", None)

    def fix(value):
        if value in (None, ""):
            return None
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        if fn:
            try:
                return fn(value)
            except Exception:
                return value
        return value

    return fix


def _hb_fetch_orders(core):
    items = []
    offset = 0
    limit = 100
    for _ in range(30):
        data = core.hepsiburada_get(core.HB_ORDERS_PATH, {"offset": offset, "limit": limit})
        page = (data or {}).get("items") or []
        total = (data or {}).get("totalCount", 0)
        items.extend(page)
        offset += limit
        if offset >= total or not page:
            break
    return items


def _sort_key(r):
    due = r.get("due_ms")
    return (due is None, due or 0, r.get("order_date_ms") or 0)


def attach_images(rows, image_map=None):
    """Her satıra (ln) imageUrl ekler. Görsel kaynağı product_images tablosudur
    (Trendyol'dan senkronize edilir, SKU bazlı); Hepsiburada'daki farklı SKU
    yazımları sku_alias ile normalize edilir. Görsel bulunamazsa imageUrl None
    kalır, frontend placeholder gösterir. Hata sayfayı asla bozmaz."""
    if image_map is None:
        try:
            from database import list_product_images
            image_map = list_product_images()
        except Exception:
            logger.exception("Paketlenecekler: urun gorselleri okunamadi")
            image_map = {}
    from sku_alias import normalize_sku
    for row in rows:
        for ln in row.get("lines") or []:
            sku = ln.get("sku") or ""
            ln["imageUrl"] = image_map.get(sku) or image_map.get(normalize_sku(sku))
    return rows


def _collect(debug=False):
    core = _core()
    now = datetime.now()
    rows = []
    errors = {}
    raw = {}

    try:
        start_ms = int((now - timedelta(days=13)).timestamp() * 1000)
        end_ms = int(now.timestamp() * 1000)
        pkgs = core.fetch_all_orders(start_ms, end_ms, status="Created")
        if debug and pkgs:
            raw["trendyol_created"] = pkgs[0]
        rows += ty_created(pkgs, _ty_fixer(core))
    except Exception as exc:
        errors["trendyol"] = str(exc)[:300]

    try:
        cred_error = core._check_hb_credentials()
        if cred_error:
            raise RuntimeError(cred_error)
        items = _hb_fetch_orders(core)
        unpacked = hb_unpacked(items, _hb_iso_to_ms)
        if debug:
            open_items = [i for i in items if not i.get("packageNumber")
                          and (i.get("status") or "").lower() == "open"]
            if open_items:
                raw["hb_order_item"] = open_items[0]
        rows += unpacked
        pkgs = core.fetch_all_hb_packages(now - timedelta(days=14), now)
        packed = hb_packed(pkgs, _hb_iso_to_ms)
        if debug and pkgs:
            raw["hb_package"] = pkgs[0]
        rows += packed
    except Exception as exc:
        errors["hepsiburada"] = str(exc)[:300]

    attach_images(rows)
    rows.sort(key=_sort_key)
    out = {"rows": rows, "errors": errors, "generated_ms": int(time.time() * 1000)}
    if debug:
        out["raw_samples"] = raw
    return out


def _log(action, order_number, target_id, req, dry_run, status, text, ok, marketplace="hepsiburada"):
    try:
        from database import get_connection
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO paketlenecekler_islemleri "
                "(marketplace, action, order_number, target_id, request_json, "
                "dry_run, http_status, response_text, ok) VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    marketplace, action, order_number, target_id,
                    json.dumps({"method": req["method"], "path": req["path"], "body": req["body"]},
                               ensure_ascii=False),
                    1 if dry_run else 0, status, (text or "")[:2000],
                    None if ok is None else (1 if ok else 0),
                ),
            )
            conn.commit()
    except Exception as exc:
        logger.warning("paketlenecekler islem gunlugu yazilamadi: %s", exc)



# --- Etiket dosya adı: etiket-1.pdf, etiket-2.pdf ... (kalıcı sayaç) ----------------
_LABEL_COUNTER_FILE = "etiket_sayac.txt"
_LABEL_LOCK = threading.Lock()
_LABEL_STASH = {}  # token -> (pdf_bytes, dosya_adi, zaman); toplu etiket için kısa ömürlü


def _next_label_name():
    """Her üretilen etiket PDF'ine sıradaki adı verir: etiket-1.pdf, etiket-2.pdf ...
    Sayaç etiket_sayac.txt'te tutulur (yeniden başlatmada sıfırlanmaz)."""
    with _LABEL_LOCK:
        try:
            with open(_LABEL_COUNTER_FILE, encoding="utf-8") as fh:
                n = int((fh.read() or "0").strip() or 0)
        except (OSError, ValueError):
            n = 0
        n += 1
        try:
            tmp = _LABEL_COUNTER_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(str(n))
            os.replace(tmp, _LABEL_COUNTER_FILE)
        except OSError as exc:
            logger.warning("etiket sayaci yazilamadi: %s", exc)
    return "etiket-%d.pdf" % n


def _label_response(pdf):
    """Etiket PDF yanıtı; tarayıcı kaydederken adı etiket-N.pdf olur."""
    name = _next_label_name()
    resp = Response(pdf, mimetype="application/pdf")
    resp.headers["Content-Disposition"] = 'inline; filename="%s"' % name
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["X-Etiket-Dosya"] = name
    return resp, name


def _stash_label(pdf, name):
    now = time.time()
    for k in [k for k, v in _LABEL_STASH.items() if now - v[2] > 600]:
        _LABEL_STASH.pop(k, None)
    while len(_LABEL_STASH) >= 8:
        _LABEL_STASH.pop(min(_LABEL_STASH, key=lambda k: _LABEL_STASH[k][2]), None)
    token = secrets.token_urlsafe(16)
    _LABEL_STASH[token] = (pdf, name, now)
    return token


@bp.route("/paketlenecekler")
def paketlenecekler_page():
    return render_template("pages/paketlenecekler.html", active_page="paketlenecekler")


@bp.route("/api/paketlenecekler")
def api_paketlenecekler():
    debug = request.args.get("debug") == "1"
    force = request.args.get("refresh") == "1"
    now = time.time()
    if not debug and not force and _CACHE["data"] is not None and now - _CACHE["ts"] < _CACHE_TTL:
        return jsonify(_CACHE["data"])
    data = _collect(debug)
    if not debug:
        _CACHE["ts"] = now
        _CACHE["data"] = data
    return jsonify(data)


@bp.route("/api/paketlenecekler/hb/kargo-secenekleri")
def api_hb_cargo_options():
    core = _core()
    cred_error = core._check_hb_credentials()
    if cred_error:
        return jsonify({"error": cred_error}), 400
    try:
        path = hbw.options_path(
            core.HB_MERCHANT_ID, request.args.get("line_id"), request.args.get("package_number"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        raw = core.hepsiburada_get(path)
    except Exception as exc:
        return jsonify({"error": str(exc)[:300]}), 502
    return jsonify({"options": hbw.normalize_options(raw)})


@bp.route("/api/paketlenecekler/hb/islem", methods=["POST"])
def api_hb_islem():
    if not request.is_json:
        return jsonify({"ok": False, "error": "JSON gerekli"}), 415
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Geçersiz istek"}), 400
    action = payload.get("action")
    dry_run = payload.get("dry_run") is not False
    order_number = str(payload.get("order_number") or "")[:64]
    core = _core()
    cred_error = core._check_hb_credentials()
    if cred_error:
        return jsonify({"ok": False, "error": cred_error}), 400
    try:
        reqs = hbw.build_requests(action, core.HB_MERCHANT_ID, payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    writes_enabled = _writes_enabled()
    if dry_run:
        preview = [{"method": r["method"], "path": r["path"], "body": r["body"]} for r in reqs]
        return jsonify({"ok": True, "dry_run": True, "writes_enabled": writes_enabled,
                        "requests": preview})

    if not writes_enabled:
        return jsonify({
            "ok": False, "dry_run": False, "writes_enabled": False,
            "error": "Yazma işlemleri kapalı. Açmak için .env dosyasına LAL_WRITES_ENABLED=1 ekleyip servisi yeniden başlat.",
        }), 403

    results = []
    all_ok = True
    for r in reqs:
        status, text = hbw.send(core, r)
        ok = 200 <= status < 300
        _log(action, order_number, r["target_id"], r, False, status, text, ok)
        results.append({"path": r["path"], "status": status, "response": text[:600]})
        if not ok:
            all_ok = False
            break
    _CACHE["data"] = None
    return jsonify({"ok": all_ok, "dry_run": False, "writes_enabled": True, "results": results})


@bp.route("/api/paketlenecekler/hb/etiket")
def api_hb_label():
    import base64
    from flask import Response
    core = _core()
    cred_error = core._check_hb_credentials()
    if cred_error:
        return jsonify({"error": cred_error}), 400
    try:
        path = hbw.label_path(core.HB_MERCHANT_ID, request.args.get("package_number"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    try:
        raw = core.hepsiburada_get(path, {"format": "pdf"})
    except Exception as exc:
        return jsonify({"error": str(exc)[:300]}), 502
    parts = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(parts, list) or len(parts) != 1:
        return jsonify({"error": "Beklenmeyen etiket yanıtı (parça sayısı: %s)" % (
            len(parts) if isinstance(parts, list) else "yok")}), 502
    try:
        pdf = base64.b64decode(parts[0], validate=True)
    except Exception:
        return jsonify({"error": "Etiket çözülemedi"}), 502
    if not pdf.startswith(b"%PDF"):
        return jsonify({"error": "Etiket PDF değil"}), 502
    pdf = _brand_hb_label(pdf, request.args.get("package_number"))
    resp, _name = _label_response(pdf)
    return resp


@bp.route("/api/paketlenecekler/ty/kargo-secenekleri")
def api_ty_cargo_options():
    core = _core()
    try:
        raw = core.trendyol_get("/integration/product/lookup/cargo-providers")
    except Exception as exc:
        return jsonify({"error": str(exc)[:300]}), 502
    opts = []
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, dict) and it.get("code"):
                code = str(it["code"])
                opts.append({"short": code, "name": str(it.get("name") or code)})
    return jsonify({"options": opts})


@bp.route("/api/paketlenecekler/ty/islem", methods=["POST"])
def api_ty_islem():
    if not request.is_json:
        return jsonify({"ok": False, "error": "JSON gerekli"}), 415
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"ok": False, "error": "Geçersiz istek"}), 400
    action = payload.get("action")
    dry_run = payload.get("dry_run") is not False
    order_number = str(payload.get("order_number") or "")[:64]
    core = _core()
    try:
        reqs = tyw.build_requests(action, core.SUPPLIER_ID, payload)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    writes_enabled = _writes_enabled()
    if dry_run:
        preview = [{"method": r["method"], "path": r["path"], "body": r["body"]} for r in reqs]
        return jsonify({"ok": True, "dry_run": True, "writes_enabled": writes_enabled,
                        "requests": preview})

    if not writes_enabled:
        return jsonify({
            "ok": False, "dry_run": False, "writes_enabled": False,
            "error": "Yazma işlemleri kapalı. Açmak için .env dosyasına LAL_WRITES_ENABLED=1 ekleyip servisi yeniden başlat.",
        }), 403

    results = []
    all_ok = True
    for r in reqs:
        status, text = tyw.send(core, r)
        ok = 200 <= status < 300
        _log(action, order_number, r["target_id"], r, False, status, text, ok, marketplace="trendyol")
        results.append({"path": r["path"], "status": status, "response": text[:600]})
        if not ok:
            all_ok = False
            break
    _CACHE["data"] = None
    return jsonify({"ok": all_ok, "dry_run": False, "writes_enabled": True, "results": results})


@bp.route("/api/paketlenecekler/ty/etiket")
def api_ty_label():
    from flask import Response
    core = _core()
    pid = (request.args.get("package_id") or "").strip()
    if not pid.isdigit():
        return jsonify({"error": "Geçersiz paket no"}), 400
    now = int(time.time() * 1000)
    try:
        data = core.trendyol_get(
            "/integration/order/sellers/%s/v2/orders" % core.SUPPLIER_ID,
            {"shipmentPackageIds": pid, "startDate": now - 12 * 24 * 3600 * 1000,
             "endDate": now + 24 * 3600 * 1000, "size": 50})
    except Exception as exc:
        return jsonify({"error": str(exc)[:300]}), 502
    pkgs = (data or {}).get("content") or []
    pkg = next((p for p in pkgs if str(p.get("id") or p.get("shipmentPackageId")) == pid), None)
    if not pkg:
        return jsonify({"error": "Paket bulunamadı (son 12 gün)"}), 404
    try:
        _enrich_ty_images(pkg)
        import ty_label as tyl
        pdf = tyl.build_label_pdf(pkg)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422
    except Exception as exc:
        logger.warning("trendyol etiketi uretilemedi: %s", exc)
        return jsonify({"error": "Etiket üretilemedi: %s" % str(exc)[:200]}), 500
    resp, _name = _label_response(pdf)
    return resp


# --- Toplu etiket yazdırma (12.10.2026) -----------------------------------
# Seçilen Trendyol + Hepsiburada paketlerinin etiketlerini TEK PDF'te toplar
# (her etiket ayrı sayfa, seçim sırasıyla). Salt okunur: yalnızca etiket
# GET'leri yapılır, yazma bayrağı (LAL_WRITES_ENABLED) gerekmez.
BULK_LABEL_MAX = 50


def _hb_label_pdf_bytes(core, package_number):
    """HB paket etiketi (tek parça PDF) bayt olarak. Hata -> RuntimeError(mesaj)."""
    import base64
    try:
        path = hbw.label_path(core.HB_MERCHANT_ID, package_number)
    except ValueError as exc:
        raise RuntimeError(str(exc))
    try:
        raw = core.hepsiburada_get(path, {"format": "pdf"})
    except Exception as exc:
        raise RuntimeError(str(exc)[:200])
    parts = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(parts, list) or len(parts) != 1:
        raise RuntimeError("Beklenmeyen etiket yanıtı")
    try:
        pdf = base64.b64decode(parts[0], validate=True)
    except Exception:
        raise RuntimeError("Etiket çözülemedi")
    if not pdf.startswith(b"%PDF"):
        raise RuntimeError("Etiket PDF değil")
    return _brand_hb_label(pdf, package_number)


def _ty_label_pdf_bytes(core, package_id):
    """Trendyol paket etiketi (100x150 mm, tek sayfa) bayt olarak."""
    if not str(package_id).isdigit():
        raise RuntimeError("Geçersiz paket no")
    now = int(time.time() * 1000)
    try:
        data = core.trendyol_get(
            "/integration/order/sellers/%s/v2/orders" % core.SUPPLIER_ID,
            {"shipmentPackageIds": package_id, "startDate": now - 12 * 24 * 3600 * 1000,
             "endDate": now + 24 * 3600 * 1000, "size": 50})
    except Exception as exc:
        raise RuntimeError(str(exc)[:200])
    pkgs = (data or {}).get("content") or []
    pkg = next((p for p in pkgs
                if str(p.get("id") or p.get("shipmentPackageId")) == str(package_id)), None)
    if not pkg:
        raise RuntimeError("Paket bulunamadı (son 12 gün)")
    _enrich_ty_images(pkg)
    import ty_label as tyl
    try:
        return tyl.build_label_pdf(pkg)
    except ValueError as exc:
        raise RuntimeError(str(exc))


@bp.route("/api/paketlenecekler/etiketler", methods=["POST"])
def api_bulk_labels():
    import io
    import json
    from flask import Response
    if not request.is_json:
        return jsonify({"error": "JSON gerekli"}), 415
    payload = request.get_json(silent=True)
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        return jsonify({"error": "Etiket için paket seçilmedi"}), 400
    if len(items) > BULK_LABEL_MAX:
        return jsonify({"error": "En fazla %d etiket birlikte yazdırılabilir" % BULK_LABEL_MAX}), 400
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        return jsonify({"error": "pypdf kurulu değil"}), 500

    core = _core()
    hb_cred_error = None
    writer = PdfWriter()
    skipped = []
    seen = set()
    count = 0
    for it in items:
        if not isinstance(it, dict):
            continue
        mp = str(it.get("marketplace") or "")
        pid = str(it.get("package_id") or "").strip()
        label = str(it.get("order_number") or "")[:64] or pid
        if (mp, pid) in seen:
            continue
        seen.add((mp, pid))
        try:
            if mp == "trendyol":
                pdf = _ty_label_pdf_bytes(core, pid)
            elif mp == "hepsiburada":
                if hb_cred_error is None:
                    hb_cred_error = core._check_hb_credentials() or ""
                if hb_cred_error:
                    raise RuntimeError(hb_cred_error)
                pdf = _hb_label_pdf_bytes(core, pid)
            else:
                raise RuntimeError("Bilinmeyen pazaryeri")
            for page in PdfReader(io.BytesIO(pdf)).pages:
                writer.add_page(page)
            count += 1
        except RuntimeError as exc:
            skipped.append({"marketplace": mp, "package_id": pid,
                            "order_number": label, "reason": str(exc)[:160]})
        except Exception as exc:
            logger.warning("toplu etiket atlandi (%s %s): %s", mp, pid, exc)
            skipped.append({"marketplace": mp, "package_id": pid,
                            "order_number": label, "reason": "Etiket üretilemedi"})
    if not count:
        return jsonify({"error": "Hiçbir etiket alınamadı", "skipped": skipped}), 422
    out = io.BytesIO()
    writer.write(out)
    resp, name = _label_response(out.getvalue())
    # Blob URL dosya adını kaybettirir; PDF kısa süre saklanır, ad sonda olan adresten açılır
    token = _stash_label(out.getvalue(), name)
    resp.headers["X-Etiket-Url"] = "/api/paketlenecekler/etiketler/dosya/%s/%s" % (token, name)
    # json.dumps varsayılanı ASCII kaçışlıdır -> HTTP başlığında güvenli
    resp.headers["X-Etiket-Atlanan"] = json.dumps(skipped)
    return resp


@bp.route("/api/paketlenecekler/etiketler/dosya/<token>/<name>")
def api_labels_file(token, name):
    from flask import Response
    item = _LABEL_STASH.get(token)
    if not item or time.time() - item[2] > 600:
        return jsonify({"error": "Etiket süresi doldu, yeniden oluşturun"}), 404
    resp = Response(item[0], mimetype="application/pdf")
    resp.headers["Content-Disposition"] = 'inline; filename="%s"' % item[1]
    resp.headers["Cache-Control"] = "no-store"
    return resp


# --- Etiket v3: kargo firması, ürün görseli, Hepsiburada tek etiket -----------------
def _label_images(skus):
    """{sku: imageUrl|None}. Sayfadaki ürün görselleriyle aynı kaynak ve kurallar
    (product_images tablosu + sku_alias); hata etiketi bozmaz."""
    row = {"lines": [{"sku": s or ""} for s in skus]}
    attach_images([row])
    return {ln["sku"]: ln.get("imageUrl") for ln in row["lines"]}


def _enrich_ty_images(pkg):
    """Trendyol paket satırlarına imageUrl ekler (kural: sayfadaki satırla aynı sku)."""
    try:
        lines = pkg.get("lines") or []
        skus = [ln.get("merchantSku") or ln.get("barcode") or "" for ln in lines]
        found = _label_images(skus)
        for ln, sku in zip(lines, skus):
            ln["imageUrl"] = found.get(sku)
    except Exception as exc:
        logger.warning("Trendyol etiket gorselleri eklenemedi: %s", exc)


_HB_ITEMS = {"ts": 0.0, "items": None}


def _hb_items_cached(core, ttl=30):
    """HB sipariş kalemleri (toplu etikette her etiket için yeniden çekmemek için 30 sn)."""
    now = time.time()
    if _HB_ITEMS["items"] is None or now - _HB_ITEMS["ts"] > ttl:
        _HB_ITEMS["items"] = _hb_fetch_orders(core)
        _HB_ITEMS["ts"] = now
    return _HB_ITEMS["items"]


def _hb_order_detail_items(core, order_no):
    """HB sipariş detayı (salt okunur GET): kalemler, her kalemde shippingAddress."""
    base = (getattr(core, "HB_ORDERS_PATH", "") or "").rstrip("/")
    if not base or not order_no:
        return []
    data = core.hepsiburada_get("%s/ordernumber/%s" % (base, order_no), {})
    if isinstance(data, dict):
        items = data.get("items") or data.get("lineItems") or ([data] if data.get("shippingAddress") else [])
    elif isinstance(data, list):
        items = data
    else:
        items = []
    return [it for it in items if isinstance(it, dict)]


def _hb_label_order(core, package_number):
    """Paket numarasından HB etiketi için sipariş verisi; bulunamazsa None."""
    pn = str(package_number)

    def mine_of(src):
        return [it for it in (src or []) if str(it.get("packageNumber") or "") == pn]

    mine = mine_of(_hb_items_cached(core))
    if not mine:  # paket az önce oluşturulduysa önbellek eski olabilir
        _HB_ITEMS["items"] = None
        mine = mine_of(_hb_items_cached(core))
    pkg_obj = None
    if not mine:
        now = datetime.now()
        pkgs = core.fetch_all_hb_packages(now - timedelta(days=14), now)
        pkg_obj = next((p for p in (pkgs or [])
                        if str(p.get("packageNumber") or p.get("id") or "") == pn), None)
        mine = (pkg_obj or {}).get("items") or []
    if not mine:
        return None
    first = mine[0]
    addr = first.get("shippingAddress") or {}
    model = first.get("cargoCompanyModel") or {}
    pkg_obj = pkg_obj or {}
    if not addr.get("city") and not addr.get("address"):
        # Paketlenmiş kalemlerde teslimat adresi gelmiyorsa sipariş detayından al
        try:
            for det in _hb_order_detail_items(core, first.get("orderNumber")):
                if (det.get("shippingAddress") or {}).get("city") or (det.get("shippingAddress") or {}).get("address"):
                    addr = det["shippingAddress"]
                    model = model or det.get("cargoCompanyModel") or {}
                    break
        except Exception as exc:
            logger.warning("HB siparis detayi alinamadi (%s): %s", first.get("orderNumber"), exc)
    # HB: city=il, town=ilçe, district=mahalle. Gerekirse .env: LAL_HB_ILCE_FIELD=district
    ilce_field = os.getenv("LAL_HB_ILCE_FIELD", "town")
    ilce = addr.get(ilce_field) or addr.get("town") or addr.get("district") or ""
    skus = [(it.get("merchantSKU") or it.get("merchantSku") or it.get("sku") or "") for it in mine]
    images = _label_images(skus)
    return {
        "order_no": str(first.get("orderNumber") or ""),
        "cargo": first.get("cargoCompany") or model.get("name") or pkg_obj.get("cargoCompany") or "",
        "name": addr.get("name") or first.get("customerName") or pkg_obj.get("customerName") or "",
        "address": addr.get("address") or "",
        "ilce": ilce,
        "il": addr.get("city") or "",
        "phone": addr.get("phoneNumber") or addr.get("alternatePhoneNumber") or "",
        "items": [{"name": it.get("name") or it.get("productName") or "",
                   "qty": it.get("quantity") or 1, "sku": sku, "imageUrl": images.get(sku)}
                  for it, sku in zip(mine, skus)],
    }


def _brand_hb_label(pdf, package_number=None):
    """HB etiketini SoftHydra tasarımına çevirir (HB'nin barkod bloğu aynen kalır).
    Sipariş verisi alınamazsa yalnız logolu karta, o da olmazsa orijinal PDF'e döner:
    etiket hiçbir koşulda bozulmaz."""
    try:
        import hb_label
    except Exception as exc:
        logger.warning("hb_label yuklenemedi: %s", exc)
        return pdf
    if package_number:
        try:
            order = _hb_label_order(_core(), package_number)
            if order:
                return hb_label.build_hb_label(pdf, order)
            logger.warning("HB etiket verisi bulunamadi (paket %s); kart yedegi", package_number)
        except Exception as exc:
            logger.warning("HB tam etiket uretilemedi (paket %s): %s", package_number, exc)
    try:
        return hb_label.stamp_hb_label(pdf)
    except Exception as exc:
        logger.warning("HB etiket markalama atlandi: %s", exc)
        return pdf
