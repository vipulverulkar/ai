"""Transaction routes (Controller layer)."""
import os
import calendar
import csv
import io
from datetime import date, datetime
from werkzeug.utils import secure_filename

from flask import Response, flash, g, redirect, render_template, request, session, url_for, current_app

from ...config import RECEIPT_ALLOWED_EXTS as ALLOWED_RECEIPT_EXTS
from ...config import RECEIPT_MAX_BYTES as MAX_RECEIPT_BYTES
from ...config import TRANSACTIONS_PER_PAGE_DEFAULT as _TX_PER_PAGE_FALLBACK
from ...db import get_db, log_action
from ..auth import models as auth_models
from ..auth.controllers import admin_required
from ..categories import models as category_models
from . import bp, models


def _month_options(selected="", n=12):
    """Dropdown options for the month filter: last n months + selection.

    Returns a list of (value, label) tuples, oldest first. If `selected`
    is outside the recent window (deep link to an older month), it is
    appended so the dropdown still shows it as active.
    """
    today = date.today()
    opts = []
    y, m = today.year, today.month
    for _ in range(n):
        opts.append((f"{y}-{m:02d}", f"{calendar.month_name[m]} {y}"))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    opts.reverse()
    if selected and selected not in dict(opts):
        try:
            from ...helpers import parse_month_strict
            yy, mm = parse_month_strict(selected)
            opts.insert(0, (selected, f"{calendar.month_name[mm]} {yy}"))
        except (ValueError, TypeError):
            # Invalid values are redirected away by index(); labelling the
            # raw value avoids ever showing a mismatched month name.
            opts.insert(0, (selected, selected))
    return opts


def _receipt_exts():
    """Allowed receipt extensions (runtime config, env default)."""
    try:
        exts = current_app.config.get("RECEIPT_ALLOWED_EXTS", ALLOWED_RECEIPT_EXTS)
        return tuple(exts) or ALLOWED_RECEIPT_EXTS
    except RuntimeError:
        return ALLOWED_RECEIPT_EXTS


def _receipt_max_bytes():
    """Max receipt size in bytes (runtime config, env default)."""
    try:
        return int(current_app.config.get("RECEIPT_MAX_BYTES", MAX_RECEIPT_BYTES)
                   or MAX_RECEIPT_BYTES)
    except (RuntimeError, ValueError, TypeError):
        return MAX_RECEIPT_BYTES


def _receipt_mb_label():
    from ...helpers import format_bytes
    return format_bytes(_receipt_max_bytes())


def _save_receipt(receipt_file):
    """Validate and store an uploaded receipt. Returns rel_path or (None, err)."""
    import uuid
    exts = _receipt_exts()
    filename = secure_filename(receipt_file.filename or "")
    if not filename or "." not in filename:
        return None, "Receipt must be an image or PDF file."
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext not in exts:
        return None, f"Receipt must be one of: {', '.join(e.upper() for e in exts)}."
    # Enforce a per-file size cap (app has no global MAX_CONTENT_LENGTH).
    receipt_file.seek(0, os.SEEK_END)
    size = receipt_file.tell()
    receipt_file.seek(0)
    if size > _receipt_max_bytes():
        return None, f"Receipt file is too large (max {_receipt_mb_label()})."
    if size == 0:
        return None, "Receipt file is empty."
    safe = f"{uuid.uuid4().hex[:12]}_{filename}"
    rel_path = os.path.join("static", "receipts", safe)
    abs_path = os.path.join(current_app.root_path, rel_path)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    receipt_file.save(abs_path)
    return rel_path, None


def _delete_receipt_file(rel_path):
    """Best-effort removal of a stored receipt (purge/replace cleanup)."""
    if not rel_path:
        return
    try:
        # Only ever delete inside our own receipts dir (no path traversal).
        base = os.path.realpath(os.path.join(current_app.root_path, "static", "receipts"))
        target = os.path.realpath(os.path.join(current_app.root_path, rel_path))
        if os.path.commonpath([base, target]) != base:
            return
        if os.path.isfile(target):
            os.remove(target)
    except Exception:  # noqa: BLE001 — cleanup must never break the request
        pass


def _filter_args(db):
    """Parse filter/sort params from the query string."""
    f_type = request.args.get("type", "all")
    f_category = request.args.get("category", "all")
    f_owner = request.args.get("owner", "all")
    f_month = request.args.get("month", "")
    f_search = request.args.get("q", "").strip()
    sort = request.args.get("sort", "date")
    order = request.args.get("order", "desc")
    sort, order, where, args, order_sql = models.filter_query(
        db, f_type, f_category, f_owner, f_month, f_search, sort, order)
    return f_type, f_category, f_owner, f_month, f_search, sort, order, where, args, order_sql


