"""Manual order entry for channels without API access (softhydra.com, n11, Amazon)."""
from flask import Blueprint, jsonify, request

import manual_orders as mo
from database import get_connection

bp = Blueprint("manual_order_routes", __name__)


def _error(exc):
    status = 404 if isinstance(exc, LookupError) else 400
    return jsonify({"error": str(exc)}), status


@bp.route("/api/manual-orders/meta")
def manual_orders_meta():
    return jsonify({
        "channels": [{"key": k, "label": v} for k, v in mo.MANUAL_CHANNELS.items()],
        "statuses": list(mo.MANUAL_STATUSES),
    })


@bp.route("/api/manual-orders/skus")
def manual_orders_skus():
    q = (request.args.get("q") or "").strip()
    like = f"%{q}%"
    with get_connection() as conn:
        rows = conn.execute(
            """SELECT sku, product_name, cost_incl_vat, sale_price_incl_vat
               FROM product_costs WHERE sku LIKE ? OR product_name LIKE ?
               ORDER BY sku LIMIT 50""",
            (like, like),
        ).fetchall()
    return jsonify({"skus": [
        {
            "sku": r["sku"],
            "productName": r["product_name"],
            "costInclVat": r["cost_incl_vat"],
            "salePriceInclVat": r["sale_price_incl_vat"],
        }
        for r in rows
    ]})


@bp.route("/api/manual-orders", methods=["POST"])
def manual_orders_create():
    try:
        order_id = mo.create_manual_order(request.get_json(silent=True))
        return jsonify(mo.get_manual_order(order_id)), 201
    except (ValueError, LookupError) as exc:
        return _error(exc)


@bp.route("/api/manual-orders/<int:order_id>", methods=["GET"])
def manual_orders_get(order_id):
    try:
        return jsonify(mo.get_manual_order(order_id))
    except (ValueError, LookupError) as exc:
        return _error(exc)


@bp.route("/api/manual-orders/<int:order_id>", methods=["PUT"])
def manual_orders_update(order_id):
    try:
        mo.update_manual_order(order_id, request.get_json(silent=True))
        return jsonify(mo.get_manual_order(order_id))
    except (ValueError, LookupError) as exc:
        return _error(exc)


@bp.route("/api/manual-orders/<int:order_id>", methods=["DELETE"])
def manual_orders_delete(order_id):
    try:
        mo.delete_manual_order(order_id)
        return jsonify({"ok": True})
    except (ValueError, LookupError) as exc:
        return _error(exc)
