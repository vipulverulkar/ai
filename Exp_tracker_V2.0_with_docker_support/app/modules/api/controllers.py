"""API routes (Controller layer)."""
from flask import jsonify, request

from ...db import get_db
from . import bp, models


@bp.route("/summary")
def summary():
    data = models.summary(get_db(), request.args.get("month", ""),
                          request.args.get("year", ""))
    return jsonify(data)


@bp.route("/transactions")
def transactions():
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
    except ValueError:
        limit = 50
    f_type = request.args.get("type", "all")
    return jsonify(models.latest(get_db(), limit, f_type))
