"""Bank statement import (Controller layer) — upload once, map columns, preview, import.

Flow:
    1. GET  /bank-import/         pick a file (or a saved template + file)
    2. POST /bank-import/map      file is staged in the session, headers are
                                  auto-mapped, user adjusts dropdowns
    3. POST /bank-import/preview  staged file + mapping -> validated preview
    4. POST /bank-import/import   staged file + mapping -> rows created

Staging the upload in the session means the user never re-uploads the
same file between steps. Only admins may run the write steps.
"""
import csv
import io
import json

from flask import current_app, flash, g, redirect, render_template, request, session, url_for

from ...config import BANK_IMPORT_MAX_BYTES as MAX_BANK_CSV_BYTES
from ...config import BANK_IMPORT_PREVIEW_ROWS as PREVIEW_ROWS
from ...config import BANK_IMPORT_ROW_LIMIT as BANK_ROW_LIMIT
from ...db import get_db
from ..auth.controllers import admin_required
from ..categories import models as category_models
from .. import import_templates as templates_mod
from ..transactions import models as tx_models
from . import bp

STAGE_KEY = "bank_csv_text"
STAGE_NAME_KEY = "bank_csv_name"


def _max_bytes():
    """Max staged bank CSV size in bytes (runtime config, env default)."""
    try:
        return int(current_app.config.get("BANK_IMPORT_MAX_BYTES", MAX_BANK_CSV_BYTES)
                   or MAX_BANK_CSV_BYTES)
    except (RuntimeError, ValueError, TypeError):
        return MAX_BANK_CSV_BYTES


def _mb_label():
    from ...helpers import format_bytes
    return format_bytes(_max_bytes())


def _row_limit():
    """Max bank CSV rows per import (runtime config, env default)."""
    try:
        return int(current_app.config.get("BANK_IMPORT_ROW_LIMIT", BANK_ROW_LIMIT)
                   or BANK_ROW_LIMIT)
    except (RuntimeError, ValueError, TypeError):
        return BANK_ROW_LIMIT


def _preview_rows():
    """Preview sample size (runtime config, env default)."""
    try:
        return int(current_app.config.get("BANK_IMPORT_PREVIEW_ROWS", PREVIEW_ROWS)
                   or PREVIEW_ROWS)
    except (RuntimeError, ValueError, TypeError):
        return PREVIEW_ROWS


def _can_stage():
    """True when staged uploads fit in the session (server-side sessions).

    With SESSION_TYPE=cookie the whole CSV would have to ride in the
    browser cookie (~4 KB limit), so staging is skipped and each step
    re-uses an explicitly re-attached file instead.
    """
    return (current_app.config.get("SESSION_TYPE") or "cookie") != "cookie"


def _read_upload(file_storage):
    """Read + decode an uploaded CSV, enforcing the size cap."""
    if not file_storage or not (file_storage.filename or "").lower().endswith(".csv"):
        return None, "Please upload a valid .csv file."
    raw = file_storage.read(_max_bytes() + 1)
    if len(raw) > _max_bytes():
        return None, f"CSV file is too large (max {_mb_label()}). Split it and try again."
    if not raw.strip():
        return None, "CSV file is empty."
    try:
        return templates_mod.detect_csv_encoding(raw), None
    except Exception:  # noqa: BLE001
        return None, "Could not read CSV file. Make sure it is a valid .csv file."


def _parse_rows(text):
    """Return (headers, sample_rows, total_data_rows)."""
    reader = csv.DictReader(io.StringIO(text))
    headers = [h for h in (reader.fieldnames or []) if h]
    if not headers:
        return None, None, "No header row found. The first row must name the columns."
    rows = [r for r in reader
            if r and any((v or "").strip() for v in r.values() if isinstance(v, str))]
    if not rows:
        return None, None, "No data rows found. The file has only a header."
    return headers, rows, None


def _mapping_from_form(form):
    """Collect the mapping dropdowns from a posted form."""
    mapping = {}
    for target in ("date", "amount", "debit", "credit", "type", "category", "note"):
        val = (form.get(f"map_{target}") or "").strip()
        if val:
            mapping[target] = val
    return mapping