@bp.route("/transactions")
def index():
    # Canonical clean URL: drop default/empty filter params (and any leaked
    # csrf_token) so the address bar shows /transactions instead of a long
    # ?type=all&category=all&... query string. Deep links with real filters
    # are preserved untouched.
    from ...helpers import canonical_clean_args, is_valid_month
    raw_month = request.args.get("month", "")
    if raw_month and not is_valid_month(raw_month):
        flash(f"Invalid month '{raw_month}' — showing all months.", "error")
        args = {k: v for k, v in request.args.items() if k != "month"}
        cleaned = canonical_clean_args(args, {
            "type": "all", "category": "all", "owner": "all", "month": "",
            "q": "", "sort": "date", "order": "desc",
            "per_page": "10", "page": "1",
        })
        return redirect(url_for("transactions.index", **(cleaned or {})))
    cleaned = canonical_clean_args(request.args, {
        "type": "all", "category": "all", "owner": "all", "month": "",
        "q": "", "sort": "date", "order": "desc",
        "per_page": "10", "page": "1",
    })
    if cleaned is not None:
        return redirect(url_for("transactions.index", **cleaned))
    db = get_db()
    categories = category_models.all(db)
    owners = auth_models.all_users(db)
    f_type, f_category, f_owner, f_month, f_search, sort, order, where, args, order_sql = _filter_args(db)

    try:
        default_pp = int(current_app.config.get(
            "TRANSACTIONS_PER_PAGE_DEFAULT", _TX_PER_PAGE_FALLBACK))
    except (ValueError, TypeError):
        default_pp = _TX_PER_PAGE_FALLBACK
    try:
        per_page = int(request.args.get("per_page", default_pp))
    except (ValueError, TypeError):
        per_page = default_pp
    if per_page not in models.PER_PAGE_CHOICES:
        per_page = default_pp

    total = models.count_filtered(db, where, args)
    filt_income, filt_expense, filt_saved = models.sums_filtered(db, where, args)

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
        month_options=_month_options(selected=f_month),
        sort=sort, order=order,
        page=page, per_page=per_page, total=total, total_pages=total_pages,
        start=start, end=end, pages=pages,
        filt_income=filt_income, filt_expense=filt_expense, filt_saved=filt_saved,
        filt_net=filt_income - filt_expense,
    )


@bp.route("/transactions/export")
def export():
    db = get_db()
    _, _, _, _, _, _, _, where, args, order_sql = _filter_args(db)
    rows = models.export_rows(db, where, args, order_sql)
    from ...helpers import safe_sheet_value
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "date", "type", "category", "amount", "note", "owner",
                "currency", "orig_amount"])
    for r in rows:
        orig = ""
        if r["currency"] and r["currency"] != models.base_currency() and r["orig_amount"]:
            orig = f"{models.from_cents(r['orig_amount']):.2f}"
        w.writerow([r["id"], r["date"], r["type"], safe_sheet_value(r["category"]),
                    f"{models.from_cents(r['amount']):.2f}",
                    safe_sheet_value(r["note"] or ""), safe_sheet_value(r["owner"] or ""),
                    r["currency"] or "", orig])
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=expenses-{stamp}.csv"})


@bp.route("/transactions/import", methods=["POST"])
@admin_required
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
    inserted, skipped, truncated = models.import_csv(
        db, text, models.recorded_by(db, session.get("user", "")))
    trunc_note = (f" File holds more than {models.IMPORT_ROW_LIMIT} rows — "
                  f"only the first {models.IMPORT_ROW_LIMIT} were processed."
                  if truncated else "")
    if inserted:
        flash(f"Imported {inserted} transaction(s){f' ({skipped} skipped)' if skipped else ''}.{trunc_note}", "success")
    else:
        flash(f"No rows imported ({skipped} skipped). Check CSV format: required columns date,type,category,amount with optional note,owner,currency.{trunc_note}", "error")
    return redirect(url_for("transactions.index"))


