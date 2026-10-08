"""Category routes (Controller layer)."""
from flask import flash, g, redirect, render_template, request, url_for

from ...db import INTEGRITY_ERRORS, get_db
from ...helpers import page_window, paginate
from ..auth.controllers import admin_required
from . import bp, models


@bp.route("/categories", methods=["GET", "POST"])
def index():
    db = get_db()
    if request.method == "POST":
        if not g.get("is_admin", False):
            flash("That action requires an admin account.", "error")
            return redirect(url_for("categories.index"))
        name = request.form.get("name", "").strip()[:50]
        ctype = request.form.get("type", "expense")
        if not name:
            flash("Category name is required.", "error")
            return redirect(url_for("categories.index"))
        if ctype not in ("income", "expense"):
            flash("Invalid category type.", "error")
            return redirect(url_for("categories.index"))
        try:
            models.create(db, name, ctype)
            flash(f"Category '{name}' added.", "success")
        except INTEGRITY_ERRORS:
            flash(f"Category '{name}' already exists.", "error")
        return redirect(url_for("categories.index"))
    total = models.count(db)
    page, per_page, total_pages, offset = paginate(
        total, request.args.get("page"), request.args.get("per_page"))
    return render_template("categories/list.html",
                           categories=models.page(db, per_page, offset),
                           usage=models.usage_counts(db),
                           page=page, per_page=per_page, total=total,
                           total_pages=total_pages,
                           start=offset + 1 if total else 0,
                           end=min(offset + per_page, total),
                           pages=page_window(page, total_pages))


@bp.route("/categories/edit/<int:cat_id>", methods=["GET", "POST"])
@admin_required
def edit(cat_id):
    db = get_db()
    cat = models.get(db, cat_id)
    if not cat:
        flash("Category not found.", "error")
        return redirect(url_for("categories.index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:50]
        if not name:
            flash("Category name is required.", "error")
            return redirect(url_for("categories.edit", cat_id=cat_id))
        try:
            models.rename(db, cat_id, name)
            flash("Category renamed.", "success")
        except INTEGRITY_ERRORS:
            flash(f"Category '{name}' already exists.", "error")
            return redirect(url_for("categories.edit", cat_id=cat_id))
        return redirect(url_for("categories.index"))
    return render_template("categories/edit.html", cat=cat)


@bp.route("/categories/delete/<int:cat_id>", methods=["POST"])
@admin_required
def delete(cat_id):
    db = get_db()
    count = models.transaction_count(db, cat_id)
    if count > 0:
        flash(f"Cannot delete: {count} transaction(s) use this category.", "error")
        return redirect(url_for("categories.index"))
    models.delete(db, cat_id)
    flash("Category deleted.", "success")
    return redirect(url_for("categories.index"))


@bp.route("/categories/savings/<int:cat_id>", methods=["POST"])
@admin_required
def toggle_savings(cat_id):
    """Flag/unflag an expense category as a savings bucket.

    Savings buckets are excluded from spending totals and shown as Saved
    instead; they cannot carry budgets (any existing budget is removed).
    """
    from ..budgets import models as budget_models
    db = get_db()
    cat = models.get(db, cat_id)
    if not cat:
        flash("Category not found.", "error")
        return redirect(url_for("categories.index"))
    if cat["type"] != "expense":
        flash("Only expense categories can be savings buckets.", "error")
        return redirect(url_for("categories.index"))
    if cat["is_savings"]:
        models.set_savings(db, cat_id, False)
        flash(f"'{cat['name']}' is now a regular spending category.", "success")
    else:
        models.set_savings(db, cat_id, True)
        budget_models.clear(db, cat_id)
        flash(f"'{cat['name']}' is now a savings bucket — excluded from spending, "
              f"budgets removed.", "success")
    return redirect(url_for("categories.index"))
