from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from ...db import get_db
from ...helpers import parse_month
from . import bp
from ..transactions import models as tx_models
from ..categories import models as category_models
from ..import_templates import __init__ as templates_mod
import csv
import io
import json


@bp.route("/")
def index():
    db = get_db()
    templates = db.execute("SELECT * FROM import_templates").fetchall()
    return render_template("bank_import/index.html", templates=templates)


@bp.route("/preview", methods=["POST"])
def preview():
    """Preview the first few rows of the uploaded CSV after mapping."""
    db = get_db()
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".csv"):
        flash("Please upload a valid .csv file.", "error")
        return redirect(url_for("bank_import.index"))

    # Get mapping from form or template
    template_id = request.form.get("template_id")
    mapping = _get_mapping(db, template_id, request.form)
    
    if not templates_mod.validate_mapping(mapping):
        flash("Please provide mappings for all required fields (date, type, category, amount).", "error")
        return redirect(url_for("bank_import.index"))

    try:
        file_bytes = f.read()
        text = templates_mod.detect_csv_encoding(file_bytes)
        reader = csv.DictReader(io.StringIO(text))
        
        preview_rows = []
        skipped_preview = []
        
        for i, row in enumerate(reader):
            if i >= 5:  # Preview first 5 rows
                break
            try:
                mapped = templates_mod.apply_mapping(row, mapping)
                
                # Parse date
                date_str = templates_mod.infer_date_format(mapped.get("date"))
                
                # Detect type and normalize amount
                ttype, amount_str = templates_mod.detect_type_from_amount(
                    mapped.get("amount"), mapped.get("type")
                )
                
                preview_rows.append({
                    'date': date_str or mapped.get("date", "?"),
                    'type': ttype,
                    'category': mapped.get("category", ""),
                    'amount': amount_str or mapped.get("amount", "?"),
                    'note': mapped.get("note", ""),
                    'raw': dict(mapped)
                })
            except Exception as e:
                skipped_preview.append(f"Row {i+1}: {str(e)}")
        
        return render_template("bank_import/preview.html",
                               preview_rows=preview_rows,
                               skipped=skipped_preview,
                               mapping=mapping,
                               template_id=template_id)
    except Exception as e:
        flash(f"Could not preview file: {str(e)}", "error")
        return redirect(url_for("bank_import.index"))


@bp.route("/import", methods=["POST"])
def import_bank():
    """Actually import the transactions after preview."""
    db = get_db()
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".csv"):
        flash("Please upload a valid .csv file.", "error")
        return redirect(url_for("bank_import.index"))

    # Get mapping from form or template
    template_id = request.form.get("template_id")
    mapping = _get_mapping(db, template_id, request.form)
    
    if not templates_mod.validate_mapping(mapping):
        flash("Invalid mapping configuration.", "error")
        return redirect(url_for("bank_import.index"))

    try:
        file_bytes = f.read()
        text = templates_mod.detect_csv_encoding(file_bytes)
        reader = csv.DictReader(io.StringIO(text))
        
        inserted = 0
        skipped = 0
        skip_reasons = []
        me = tx_models.recorded_by(db, session.get("user", ""))
        
        # Preload categories for faster lookup
        cats = {r["name"].lower(): r for r in db.execute("SELECT * FROM categories").fetchall()}
        
        for i, row in enumerate(reader, start=1):
            try:
                result = _process_bank_row(db, row, mapping, cats, me)
                if result:
                    inserted += 1
                else:
                    skipped += 1
            except Exception as e:
                skipped += 1
                skip_reasons.append(f"Row {i}: {str(e)}")
                if len(skip_reasons) > 10:
                    skip_reasons.append("... (additional errors suppressed)")
                    break
        
        if inserted > 0:
            msg = f"Imported {inserted} transaction(s)"
            if skipped > 0:
                msg += f", {skipped} skipped"
            flash(msg, "success")
            if skip_reasons:
                flash(f"First errors: {'; '.join(skip_reasons[:3])}", "warning")
        else:
            flash(f"No rows imported ({skipped} skipped). Check your column mappings.", "error")
            if skip_reasons:
                flash(f"Errors: {'; '.join(skip_reasons[:3])}", "error")
                
    except Exception as e:
        flash(f"Import failed: {str(e)}", "error")

    return redirect(url_for("bank_import.index"))


def _get_mapping(db, template_id, form):
    """Get mapping from template or form."""
    mapping = None
    
    if template_id:
        template = templates_mod.get_template_by_id(db, template_id)
        if template:
            mapping = json.loads(template["mapping"])
    
    if not mapping:
        mapping = {
            "date": form.get("map_date"),
            "type": form.get("map_type"),
            "category": form.get("map_category"),
            "amount": form.get("map_amount"),
            "note": form.get("map_note")  # Optional
        }
    
    # Remove empty optional fields
    mapping = {k: v for k, v in mapping.items() if v}
    
    return mapping


def _process_bank_row(db, row, mapping, cats, user_id):
    """Process a single bank CSV row and create transaction.
    
    Returns True on success, False on skip.
    """
    # Apply column mapping
    mapped = templates_mod.apply_mapping(row, mapping)
    
    # Parse and validate date
    date_raw = mapped.get("date")
    date_str = templates_mod.infer_date_format(date_raw)
    if not date_str:
        raise ValueError(f"Cannot parse date: '{date_raw}'")
    
    # Validate date is not in future
    from datetime import date
    if date_str > date.today().isoformat():
        raise ValueError(f"Date is in the future: {date_str}")
    
    # Detect type and normalize amount
    type_raw = mapped.get("type")
    amount_raw = mapped.get("amount")
    ttype, amount_str = templates_mod.detect_type_from_amount(amount_raw, type_raw)
    
    if not amount_str:
        raise ValueError(f"Cannot parse amount: '{amount_raw}'")
    
    # Resolve category
    cat_name = mapped.get("category", "")
    if not cat_name:
        raise ValueError("Category/description is empty")
    
    cat_name = str(cat_name).strip()
    cat_key = cat_name.lower()
    
    if cat_key in cats:
        cat = cats[cat_key]
    else:
        # Auto-create category
        category_models.insert(db, cat_name, ttype)
        cat = db.execute("SELECT * FROM categories WHERE name=?", (cat_name,)).fetchone()
        cats[cat_key] = cat
    
    if cat["type"] != ttype:
        raise ValueError(f"Category '{cat_name}' is for {cat['type']}, not {ttype}")
    
    # Validate using existing models
    amount_cents, validated_cat, validated_date, note, err = tx_models.validate(
        db, amount_str, ttype, cat["id"], date_str, mapped.get("note", "")
    )
    if err:
        raise ValueError(err)
    
    # Create the transaction
    tx_models.create(db, amount_cents, ttype, validated_cat["id"], validated_date, note, user_id)
    
    return True