@bp.route("/transactions/bulk", methods=["POST"])
@admin_required
def bulk():
    """Bulk actions over selected rows: soft-delete or re-categorize."""
    db = get_db()
    raw = request.form.get("ids", "")
    try:
        ids = [int(x) for x in raw.split(",") if x.strip().isdigit()]
    except ValueError:
        ids = []
    action = request.form.get("action", "")
    if not ids:
        flash("Select at least one transaction.", "error")
        return redirect(url_for("transactions.index"))
    if action == "delete":
        n = models.bulk_soft_delete(db, ids)
        log_action(db, session.get("user"), "bulk_delete", "transactions",
                   None, f"{n} row(s)")
        flash(f"Deleted {n} transaction(s).", "success" if n else "error")
    elif action == "category":
        cat_raw = request.form.get("bulk_category_id", "")
        if not cat_raw.isdigit():
            flash("Choose a category for the bulk change.", "error")
            return redirect(url_for("transactions.index"))
        updated, skipped = models.bulk_set_category(db, ids, int(cat_raw))
        log_action(db, session.get("user"), "bulk_recategorize", "transactions",
                   int(cat_raw), f"{updated} updated, {skipped} skipped")
        msg = f"Moved {updated} transaction(s)."
        if skipped:
            msg += f" {skipped} skipped (type mismatch)."
        flash(msg, "success" if updated else "error")
    else:
        flash("Unknown bulk action.", "error")
    return redirect(url_for("transactions.index"))


@bp.route("/add", methods=["POST"])
@admin_required
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

    # Multi-currency: convert the entered amount to base-currency cents.
    code = (request.form.get("currency") or models.base_currency()).strip().upper()
    base, orig, cerr = models.convert_to_base(request.form.get("amount", ""), code)
    if cerr:
        flash(cerr, "error")
        return redirect(url_for("dashboard.index"))
    # `amount` from validate() treated the input as base currency; use the
    # converted value instead so both paths agree.
    amount = base

    # Optional split lines (each becomes its own linked transaction row).
    lines, serr = models.parse_splits(db, request.form, ttype, amount, code)
    if serr:
        flash(serr, "error")
        return redirect(url_for("dashboard.index"))

    receipt_file = request.files.get("receipt")
    receipt_path = None
    if receipt_file and receipt_file.filename != "":
        receipt_path, rerr = _save_receipt(receipt_file)
        if rerr:
            flash(rerr, "error")
            return redirect(url_for("dashboard.index"))

    if lines:
        group = models.new_split_group()
        remainder = amount - sum(a for _, a in lines)
        all_lines = [(cat["id"], remainder)] + lines
        if orig is not None:
            # Split the original-currency amount proportionally so each
            # line keeps an auditable orig value that sums to the total.
            from decimal import Decimal, ROUND_HALF_UP
            rate = models.rate_to_base(code)
            rate_d = Decimal(str(rate))
            orig_lines = [max(1, int((Decimal(a) / rate_d)
                                     .to_integral_value(rounding=ROUND_HALF_UP)))
                          for _, a in all_lines]
            drift = orig - sum(orig_lines)
            # Fold rounding drift into the largest line so every line keeps
            # a positive orig value and the total still reconciles.
            biggest = max(range(len(orig_lines)),
                          key=lambda i: all_lines[i][1])
            orig_lines[biggest] += drift
            if orig_lines[biggest] <= 0:
                # Micro-amounts that can't be represented per-line in this
                # currency — refuse rather than store zero/negative values.
                flash("Split amounts are too small to represent in "
                      f"{code}. Use fewer lines or a larger amount.", "error")
                return redirect(url_for("dashboard.index"))
        else:
            orig_lines = [None] * len(all_lines)
        for (cat_id, line_amount), line_orig in zip(all_lines, orig_lines):
            models.create(db, line_amount, ttype, cat_id, date_str, note,
                          owner_id, currency=code, orig_amount=line_orig,
                          split_group=group, receipt_path=receipt_path)
        flash(f"Transaction added, split across {len(all_lines)} categories.", "success")
    else:
        models.create(db, amount, ttype, cat["id"], date_str, note, owner_id,
                      currency=code, orig_amount=orig, receipt_path=receipt_path)
        flash("Transaction added.", "success")
    return redirect(url_for("dashboard.index"))


@bp.route("/edit/<int:tx_id>", methods=["GET", "POST"])
@admin_required
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
        code = (request.form.get("currency") or (tx["currency"] or models.base_currency())).strip().upper()
        base, orig, cerr = models.convert_to_base(request.form.get("amount", ""), code)
        if cerr:
            flash(cerr, "error")
            return redirect(url_for("transactions.edit", tx_id=tx_id))

        receipt_file = request.files.get("receipt")
        receipt_path = tx["receipt_path"]
        if receipt_file and receipt_file.filename != "":
            saved, rerr = _save_receipt(receipt_file)
            if rerr:
                flash(rerr, "error")
                return redirect(url_for("transactions.edit", tx_id=tx_id))
            old_path = receipt_path
            receipt_path = saved
            # Replace succeeded — remove the orphaned previous file.
            if old_path and old_path != saved:
                _delete_receipt_file(old_path)

        # A split line must keep its group's type: flipping one line's type
        # would leave the group mixing income and expense.
        if tx["split_group"]:
            siblings = models.by_group(db, tx["split_group"])
            other_types = {r["type"] for r in siblings if r["id"] != tx_id}
            if other_types and ttype not in other_types:
                _delete_receipt_file(receipt_path if receipt_path != tx["receipt_path"] else None)
                flash("A split line must keep its group's type — edit the whole split instead.", "error")
                return redirect(url_for("transactions.edit", tx_id=tx_id))

        models.update(db, tx_id, base, ttype, cat["id"], date_str, note,
                      owner_id, currency=code, orig_amount=orig, receipt_path=receipt_path)
        flash("Transaction updated.", "success")
        return redirect(url_for("transactions.index"))
    return render_template("transactions/edit.html", tx=tx,
                           categories=category_models.all(db),
                           owners=auth_models.all_users(db))


