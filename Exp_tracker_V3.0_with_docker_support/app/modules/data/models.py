"""Bulk CSV import for the whole dataset (Model layer).

Each importer takes decoded CSV text and returns (imported, skipped).
Rows commit individually so a bad row never rolls back good ones (and a
failed statement never poisons a Postgres transaction). Reuses the
categories/budgets/transactions models.
"""
import csv
import io
from datetime import datetime, timezone

from flask import current_app

from ...db import DB_ERRORS
from ...helpers import to_cents, from_cents
from ..budgets import models as budget_models
from ..categories import models as category_models
from ..transactions import models as transaction_models

ROW_LIMIT = 2000

BACKUP_VERSION = 1
BACKUP_TABLES = ("categories", "budgets", "transactions", "users", "recurrences")

# Money columns exported in rupees (major units) per table.
_MONEY_COLS = {
    "transactions": ("amount", "orig_amount"),
    "budgets": ("monthly_limit",),
    "recurrences": ("amount", "orig_amount"),
}


def _base_currency():
    """Base currency code; falls back to config defaults without app context."""
    try:
        return current_app.config.get("BASE_CURRENCY", "INR")
    except RuntimeError:
        from ...config import BASE_CURRENCY
        return BASE_CURRENCY


def _rates():
    try:
        return current_app.config.get("CURRENCY_RATES", {})
    except RuntimeError:
        from ...config import CURRENCY_RATES
        return CURRENCY_RATES


def import_categories(db, text):
    """CSV columns: name,type — existing names are left untouched."""
    reader = csv.DictReader(io.StringIO(text))
    inserted, skipped = 0, 0
    for i, row in enumerate(reader, start=1):
        if i > ROW_LIMIT:
            break
        try:
            name = (row.get("name") or "").strip()[:50]
            ctype = (row.get("type") or "expense").strip().lower()
            if not name or ctype not in ("income", "expense"):
                raise ValueError
            if category_models.insert(db, name, ctype):
                db.commit()
                inserted += 1
            else:
                skipped += 1  # name already exists
        except (ValueError, KeyError) + DB_ERRORS:
            db.rollback()
            skipped += 1
    return inserted, skipped


def import_budgets(db, text):
    """CSV columns: category,monthly_limit — upserted by category name.

    Unknown or non-expense categories are skipped.
    """
    reader = csv.DictReader(io.StringIO(text))
    cats = {r["name"].lower(): r for r in category_models.all(db)}
    applied, skipped = 0, 0
    for i, row in enumerate(reader, start=1):
        if i > ROW_LIMIT:
            break
        try:
            cat_name = (row.get("category") or "").strip()
            limit_raw = (row.get("monthly_limit") or "").strip()
            limit = round(float(limit_raw.replace(",", "")), 2)
            if limit <= 0 or not cat_name:
                raise ValueError
            cat = cats.get(cat_name.lower())
            if not cat or cat["type"] != "expense":
                raise ValueError
            budget_models.upsert(db, cat["id"], limit)
            db.commit()
            applied += 1
        except (ValueError, KeyError) + DB_ERRORS:
            db.rollback()
            skipped += 1
    return applied, skipped


def import_transactions(db, text, user_id=None):
    """CSV columns: date,type,category,amount,note[,owner].

    Delegates to the transactions module (unknown categories auto-created,
    rows attributed to the named owner or user_id).
    """
    return transaction_models.import_csv(db, text, user_id)


# ---------- database backup / restore (JSON, engine-agnostic) ----------