def _staged_text():
    return session.get(STAGE_KEY)


@bp.route("/")
def index():
    db = get_db()
    if not g.get("is_admin", False):
        flash("That action requires an admin account.", "error")
        return redirect(url_for("dashboard.index"))
    templates = db.execute("SELECT * FROM import_templates ORDER BY name").fetchall()
    staged_name = session.get(STAGE_NAME_KEY)
    staged = bool(session.get(STAGE_KEY))
    return render_template("bank_import/index.html", templates=templates,
                           staged_name=staged_name, staged=staged,
                           max_label=_mb_label())


@bp.route("/map", methods=["POST"])
@admin_required
def map_columns():
    """Stage the upload and show the mapping step with auto-guessed columns."""
    db = get_db()
    f = request.files.get("file")
    template_id = request.form.get("template_id") or None
    if f and f.filename:
        text, err = _read_upload(f)
        if err:
            flash(err, "error")
            return redirect(url_for("bank_import.index"))
        headers, rows, err = _parse_rows(text)
        if err:
            flash(err, "error")
            return redirect(url_for("bank_import.index"))
        if len(rows) > _row_limit():
            flash(f"Too many rows ({len(rows)}, max {_row_limit()}). "
                  "Split the file and try again.", "error")
            return redirect(url_for("bank_import.index"))
        if _can_stage():
            session[STAGE_KEY] = text
            session[STAGE_NAME_KEY] = f.filename
        else:
            # Cookie sessions can't hold the CSV: each step re-attaches it.
            session.pop(STAGE_KEY, None)
            session.pop(STAGE_NAME_KEY, None)
    else:
        # No new file — reuse the staged upload (e.g. switching templates).
        text = _staged_text()
        if not text:
            flash("Choose a CSV file to import.", "error")
            return redirect(url_for("bank_import.index"))
        headers, rows, err = _parse_rows(text)
        if err:
            flash(err, "error")
            return redirect(url_for("bank_import.index"))
    # Starting mapping: posted mapping wins (back from preview), then a
    # saved template, else auto-guess from headers.
    mapping = _mapping_from_form(request.form)
    if not mapping and template_id:
        tpl = templates_mod.get_template_by_id(db, template_id)
        if tpl:
            try:
                mapping = json.loads(tpl["mapping"])
            except (ValueError, TypeError):
                mapping = {}
    if not mapping:
        mapping = {k: v for k, v in templates_mod.guess_mapping(headers).items() if v}
    samples = templates_mod.sample_values(rows[:20], headers)
    categories = category_models.all(db)
    templates = db.execute("SELECT * FROM import_templates ORDER BY name").fetchall()
    return render_template("bank_import/map.html", headers=headers,
                           sample_rows=rows[:5], samples=samples,
                           mapping=mapping, categories=categories,
                           templates=templates, template_id=template_id or "",
                           default_category=(request.form.get("default_category")
                                             or "").strip(),
                           filename=session.get(STAGE_NAME_KEY, ""),
                           cookie_mode=not _can_stage())


def _resolve_preview_inputs(form):
    """Return (text, mapping, default_cat_id, error). Prefers staged upload."""
    text = _staged_text()
    f = request.files.get("file")
    if f and f.filename:
        text, err = _read_upload(f)
        if err:
            return None, None, None, err
        if _can_stage():
            session[STAGE_KEY] = text
            session[STAGE_NAME_KEY] = f.filename
        # Cookie sessions can't hold the CSV (see _can_stage): `text` is
        # used in-memory for this step and the next step re-attaches it.
    if not text:
        return None, None, None, "Upload a CSV file first."
    headers, rows, err = _parse_rows(text)
    if err:
        return None, None, None, err
    mapping = _mapping_from_form(form)
    if not templates_mod.validate_mapping(mapping):
        return None, None, None, (
            "Map the Date and Description columns plus either an Amount "
            "column or a Debit + Credit column pair.")
    unknown = [v for v in mapping.values() if v not in headers]
    if unknown:
        return None, None, None, (
            f"Mapped column(s) not in this file: {', '.join(unknown)}.")
    default_cat = (form.get("default_category") or "").strip()
    return rows, mapping, (default_cat or None), None