@bp.route("/duplicate/<int:tx_id>", methods=["POST"])
@admin_required
def duplicate(tx_id):
    db = get_db()
    row = db.execute("SELECT deleted_at FROM transactions WHERE id=?", (tx_id,)).fetchone()
    if row is not None and row["deleted_at"] is not None:
        flash("That transaction is in trash — restore it first.", "error")
        return redirect(url_for("transactions.trash"))
    if models.duplicate(db, tx_id) is None:
        flash("Transaction not found.", "error")
        return redirect(url_for("transactions.index"))
    flash("Transaction duplicated for today.", "success")
    return redirect(url_for("transactions.index"))


@bp.route("/delete/<int:tx_id>", methods=["POST"])
@admin_required
def delete(tx_id):
    db = get_db()
    log_action(db, session.get("user"), "soft_delete_transaction", "transactions", tx_id)
    models.delete(db, tx_id)
    flash("Transaction moved to trash.", "success")
    return redirect(url_for("transactions.index"))


# ---------- trash (soft-deleted rows) ----------

@bp.route("/trash")
def trash():
    from ...helpers import canonical_clean_args, page_window, paginate
    cleaned = canonical_clean_args(request.args, {"page": "1", "per_page": "25"})
    if cleaned is not None:
        return redirect(url_for("transactions.trash", **cleaned))
    db = get_db()
    total = models.count_deleted(db)
    page, per_page, total_pages, offset = paginate(
        total, request.args.get("page"), request.args.get("per_page"))
    rows = models.deleted_page(db, per_page, offset)
    return render_template("transactions/trash.html", rows=rows,
                           page=page, per_page=per_page, total=total,
                           total_pages=total_pages,
                           start=offset + 1 if total else 0,
                           end=min(offset + per_page, total),
                           pages=page_window(page, total_pages))


@bp.route("/trash/<int:tx_id>/restore", methods=["POST"])
@admin_required
def trash_restore(tx_id):
    result = models.restore(get_db(), tx_id)
    if result == "no_category":
        flash("Cannot restore — its category was deleted. Purge it or recreate the category first.", "error")
    elif result:
        flash("Transaction restored.", "success")
    else:
        flash("Transaction not found in trash.", "error")
    return redirect(url_for("transactions.trash"))


@bp.route("/trash/<int:tx_id>/purge", methods=["POST"])
@admin_required
def trash_purge(tx_id):
    db = get_db()
    removed = models.purge(db, tx_id)
    if removed:
        _delete_receipt_file(removed if isinstance(removed, str) else None)
        log_action(db, session.get("user"), "purge_transaction", "transactions", tx_id)
        flash("Transaction permanently deleted.", "success")
    else:
        flash("Transaction not found in trash.", "error")
    return redirect(url_for("transactions.trash"))


# ---------- split groups ----------

@bp.route("/transactions/split/<group>")
def split_view(group):
    db = get_db()
    rows = models.by_group(db, group)
    if not rows:
        flash("Split not found (it may have been deleted).", "error")
        return redirect(url_for("transactions.index"))
    total = sum(r["amount"] for r in rows)
    types = {r["type"] for r in rows}
    mixed = len(types) > 1
    return render_template("transactions/split.html", rows=rows, group=group,
                           total=total, mixed_types=mixed)


@bp.route("/transactions/split/<group>/delete", methods=["POST"])
@admin_required
def split_delete(group):
    db = get_db()
    n = models.delete_group(db, group)
    if n:
        log_action(db, session.get("user"), "soft_delete_split", "transactions",
                   None, f"group {group}, {n} row(s)")
        flash(f"Moved {n} split line(s) to trash.", "success")
    else:
        flash("Split not found.", "error")
    return redirect(url_for("transactions.index"))
