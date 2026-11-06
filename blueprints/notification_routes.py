"""Bildirim merkezi API'si. UI bu uc noktalari periyodik sorgular."""

import os

from flask import Blueprint, jsonify, request, send_from_directory

import notifications
import web_push

bp = Blueprint("notification_routes", __name__)


@bp.route("/api/notifications")
def notifications_list():
    try:
        after_id = int(request.args.get("after_id", 0))
        limit = max(1, min(int(request.args.get("limit", 30)), 100))
    except ValueError:
        return jsonify({"error": "gecersiz parametre"}), 400
    try:
        return jsonify(notifications.list_notifications(after_id=after_id, limit=limit))
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@bp.route("/api/notifications/read", methods=["POST"])
def notifications_read():
    payload = request.get_json(silent=True) or {}
    try:
        if payload.get("all"):
            notifications.mark_read(None)
        else:
            ids = [int(i) for i in payload.get("ids", [])]
            notifications.mark_read(ids)
    except (TypeError, ValueError):
        return jsonify({"error": "gecersiz id"}), 400
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500
    return jsonify({"ok": True})


# ---------------- Web Push (telefon bildirimi) ----------------

@bp.route("/sw.js")
def service_worker():
    """Service worker kok kapsamdan sunulmali (scope '/')."""
    static_js = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "js")
    resp = send_from_directory(static_js, "sw.js", mimetype="application/javascript", max_age=0)
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.route("/api/push/config")
def push_config():
    cfg = web_push.config()
    return jsonify({"enabled": cfg["enabled"], "publicKey": cfg["public_key"]})


@bp.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    payload = request.get_json(silent=True) or {}
    try:
        web_push.subscribe(payload.get("subscription"), request.headers.get("User-Agent"))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"ok": True})


@bp.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    endpoint = (request.get_json(silent=True) or {}).get("endpoint")
    if not endpoint:
        return jsonify({"error": "endpoint gerekli"}), 400
    web_push.unsubscribe(endpoint)
    return jsonify({"ok": True})


@bp.route("/api/push/test", methods=["POST"])
def push_test():
    stats = web_push.send_to_all({
        "title": "LAL bildirimleri açık",
        "body": "Yeni sipariş, iptal ve yorumlar bu cihaza gelecek.",
        "url": "/panel", "tag": "lal-test", "kind": "test",
    })
    return jsonify(stats)
