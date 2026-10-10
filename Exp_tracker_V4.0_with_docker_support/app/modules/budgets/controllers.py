"""Budget routes (Controller layer)."""
from datetime import date

from flask import current_app, flash, g, redirect, render_template, request, url_for

from ...db import get_db
from ...helpers import format_inr, from_cents, parse_month, to_cents
from ..auth.controllers import admin_required
from ..categories import models as category_models
from . import bp, models


@bp.route("/budgets", methods=["GET", "POST"])
def index():
    db = get_db()
    if request.method == "POST":
        if not g.get("is_admin", False):
            flash("That action requires an admin account.", "error")
            return redirect(url_for("budgets.index"))
        return _save(db)
    from ...helpers import is_valid_month
    y, m = date.today().year, date.today().month
    month_str = request.args.get("month", f"{y}-{m:02d}")
    if not is_valid_month(month_str):
        flash(f"Invalid month '{month_str}' — showing the current month.", "error")
        return redirect(url_for("budgets.index"))
    y, m = parse_month(month_str)
    month_str = f"{y}-{m:02d}"
    status = models.status(db, y, m)
    return render_template(
        "budgets/list.html",
        expense_cats=[c for c in category_models.by_type(db, "expense")
                      if not c["is_savings"]],
        limits=models.limits_map(db),
        status=status, month=month_str,
        total_limit=sum(b["limit"] for b in status),
        total_spent=sum(b["spent"] for b in status),
    )


def _save(db):
    category_id = request.form.get("category_id", "")
    limit_raw = request.form.get("monthly_limit", "").strip()
    if not category_id.isdigit():
        flash("Select a valid category.", "error")
        return redirect(url_for("budgets.index"))
    cat = category_models.get(db, int(category_id))
    if not cat or cat["type"] != "expense":
        flash("Budgets apply to expense categories.", "error")
        return redirect(url_for("budgets.index"))
    if cat["is_savings"]:
        flash(f"'{cat['name']}' is a savings bucket — budgets apply to spending only.", "error")
        return redirect(url_for("budgets.index"))
    if not limit_raw:  # clear budget
        models.clear(db, cat["id"])
        flash(f"Budget for '{cat['name']}' removed.", "success")
        return redirect(url_for("budgets.index"))
    try:
        limit = to_cents(limit_raw)
        if limit <= 0:
            raise ValueError
    except ValueError:
        flash("Limit must be a positive number.", "error")
        return redirect(url_for("budgets.index"))
    models.set_limit(db, cat["id"], limit)
    flash(f"Budget for '{cat['name']}' set to "
          f"{current_app.config['CURRENCY']}{format_inr(from_cents(limit))}/month.", "success")
    return redirect(url_for("budgets.index"))


@bp.route("/budgets/delete/<int:category_id>", methods=["POST"])
@admin_required
def delete(category_id):
    models.clear(get_db(), category_id)
    flash("Budget removed.", "success")
    return redirect(url_for("budgets.index"))
