"""Full-data CSV import + SQL-dump backup/restore routes (Controller layer).

Primary backup format is a SQL dump (.sql). The legacy JSON snapshot
(.json) is still downloadable and restorable so old backups keep working.
"""
import json
import os
from datetime import datetime

from flask import Response, current_app, flash, redirect, render_template, \
    request, session, url_for

from ...db import get_db, log_action
from ..auth.controllers import admin_required
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
    stats = _db_stats(db)
    return render_template("data/index.html", db_engine=db.engine, db_label=db_label,
                           db_stats=stats)


def _db_stats(db):
    """Live row counts shown on the page so users know what a backup holds."""
    stats = {}
    for table in ("categories", "budgets", "transactions", "users", "recurrences"):
        try:
            stats[table] = db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except Exception:  # noqa: BLE001 — a missing table just shows 0
            stats[table] = 0
    stats["total"] = sum(stats.values())
    return stats


@bp.route("/data/backup")
def backup():
    """Download a SQL-dump snapshot of the whole database (all tables)."""
    try:
        body = models.export_sql_backup(get_db())
    except Exception as e:  # noqa: BLE001 — never strand the user on a 500
        current_app.logger.exception("Backup export failed")
        flash(f"Backup failed: {e}. Please try again.", "error")
        return redirect(url_for("data.index"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Response(
        body, mimetype="application/sql",
        headers={"Content-Disposition": f"attachment; filename=exptracker-backup-{stamp}.sql"},
    )


@bp.route("/data/backup.json")
def backup_json():
    """Download a legacy JSON snapshot (for old clients/backups)."""
    try:
        payload = models.export_backup(get_db())
    except Exception as e:  # noqa: BLE001 — never strand the user on a 500
        current_app.logger.exception("Backup export failed")
        flash(f"Backup failed: {e}. Please try again.", "error")
        return redirect(url_for("data.index"))
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    body = json.dumps(payload, indent=2, ensure_ascii=False)
    return Response(
        body, mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=exptracker-backup-{stamp}.json"},
    )


@bp.route("/data/restore", methods=["POST"])
@admin_required
def restore():
    """Restore the database from an uploaded backup (replaces all data).

    Accepts SQL dumps (.sql, primary) and legacy JSON snapshots (.json).
    """
    f = request.files.get("backup_file")
    filename = (f.filename or "").strip() if f else ""
    if not f or not filename:
        flash("Choose a backup (.sql or .json) file to restore.", "error")
        return redirect(url_for("data.index"))
    lowered = filename.lower()
    if lowered.endswith(".sql"):
        fmt = "sql"
    elif lowered.endswith(".json"):
        fmt = "json"
    else:
        flash(f"Backup: '{filename}' is not a .sql or .json file — please upload a backup "
              f"downloaded via “Download backup”.", "error")
        return redirect(url_for("data.index"))
    if request.form.get("confirm") != "yes":
        flash("Restore: tick the confirmation checkbox to replace all data. "
              "This confirms you understand restoring replaces everything.", "error")
        return redirect(url_for("data.index"))
    try:
        raw = f.read()
    except Exception:  # noqa: BLE001
        flash(f"Backup: could not read '{filename}'. Please try again.", "error")
        return redirect(url_for("data.index"))
    if not raw:
        flash(f"Backup: '{filename}' is empty (0 bytes). Choose a non-empty backup file.",
              "error")
        return redirect(url_for("data.index"))
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        if fmt == "json":
            flash(f"Backup: '{filename}' is not a readable text file — could not read JSON file. "
                  f"Make sure it is an unmodified .json backup.", "error")
        else:
            flash(f"Backup: '{filename}' is not readable text (UTF-8 decoding failed). "
                  f"Make sure it is an unmodified .sql backup.", "error")
        return redirect(url_for("data.index"))
    db = get_db()
    if fmt == "sql":
        counts, err = models.restore_sql_backup(db, text)
    else:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as e:
            flash(f"Backup: could not read JSON file — {e.msg} at line {e.lineno}, "
                  f"column {e.colno}. The file may be corrupted or not a backup.", "error")
            return redirect(url_for("data.index"))
        except Exception:  # noqa: BLE001
            flash("Backup: could not read JSON file. The file may be corrupted.", "error")
            return redirect(url_for("data.index"))
        counts, err = models.restore_backup(db, payload)
    if err:
        log_action(db, session.get("user"), "restore_backup_failed", None, None,
                   f"{filename}: {err}")
        flash(f"Restore failed: {err} No changes were made — your current data is intact.",
              "error")
    else:
        detail = models.summarize_counts(counts)
        log_action(db, session.get("user"), "restore_backup", None, None,
                   f"{filename}: {detail}")
        flash(
            f"Restored {sum(counts.values())} row(s) from '{filename}' — {detail}. "
            f"Previous data was replaced.",
            "success",
        )
    return redirect(url_for("data.index"))


@bp.route("/data/restore-csv", methods=["POST"])
@admin_required
def restore_csv():
    """Restore data tables from uploaded CSV files (replaces current data).

    Accepts the same three CSV formats as the importer. Users and login
    accounts are always preserved (CSV has no user format); recurring
    schedules are removed (CSV has no recurrence format) — use a .sql
    backup for a full-fidelity restore.
    """
    specs = (("categories_file", "categories", "Categories"),
             ("budgets_file", "budgets", "Budgets"),
             ("transactions_file", "transactions", "Transactions"))
    texts = {}
    for field, key, label in specs:
        f = request.files.get(field)
        if not f or not f.filename:
            continue
        if not f.filename.lower().endswith(".csv"):
            flash(f"{label}: please upload a .csv file.", "error")
            return redirect(url_for("data.index"))
        try:
            text = f.read().decode("utf-8-sig")
        except Exception:  # noqa: BLE001
            flash(f"{label}: could not read CSV file.", "error")
            return redirect(url_for("data.index"))
        if not text.strip():
            flash(f"{label}: file is empty. Choose a non-empty .csv file.", "error")
            return redirect(url_for("data.index"))
        texts[key] = text
    if not texts:
        flash("Choose at least one CSV file to restore from.", "error")
        return redirect(url_for("data.index"))
    if request.form.get("confirm") != "yes":
        flash("Restore: tick the confirmation checkbox to replace current data. "
              "This confirms you understand restoring replaces categories, budgets "
              "and transactions.", "error")
        return redirect(url_for("data.index"))
    db = get_db()
    results, err = models.restore_from_csv(
        db, texts, transaction_models.recorded_by(db, session.get("user", "")))
    if err:
        log_action(db, session.get("user"), "restore_csv_failed", None, None, err)
        flash(f"Restore failed: {err} No changes were made — your current data is intact.",
              "error")
    else:
        detail = models.summarize_csv_results(results)
        rec_msg = ""
        if results.get("recurrences_removed"):
            rec_msg = (f" {results['recurrences_removed']} recurring schedule(s) removed "
                       f"(CSV has no recurring format — use a .sql backup to keep them).")
        log_action(db, session.get("user"), "restore_csv", None, None, detail)
        flash(f"Restored from CSV — {detail}.{rec_msg} Users preserved.",
              "success" if detail != "0 rows" else "error")
    return redirect(url_for("data.index"))


@bp.route("/data/import", methods=["POST"])
@admin_required
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
        log_action(db, session.get("user"), "csv_import", None, None,
                   f"{label}: {imported} imported, {skipped} skipped")
    if not handled:
        flash("Choose at least one CSV file to import.", "error")
    return redirect(url_for("data.index"))