def _json_safe(value):
    """Coerce a DB value to something json.dumps can handle."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def export_backup(db):
    """Dump all tables to a JSON-serializable dict (SQLite and Postgres).

    Includes explicit ids so foreign keys survive a restore, plus a
    version stamp for forward compatibility. Money is exported in rupees
    (major units) so backups stay human-readable and engine-portable.
    """
    data = {}
    for table in BACKUP_TABLES:
        rows = db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        money_cols = _MONEY_COLS.get(table, ())
        out_rows = []
        for r in rows:
            d = {k: _json_safe(v) for k, v in dict(r).items()}
            for col in money_cols:
                if d.get(col) is not None:
                    d[col] = round(from_cents(d[col]), 2)
            out_rows.append(d)
        data[table] = out_rows
    return {
        "app": "exptracker",
        "version": BACKUP_VERSION,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "data": data,
    }


def _opt_timeout(row):
    """Per-user timeout override from a backup row (None = site default).

    Raises ValueError on out-of-range values so the restore aborts cleanly.
    """
    value = row.get("session_timeout_minutes")
    if value in (None, ""):
        return None
    minutes = int(value)
    if not 1 <= minutes <= 1440:
        raise ValueError(f"bad session_timeout_minutes: {row!r}")
    return minutes


def _opt_id(row, key):
    """Optional FK id from a backup row (None = unset). Old backups lack the key."""
    value = row.get(key)
    if value in (None, ""):
        return None
    ref_id = int(value)
    if ref_id <= 0:
        raise ValueError(f"bad {key}: {row!r}")
    return ref_id


def _validate_backup(payload):
    """Return (data, error_msg). data is None when the payload is invalid."""
    if not isinstance(payload, dict):
        return None, "Backup file is not a JSON object."
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, "Backup file is missing the 'data' object."
    for table in BACKUP_TABLES:
        rows = data.get(table, [])
        if not isinstance(rows, list):
            return None, f"Backup section '{table}' must be a list."
        for row in rows:
            if not isinstance(row, dict):
                return None, f"Backup section '{table}' contains an invalid row."
    return data, None


def restore_backup(db, payload):
    """Replace all data with the contents of a backup payload.

    Validates structure first, then wipes tables in FK-safe order and
    re-inserts with original ids inside a single transaction. Money in the
    payload is in rupees and is converted back to integer cents. Postgres
    sequences are reset so new rows continue after the restored max id.

    Returns (counts_dict, error_msg) — counts is None on failure.
    """
    data, err = _validate_backup(payload)
    if err:
        return None, err
    try:
        # FK-safe wipe: children first.
        db.execute("DELETE FROM transactions")
        db.execute("DELETE FROM budgets")
        db.execute("DELETE FROM recurrences")
        db.execute("DELETE FROM categories")
        db.execute("DELETE FROM users")

        for row in data.get("users", []):
            role = str(row.get("role") or "admin").strip().lower()
            if role not in ("admin", "viewer"):
                role = "admin"
            db.execute(
                "INSERT INTO users (id, username, password_hash, created_at,"
                " session_timeout_minutes, role, totp_secret, totp_enabled)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (int(row["id"]), str(row["username"]),
                 str(row["password_hash"]), row.get("created_at") or None,
                 _opt_timeout(row), role,
                 row.get("totp_secret") or None,
                 1 if row.get("totp_enabled") in (1, "1", True) else 0),
            )
        for row in data.get("categories", []):
            ctype = str(row.get("type", "")).strip().lower()
            if ctype not in ("income", "expense"):
                raise ValueError(f"bad category type: {row!r}")
            db.execute(
                "INSERT INTO categories (id, name, type) VALUES (?,?,?)",
                (int(row["id"]), str(row["name"]), ctype),
            )
        for row in data.get("budgets", []):
            limit = to_cents(row["monthly_limit"])
            if limit <= 0:
                raise ValueError(f"bad monthly_limit: {row!r}")
            db.execute(
                "INSERT INTO budgets (id, category_id, monthly_limit) VALUES (?,?,?)",
                (int(row["id"]), int(row["category_id"]), limit),
            )
        for row in data.get("transactions", []):
            ttype = str(row.get("type", "")).strip().lower()
            datetime.strptime(str(row.get("date", "")).strip(), "%Y-%m-%d")
            amount, orig, cerr = _restore_amount(row)
            if cerr:
                raise ValueError(cerr)
            if amount <= 0 or ttype not in ("income", "expense"):
                raise ValueError(f"bad transaction: {row!r}")
            code = str(row.get("currency") or _base_currency()).upper()
            db.execute(
                """INSERT INTO transactions
                   (id, amount, type, category_id, date, note, created_at, user_id,
                    currency, orig_amount, split_group)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (int(row["id"]), amount, ttype, int(row["category_id"]),
                 str(row["date"]).strip(), str(row.get("note") or "")[:200],
                 row.get("created_at") or None, _opt_id(row, "user_id"),
                 code, orig, row.get("split_group") or None),
            )
        for row in data.get("recurrences", []):
            freq = str(row.get("frequency", "")).strip().lower()
            datetime.strptime(str(row.get("next_run_date", "")).strip(), "%Y-%m-%d")
            amount = to_cents(row["amount"])
            if amount <= 0 or freq not in ("daily", "weekly", "monthly", "yearly"):
                raise ValueError(f"bad recurrence: {row!r}")
            code = str(row.get("currency") or _base_currency()).upper()
            orig = to_cents(row["orig_amount"]) \
                if row.get("orig_amount") not in (None, "") else None
            db.execute(
                """INSERT INTO recurrences
                   (id, user_id, amount, type, category_id, note, currency,
                    orig_amount, frequency, next_run_date, active, last_run_at,
                    created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (int(row["id"]), _opt_id(row, "user_id"), amount,
                 str(row.get("type", "")).strip().lower(),
                 _opt_id(row, "category_id"), str(row.get("note") or "")[:200],
                 code, orig, freq, str(row.get("next_run_date")).strip(),
                 1 if row.get("active", 1) in (1, "1", True) else 0,
                 row.get("last_run_at") or None, row.get("created_at") or None),
            )

        if getattr(db, "engine", "sqlite") == "pg":
            for table in BACKUP_TABLES:
                # 3-arg setval: empty tables restart at 1, others continue
                # after the restored max id.
                db.execute(
                    "SELECT setval(pg_get_serial_sequence('" + table + "', 'id'), "
                    "COALESCE((SELECT MAX(id) FROM " + table + "), 1), "
                    "(SELECT COUNT(*) FROM " + table + ") > 0)"
                )

        db.commit()
    except (ValueError, KeyError, TypeError) + DB_ERRORS as e:
        db.rollback()
        return None, f"Invalid backup data ({e}). No changes were made."
    counts = {t: len(data.get(t, [])) for t in BACKUP_TABLES}
    return counts, None


def _restore_amount(row):
    """(base_cents, orig_cents_or_None, error) for a backup transaction row.

    Old backups have only `amount` in rupees (base currency). Newer backups
    may carry `currency` + `orig_amount` (both in rupees): the base amount
    is reconverted from the original at the configured rate.
    """
    code = str(row.get("currency") or _base_currency()).upper()
    base = to_cents(row["amount"])
    orig_raw = row.get("orig_amount")
    if code == _base_currency() or orig_raw in (None, ""):
        return base, None, None
    rates = _rates()
    if code not in rates:
        return None, None, f"unknown currency {code!r} in backup"
    orig = to_cents(orig_raw)
    base = int(round(orig * float(rates[code])))
    return base, orig, None
