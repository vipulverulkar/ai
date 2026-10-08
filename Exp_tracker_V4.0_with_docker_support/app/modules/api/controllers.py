"""API routes (Controller layer) — served under both /api and /api/v1."""
from flask import jsonify, request

from ...db import get_db
from . import bp, bp_v1, models


def _summary_json():
    data = models.summary(get_db(), request.args.get("month", ""),
                          request.args.get("year", ""))
    return jsonify(data)


def _transactions_json():
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
    except ValueError:
        limit = 50
    f_type = request.args.get("type", "all")
    return jsonify(models.latest(get_db(), limit, f_type))


# Legacy (unversioned) endpoints — kept for backward compatibility.
@bp.route("/summary")
def summary():
    return _summary_json()


@bp.route("/transactions")
def transactions():
    return _transactions_json()


# Versioned endpoints — preferred for programmatic use.
@bp_v1.route("/summary")
def v1_summary():
    return _summary_json()


@bp_v1.route("/transactions")
def v1_transactions():
    return _transactions_json()
