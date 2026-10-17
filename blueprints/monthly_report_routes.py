"""Aylik rapor sayfasi ve API: /aylik-raporlar, /api/monthly-reports."""

import re
from datetime import datetime

from flask import Blueprint, jsonify, render_template

import database
import monthly_reports

bp = Blueprint("monthly_report_routes", __name__)

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _table_exists(conn):
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'monthly_reports'"
    ).fetchone()
    return row is not None


@bp.route("/aylik-raporlar")
def aylik_raporlar_page():
    return render_template("pages/aylik-raporlar.html", active_page="aylik-raporlar")


@bp.route("/api/monthly-reports", methods=["GET"])
def list_reports():
    with database.get_connection() as conn:
        if not _table_exists(conn):
            return jsonify({"items": []})
        rows = conn.execute(
            "SELECT period, status, generated_at FROM monthly_reports ORDER BY period DESC"
        ).fetchall()
    items = [
        {"period": r["period"], "label": monthly_reports.period_label(r["period"]),
         "status": r["status"], "generatedAt": r["generated_at"]}
        for r in rows
    ]
    return jsonify({"items": items})


@bp.route("/api/monthly-reports/<period>", methods=["GET"])
def get_report_view(period):
    if not PERIOD_RE.match(period):
        return jsonify({"error": "Gecersiz donem, YYYY-MM bekleniyor."}), 400
    with database.get_connection() as conn:
        if not _table_exists(conn):
            return jsonify({"error": "Bu ay icin rapor yok."}), 404
        view = monthly_reports.load_report_view(conn, period)
    if view is None:
        return jsonify({"error": "Bu ay icin rapor yok."}), 404
    return jsonify(view)


@bp.route("/api/monthly-reports/<period>/refresh", methods=["POST"])
def refresh_report(period):
    if not PERIOD_RE.match(period):
        return jsonify({"error": "Gecersiz donem, YYYY-MM bekleniyor."}), 400
    if period >= datetime.now().strftime("%Y-%m"):
        return jsonify({"error": "Bu ay henuz bitmedi."}), 400
    result = monthly_reports.generate_report(period, force=True)
    return jsonify(result)