def _preview_row(db, row, mapping, default_cat_id, cats):
    """Map + validate one row. Returns dict with ok flag and parsed fields."""
    mapped = templates_mod.apply_mapping(row, mapping)
    if mapping.get("debit") or mapping.get("credit"):
        amount_raw, forced_type = templates_mod.combine_debit_credit(row, mapping)
        type_raw = mapped.get("type") or forced_type
    else:
        amount_raw, type_raw = mapped.get("amount"), mapped.get("type")
    date_str = templates_mod.infer_date_format(mapped.get("date"))
    ttype, amount_str = templates_mod.detect_type_from_amount(amount_raw, type_raw)
    if not date_str or not amount_str:
        reason = []
        if not date_str:
            reason.append(f"cannot parse date '{mapped.get('date')}'")
        if not amount_str:
            reason.append(f"cannot parse amount '{amount_raw}'")
        return {"ok": False, "error": "; ".join(reason), "raw": dict(row)}
    desc = (mapped.get("category") or "").strip()
    note = (mapped.get("note") or "").strip()
    if default_cat_id:
        cat = cats.get(str(default_cat_id))
        if not cat:
            return {"ok": False, "error": "chosen default category no longer exists",
                    "raw": dict(row)}
        if cat["type"] != ttype:
            return {"ok": False, "error": f"is {ttype} but default category "
                                          f"'{cat['name']}' is for {cat['type']}",
                    "raw": dict(row)}
        label, final_note = cat["name"], (f"{desc} — {note}" if desc and note
                                          else desc or note)[:200]
    else:
        if not desc:
            return {"ok": False, "error": "empty description", "raw": dict(row)}
        key = desc.lower()
        cat = cats.get(key)
        if cat is None:
            label = desc[:50]  # would be auto-created on import
        elif cat["type"] != ttype:
            return {"ok": False, "error": f"category '{cat['name']}' is for "
                                          f"{cat['type']}, not {ttype}",
                    "raw": dict(row)}
        else:
            label = cat["name"]
        final_note = note
    from datetime import date as _date
    if date_str > _date.today().isoformat():
        return {"ok": False, "error": f"date {date_str} is in the future",
                "raw": dict(row)}
    return {"ok": True, "date": date_str, "type": ttype,
            "category": label, "amount": amount_str,
            "note": final_note, "raw": dict(row)}


@bp.route("/preview", methods=["POST"])
@admin_required
def preview():
    """Validate the staged file with the chosen mapping; no rows are written."""
    db = get_db()
    rows, mapping, default_cat, err = _resolve_preview_inputs(request.form)
    if err:
        flash(err, "error")
        return redirect(url_for("bank_import.index"))
    cats = {r["name"].lower(): r for r in db.execute("SELECT * FROM categories").fetchall()}
    cats_by_id = {str(r["id"]): r for r in cats.values()}
    if default_cat and default_cat not in cats_by_id:
        flash("Chosen default category no longer exists.", "error")
        return redirect(url_for("bank_import.index"))
    preview_rows, errors = [], []
    for i, row in enumerate(rows[:_preview_rows()]):
        try:
            parsed = _preview_row(db, row, mapping, default_cat, {**cats, **cats_by_id})
        except Exception as e:  # noqa: BLE001 — one bad row must not 500 the preview
            parsed = {"ok": False, "error": str(e) or "unparseable row",
                      "raw": dict(row)}
        preview_rows.append(parsed)
        if not parsed["ok"]:
            errors.append(f"Row {i + 1}: {parsed['error']}")
    ok_count = sum(1 for r in preview_rows if r["ok"])
    session["bank_mapping"] = mapping
    session["bank_default_category"] = default_cat
    categories = category_models.all(db)
    return render_template("bank_import/preview.html",
                           preview_rows=preview_rows, errors=errors,
                           ok_count=ok_count, total_rows=len(rows),
                           mapping=mapping, default_category=default_cat,
                           categories=categories,
                           filename=session.get(STAGE_NAME_KEY, ""),
                           staged=bool(_staged_text()))


