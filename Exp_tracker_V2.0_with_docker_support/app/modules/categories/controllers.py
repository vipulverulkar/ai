"""Category routes (Controller layer)."""
from flask import flash, redirect, render_template, request, url_for

from ...db import INTEGRITY_ERRORS, get_db
from . import bp, models


@bp.route("/categories", methods=["GET", "POST"])
def index():
    db = get_db()
    if request.method == "POST":
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
    return render_template("categories/list.html", categories=models.all(db),
                           usage=models.usage_counts(db))


@bp.route("/categories/edit/<int:cat_id>", methods=["GET", "POST"])
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
def delete(cat_id):
    db = get_db()
    count = models.transaction_count(db, cat_id)
    if count > 0:
        flash(f"Cannot delete: {count} transaction(s) use this category.", "error")
        return redirect(url_for("categories.index"))
    models.delete(db, cat_id)
    flash("Category deleted.", "success")
    return redirect(url_for("categories.index"))
