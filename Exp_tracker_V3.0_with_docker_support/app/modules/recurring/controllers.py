"""Recurring transaction routes (Controller layer)."""
from datetime import date, timedelta

from flask import flash, g, redirect, render_template, request, session, url_for

from ...db import get_db, log_action
from ..auth import models as auth_models
from ..auth.controllers import admin_required
from ..categories import models as category_models
from ..transactions import models as transaction_models
from . import bp, models

FREQUENCIES = models.FREQUENCIES


@bp.route("/recurring", methods=["GET", "POST"])
def index():
    db = get_db()
    if request.method == "POST":
        if not g.get("is_admin", False):
            flash("That action requires an admin account.", "error")
            return redirect(url_for("recurring.index"))
        return _save(db)
    return render_template(
        "recurring/list.html",
        items=models.all(db),
        categories=category_models.all(db),
        owners=auth_models.all_users(db),
        frequencies=FREQUENCIES,
        today=date.today().isoformat(),
        due=models.due_count(db, date.today()),
        username=session.get("user", ""),
    )


def _save(db):
    ttype = request.form.get("type", "expense")
    code = (request.form.get("currency") or transaction_models.base_currency()).strip().upper()
    # validate() checks the raw amount (base-currency interpretation) plus
    # type/category/frequency/date; convert_to_base() computes the stored
    # cents for the chosen currency. The validate amount is discarded.
    _, cat, frequency, next_run, err = models.validate(
        db, request.form.get("amount", "") or "1", ttype,
        request.form.get("category_id", ""),
        request.form.get("frequency", "monthly"),
        request.form.get("next_run_date", "") or date.today().isoformat())
    if err:
        flash(err, "error")
        return redirect(url_for("recurring.index"))
    base, orig, cerr = transaction_models.convert_to_base(
        request.form.get("amount", ""), code)
    if cerr:
        flash(cerr, "error")
        return redirect(url_for("recurring.index"))
    amount = base
    owner_id, oerr = transaction_models.resolve_owner(
        db, request.form.get("owner", ""),
        transaction_models.recorded_by(db, session.get("user", "")))
    if oerr:
        flash(oerr, "error")
        return redirect(url_for("recurring.index"))
    note = (request.form.get("note", "") or "").strip()[:200]
    models.create(db, amount, ttype, cat["id"], note, frequency, next_run,
                  owner_id, currency=code, orig_amount=orig)
    log_action(db, session.get("user"), "create_recurrence", "recurrences", None,
               f"{frequency} {ttype}")
    flash(f"Recurring {ttype} scheduled ({frequency}, next run {next_run}).", "success")
    return redirect(url_for("recurring.index"))


@bp.route("/recurring/<int:rec_id>/pause", methods=["POST"])
@admin_required
def pause(rec_id):
    models.set_active(get_db(), rec_id, False)
    flash("Recurrence paused.", "success")
    return redirect(url_for("recurring.index"))


@bp.route("/recurring/<int:rec_id>/resume", methods=["POST"])
@admin_required
def resume(rec_id):
    db = get_db()
    row = models.get(db, rec_id)
    if row and row["next_run_date"] <= date.today().isoformat():
        # resuming an overdue schedule: push next run a day out so it doesn't
        # instantly generate a burst of old transactions
        models.set_active(db, rec_id, True)
        db.execute("UPDATE recurrences SET next_run_date=? WHERE id=?",
                   ((date.today() + timedelta(days=1)).isoformat(), rec_id))
        db.commit()
    else:
        models.set_active(db, rec_id, True)
    flash("Recurrence resumed.", "success")
    return redirect(url_for("recurring.index"))


@bp.route("/recurring/<int:rec_id>/delete", methods=["POST"])
@admin_required
def delete(rec_id):
    db = get_db()
    row = models.get(db, rec_id)
    models.delete(db, rec_id)
    log_action(db, session.get("user"), "delete_recurrence", "recurrences", rec_id,
               row["note"] if row else None)
    flash("Recurrence deleted. Generated transactions are kept.", "success")
    return redirect(url_for("recurring.index"))


@bp.route("/recurring/run", methods=["POST"])
@admin_required
def run_now():
    created = models.run_due(get_db(), date.today())
    if created:
        flash(f"Generated {created} transaction(s) from due recurrences.", "success")
    else:
        flash("Nothing is due right now.", "info")
    return redirect(url_for("recurring.index"))