@bp.route("/import", methods=["POST"])
@admin_required
def import_bank():
    """Import the staged file with the confirmed mapping."""
    db = get_db()
    text = _staged_text()
    f = request.files.get("file")
    if f and f.filename:
        # Backward compatibility: a re-uploaded file still works.
        text, err = _read_upload(f)
        if err:
            flash(err, "error")
            return redirect(url_for("bank_import.index"))
        if _can_stage():
            session[STAGE_KEY] = text
            session[STAGE_NAME_KEY] = f.filename
    if not text:
        flash("Upload a CSV file first.", "error")
        return redirect(url_for("bank_import.index"))
    headers, rows, err = _parse_rows(text)
    if err:
        flash(err, "error")
        return redirect(url_for("bank_import.index"))
    mapping = _mapping_from_form(request.form) or session.get("bank_mapping") or {}
    default_cat = ((request.form.get("default_category") or "").strip()
                   or session.get("bank_default_category"))
    if not templates_mod.validate_mapping(mapping):
        flash("Invalid mapping configuration.", "error")
        return redirect(url_for("bank_import.index"))
    if any(v not in headers for v in mapping.values()):
        flash("Saved mapping does not match this file's columns. Re-map and try again.",
              "error")
        return redirect(url_for("bank_import.index"))
    cats = {r["name"].lower(): r for r in db.execute("SELECT * FROM categories").fetchall()}
    cats_by_id = {str(r["id"]): r for r in cats.values()}
    if default_cat and default_cat not in cats_by_id:
        flash("Chosen default category no longer exists.", "error")
        return redirect(url_for("bank_import.index"))
    from ...db import DB_ERRORS
    inserted = skipped = 0
    skip_reasons = []
    me = tx_models.recorded_by(db, session.get("user", ""))
    seen_this_run = set()  # fingerprints created by this upload (repeats
    # within one statement, e.g. two identical subscriptions, are legit)
    for i, row in enumerate(rows, start=1):
        if i > _row_limit():
            skipped += len(rows) - (i - 1)
            skip_reasons.append(f"stopped at row limit ({_row_limit()})")
            break
        try:
            fp = _process_bank_row(db, row, mapping, cats, me, default_cat,
                                   seen_this_run)
            if fp is False:
                skipped += 1
            else:
                inserted += 1
        except Exception as e:  # noqa: BLE001 — per-row failure must not abort the run
            try:
                db.rollback()
            except DB_ERRORS:
                pass
            skipped += 1
            if len(skip_reasons) < 10:
                skip_reasons.append(f"Row {i}: {e}")
    session.pop(STAGE_KEY, None)
    session.pop(STAGE_NAME_KEY, None)
    session.pop("bank_mapping", None)
    session.pop("bank_default_category", None)
    if inserted:
        msg = f"Imported {inserted} transaction(s)"
        if skipped:
            msg += f", {skipped} skipped"
        flash(msg + ".", "success")
        if skip_reasons:
            flash(f"First issues: {'; '.join(skip_reasons[:3])}", "warning")
    else:
        flash(f"No rows imported ({skipped} skipped). Check your column mapping.",
              "error")
        if skip_reasons:
            flash(f"Issues: {'; '.join(skip_reasons[:3])}", "error")
    return redirect(url_for("transactions.index"))


@bp.route("/template/save", methods=["POST"])
@admin_required
def save_template():
    """Save the current mapping dropdowns as a named template for reuse."""
    db = get_db()
    name = (request.form.get("template_name") or "").strip()[:50]
    mapping = _mapping_from_form(request.form)
    if not name:
        flash("Give the template a name to save it.", "error")
        return redirect(url_for("bank_import.index"))
    if not templates_mod.validate_mapping(mapping):
        flash("Map the required columns before saving a template.", "error")
        return redirect(url_for("bank_import.index"))
    try:
        templates_mod.save_template(db, name, mapping)
        flash(f"Template '{name}' saved.", "success")
    except Exception:  # noqa: BLE001 — e.g. duplicate name
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass
        flash(f"Could not save template '{name}' (name may already exist).",
              "error")
    return redirect(url_for("bank_import.index"))


