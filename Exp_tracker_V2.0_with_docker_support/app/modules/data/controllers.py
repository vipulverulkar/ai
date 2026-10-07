"""Full-data CSV import + JSON backup/restore routes (Controller layer)."""
import json
import os
from datetime import datetime

from flask import Response, current_app, flash, redirect, render_template, request, session, url_for

from ...db import get_db
from ..transactions import models as transaction_models
from . import bp, models

# Processed in dependency order: categories -> budgets -> transactions.
IMPORTS = [
    ("categories_file", "Categories", models.import_categories),
    ("budgets_file", "Budgets", models.import_budgets),
    ("transactions_file", "Transactions", models.import_transactions),
]


@bp.route("/data")
def index():
    db = get_db()
    if db.engine == "pg":
        db_label = "PostgreSQL"
    else:
        db_label = "SQLite · " + os.path.basename(
            current_app.config.get("EXPENSE_DB", "expenses.db"))
    return render_template("data/index.html", db_engine=db.engine, db_label=db_label)


@bp.route("/data/backup")
def backup():
    """Download a JSON snapshot of the whole database (all tables)."""
    payload = models.export_backup(get_db())
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    return Response(
        body, mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=exptracker-backup-{stamp}.json"},
    )


@bp.route("/data/restore", methods=["POST"])
def restore():
    """Restore the database from an uploaded JSON backup (replaces all data)."""
    f = request.files.get("backup_file")
    if not f or not f.filename:
        flash("Choose a backup (.json) file to restore.", "error")
        return redirect(url_for("data.index"))
    if not f.filename.lower().endswith(".json"):
        flash("Backup: please upload a .json file.", "error")
        return redirect(url_for("data.index"))
    if request.form.get("confirm") != "yes":
        flash("Restore: tick the confirmation checkbox to replace all data.", "error")
        return redirect(url_for("data.index"))
    try:
        payload = json.loads(f.read().decode("utf-8-sig"))
    except Exception:  # noqa: BLE001
        flash("Backup: could not read JSON file.", "error")
        return redirect(url_for("data.index"))
    counts, err = models.restore_backup(get_db(), payload)
    if err:
        flash(f"Restore failed: {err}", "error")
    else:
        total = sum(counts.values())
        flash(
            f"Restored {total} row(s) — "
            f"{counts['categories']} categories, {counts['budgets']} budgets, "
            f"{counts['transactions']} transactions, {counts['users']} users.",
            "success",
        )
    return redirect(url_for("data.index"))


@bp.route("/data/import", methods=["POST"])
def import_data():
    db = get_db()
    handled = False
    for field, label, func in IMPORTS:
        f = request.files.get(field)
        if not f or not f.filename:
            continue
        handled = True
        if not f.filename.lower().endswith(".csv"):
            flash(f"{label}: please upload a .csv file.", "error")
            continue
        try:
            text = f.read().decode("utf-8-sig")
        except Exception:  # noqa: BLE001
            flash(f"{label}: could not read CSV file.", "error")
            continue
        if label == "Transactions":
            imported, skipped = models.import_transactions(
                db, text,
                transaction_models.recorded_by(db, session.get("user", "")))
        else:
            imported, skipped = func(db, text)
        msg = f"{label}: imported {imported} row(s)"
        if skipped:
            msg += f", {skipped} skipped"
        flash(msg + ".", "success" if imported else "error")
    if not handled:
        flash("Choose at least one CSV file to import.", "error")
    return redirect(url_for("data.index"))
