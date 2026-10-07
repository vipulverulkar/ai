"""Transaction routes (Controller layer)."""
import csv
import io
from datetime import date, datetime

from flask import Response, flash, redirect, render_template, request, session, url_for

from ...db import get_db
from ..auth import models as auth_models
from ..categories import models as category_models
from . import bp, models


def _filter_args():
    """Parse filter/sort params from the query string."""
    f_type = request.args.get("type", "all")
    f_category = request.args.get("category", "all")
    f_owner = request.args.get("owner", "all")
    f_month = request.args.get("month", "")
    f_search = request.args.get("q", "").strip()
    sort = request.args.get("sort", "date")
    order = request.args.get("order", "desc")
    sort, order, where, args, order_sql = models.filter_query(
        f_type, f_category, f_owner, f_month, f_search, sort, order)
    return f_type, f_category, f_owner, f_month, f_search, sort, order, where, args, order_sql


@bp.route("/transactions")
def index():
    db = get_db()
    categories = category_models.all(db)
    owners = auth_models.all_users(db)
    f_type, f_category, f_owner, f_month, f_search, sort, order, where, args, order_sql = _filter_args()

    try:
        per_page = int(request.args.get("per_page", 10))
    except (ValueError, TypeError):
        per_page = 10
    if per_page not in models.PER_PAGE_CHOICES:
        per_page = 10

    total = models.count_filtered(db, where, args)
    filt_income, filt_expense = models.sums_filtered(db, where, args)

    total_pages = max(1, -(-total // per_page))
    try:
        page = int(request.args.get("page", 1))
    except (ValueError, TypeError):
        page = 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    txns = models.list_filtered(db, where, args, order_sql, per_page, offset)

    start = offset + 1 if total else 0
    end = min(offset + per_page, total)
    pages = []
    for p in range(1, total_pages + 1):
        if p == 1 or p == total_pages or abs(p - page) <= 2:
            pages.append(p)
        elif pages[-1] is not None:
            pages.append(None)

    return render_template(
        "transactions/list.html",
        transactions=txns, categories=categories, owners=owners,
        f_type=f_type, f_category=f_category, f_owner=f_owner,
        f_month=f_month, f_search=f_search,
        sort=sort, order=order,
        page=page, per_page=per_page, total=total, total_pages=total_pages,
        start=start, end=end, pages=pages,
        filt_income=filt_income, filt_expense=filt_expense,
        filt_net=filt_income - filt_expense,
    )


@bp.route("/transactions/export")
def export():
    db = get_db()
    _, _, _, _, _, _, _, where, args, order_sql = _filter_args()
    rows = models.export_rows(db, where, args, order_sql)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "date", "type", "category", "amount", "note", "owner"])
    for r in rows:
        w.writerow([r["id"], r["date"], r["type"], r["category"], f"{r['amount']:.2f}",
                    r["note"] or "", r["owner"] or ""])
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=expenses-{stamp}.csv"})


@bp.route("/transactions/import", methods=["POST"])
def import_csv():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".csv"):
        flash("Please upload a .csv file.", "error")
        return redirect(url_for("transactions.index"))
    try:
        text = f.read().decode("utf-8-sig")
    except Exception:  # noqa: BLE001
        flash("Could not read CSV file.", "error")
        return redirect(url_for("transactions.index"))
    db = get_db()
    inserted, skipped = models.import_csv(
        db, text, models.recorded_by(db, session.get("user", "")))
    if inserted:
        flash(f"Imported {inserted} transaction(s){f' ({skipped} skipped)' if skipped else ''}.", "success")
    else:
        flash(f"No rows imported ({skipped} skipped). Check CSV format: date,type,category,amount,note[,owner].", "error")
    return redirect(url_for("transactions.index"))


@bp.route("/add", methods=["POST"])
def add():
    db = get_db()
    ttype = request.form.get("type", "expense")
    amount, cat, date_str, note, err = models.validate(
        db, request.form.get("amount", ""), ttype,
        request.form.get("category_id", ""),
        request.form.get("date", "") or date.today().isoformat(),
        request.form.get("note", ""))
    if err:
        flash(err, "error")
        return redirect(url_for("dashboard.index"))
    me = models.recorded_by(db, session.get("user", ""))
    owner_id, oerr = models.resolve_owner(db, request.form.get("owner", ""), me)
    if oerr:
        flash(oerr, "error")
        return redirect(url_for("dashboard.index"))
    models.create(db, amount, ttype, cat["id"], date_str, note, owner_id)
    flash("Transaction added.", "success")
    return redirect(url_for("dashboard.index"))


@bp.route("/edit/<int:tx_id>", methods=["GET", "POST"])
def edit(tx_id):
    db = get_db()
    tx = models.get(db, tx_id)
    if not tx:
        flash("Transaction not found.", "error")
        return redirect(url_for("transactions.index"))
    if request.method == "POST":
        ttype = request.form.get("type", "expense")
        amount, cat, date_str, note, err = models.validate(
            db, request.form.get("amount", ""), ttype,
            request.form.get("category_id", ""), request.form.get("date", ""),
            request.form.get("note", ""))
        if err:
            flash(err, "error")
            return redirect(url_for("transactions.edit", tx_id=tx_id))
        me = models.recorded_by(db, session.get("user", ""))
        owner_id, oerr = models.resolve_owner(db, request.form.get("owner", ""), me)
        if oerr:
            flash(oerr, "error")
            return redirect(url_for("transactions.edit", tx_id=tx_id))
        models.update(db, tx_id, amount, ttype, cat["id"], date_str, note, owner_id)
        flash("Transaction updated.", "success")
        return redirect(url_for("transactions.index"))
    return render_template("transactions/edit.html", tx=tx,
                           categories=category_models.all(db),
                           owners=auth_models.all_users(db))


@bp.route("/duplicate/<int:tx_id>", methods=["POST"])
def duplicate(tx_id):
    if models.duplicate(get_db(), tx_id) is None:
        flash("Transaction not found.", "error")
        return redirect(url_for("transactions.index"))
    flash("Transaction duplicated for today.", "success")
    return redirect(url_for("transactions.index"))


@bp.route("/delete/<int:tx_id>", methods=["POST"])
def delete(tx_id):
    models.delete(get_db(), tx_id)
    flash("Transaction deleted.", "success")
    return redirect(url_for("transactions.index"))