@bp.route("/template/delete/<int:template_id>", methods=["POST"])
@admin_required
def delete_template(template_id):
    db = get_db()
    cur = db.execute("DELETE FROM import_templates WHERE id=?", (template_id,))
    db.commit()
    if cur.rowcount:
        flash("Template deleted.", "success")
    else:
        flash("Template not found.", "error")
    return redirect(url_for("bank_import.index"))


def _process_bank_row(db, row, mapping, cats, user_id, default_cat_id=None,
                      seen_this_run=None):
    """Process a single bank CSV row and create the transaction.

    Returns the row fingerprint on success, False when skipped as an exact
    duplicate of a pre-existing transaction (re-upload protection; repeats
    within the same upload are still imported). Raises on other skips with
    the reason.
    """
    mapped = templates_mod.apply_mapping(row, mapping)
    if mapping.get("debit") or mapping.get("credit"):
        amount_raw, forced_type = templates_mod.combine_debit_credit(row, mapping)
        type_raw = mapped.get("type") or forced_type
    else:
        amount_raw, type_raw = mapped.get("amount"), mapped.get("type")
    date_str = templates_mod.infer_date_format(mapped.get("date"))
    if not date_str:
        raise ValueError(f"Cannot parse date: '{mapped.get('date')}'")
    from datetime import date
    if date_str > date.today().isoformat():
        raise ValueError(f"Date is in the future: {date_str}")
    ttype, amount_str = templates_mod.detect_type_from_amount(amount_raw, type_raw)
    if not amount_str:
        raise ValueError(f"Cannot parse amount: '{amount_raw}'")
    desc = (mapped.get("category") or "").strip()
    note = (mapped.get("note") or "").strip()[:200]
    if default_cat_id:
        cat = db.execute("SELECT * FROM categories WHERE id=?",
                         (default_cat_id,)).fetchone()
        if not cat:
            raise ValueError("Default category no longer exists")
        if cat["type"] != ttype:
            raise ValueError(f"Row is {ttype} but default category "
                             f"'{cat['name']}' is for {cat['type']}")
        BankCat, note = cat, (f"{desc} — {note}" if desc and note
                              else desc or note)[:200]
    else:
        if not desc:
            raise ValueError("Description is empty")
        key = desc.lower()
        if key in cats:
            BankCat = cats[key]
        else:
            category_models.insert(db, desc[:50], ttype)
            BankCat = db.execute("SELECT * FROM categories WHERE name=?",
                                 (desc[:50],)).fetchone()
            cats[key] = BankCat
        if BankCat["type"] != ttype:
            raise ValueError(f"Category '{desc}' is for {BankCat['type']}, not {ttype}")
    amount_cents, validated_cat, validated_date, note, err = tx_models.validate(
        db, amount_str, ttype, BankCat["id"], date_str, note)
    if err:
        raise ValueError(err)
    fp = (validated_date, amount_cents, ttype, validated_cat["id"], note,
          user_id)
    if seen_this_run is not None and fp not in seen_this_run:
        dup = db.execute(
            "SELECT id FROM transactions WHERE date=? AND amount=? AND type=?"
            " AND category_id=? AND note=?"
            " AND COALESCE(user_id, -1)=COALESCE(?, -1)"
            " AND deleted_at IS NULL LIMIT 1",
            (validated_date, amount_cents, ttype, validated_cat["id"],
             note, user_id)).fetchone()
        if dup:
            return False
    tx_models.create(db, amount_cents, ttype, validated_cat["id"],
                     validated_date, note, user_id)
    if seen_this_run is not None:
        seen_this_run.add(fp)
    return fp
