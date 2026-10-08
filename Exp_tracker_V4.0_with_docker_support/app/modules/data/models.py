"""Bulk CSV import + database backup/restore (Model layer).

Each importer takes decoded CSV text and returns (imported, skipped).
Rows commit individually so a bad row never rolls back good ones (and a
failed statement never poisons a Postgres transaction). Reuses the
categories/budgets/transactions models.

Backups are SQL dumps (.sql) — the primary format. The legacy JSON
snapshot format is still accepted on restore so old backups keep working.
"""
import csv
import io
import re
from datetime import datetime, timezone

from flask import current_app

from ...db import DB_ERRORS
from ...helpers import to_cents, from_cents
from ..budgets import models as budget_models
from ..categories import models as category_models
from ..transactions import models as transaction_models

ROW_LIMIT = 2000

BACKUP_VERSION = 1
BACKUP_TABLES = ("categories", "budgets", "transactions", "users", "recurring_transactions")

# Legacy table names accepted on restore (old backups keep working).
BACKUP_ALIASES = {"recurrences": "recurring_transactions", "audit_log": "audit_logs"}

# Money columns exported in rupees (major units) per table.
_MONEY_COLS = {
    "transactions": ("amount", "orig_amount"),
    "budgets": ("monthly_limit",),
    "recurring_transactions": ("amount", "orig_amount"),
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
    """CSV columns: name (text, required, ≤50 chars, unique), type (income|expense, required) — existing names are left untouched."""
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
    """CSV columns: category (text, required, existing expense category name), monthly_limit (number, required, > 0 rupees) — upserted by category name.

    Unknown, non-expense or savings-bucket categories are skipped.
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
            if not cat or cat["type"] != "expense" or cat["is_savings"]:
                raise ValueError
            budget_models.upsert(db, cat["id"], limit)
            db.commit()
            applied += 1
        except (ValueError, KeyError) + DB_ERRORS:
            db.rollback()
            skipped += 1
    return applied, skipped


def import_transactions(db, text, user_id=None):
    """CSV columns: date (YYYY-MM-DD, required), type (income|expense, required), category (text, required), amount (number > 0 rupees, required), note (text ≤200, optional), owner (username, optional), currency (3-letter code, optional, default INR).

    Delegates to the transactions module (unknown categories auto-created,
    rows attributed to the named owner or user_id).
    """
    return transaction_models.import_csv(db, text, user_id)


# ---------- CSV restore (replace data tables, preserve users) ----------

# Required CSV headers per file for a CSV restore.
CSV_RESTORE_REQUIRED = {
    "categories": ("name", "type"),
    "transactions": ("date", "type", "category", "amount"),
    "budgets": ("category", "monthly_limit"),
}

# Human-readable expected headers (shown in error messages).
CSV_RESTORE_HEADERS = {
    "categories": "name,type",
    "budgets": "category,monthly_limit",
    "transactions": "date,type,category,amount (required) + note,owner,currency (optional)",
}


def validate_csv_text(text, key, label):
    """Check a CSV file's headers/rows without touching the database.

    Returns (n_data_rows, error_msg). error_msg is None when the file looks usable.
    Row-level mistakes are still possible — the importer reports those as
    "skipped" counts — but a missing header or empty file aborts the restore
    before anything is wiped.
    """
    try:
        reader = csv.DictReader(io.StringIO(text))
        headers = reader.fieldnames or []
        rows = [r for r in reader
                if r and any((v or "").strip() for v in r.values())]
    except Exception:  # noqa: BLE001
        return 0, f"{label}: could not parse CSV. Make sure it is a valid .csv file."
    missing = [c for c in CSV_RESTORE_REQUIRED[key] if c not in headers]
    if missing:
        return 0, (f"{label}: missing column(s) {', '.join(missing)} — "
                   f"expected header “{CSV_RESTORE_HEADERS[key]}”.")
    if not rows:
        return 0, f"{label}: no data rows found. The file has only a header."
    if len(rows) > ROW_LIMIT:
        return 0, (f"{label}: too many rows ({len(rows)}, max {ROW_LIMIT}). "
                   f"Split the file and try again.")
    return len(rows), None


def restore_from_csv(db, csv_texts, user_id=None):
    """Replace data tables from CSV texts ({key: text}) — users are preserved.

    CSV has no users/recurring-transactions format, so: users are never wiped, and any
    existing recurring schedules are removed (reported back so the UI can say
    so). Default categories are re-seeded after the wipe so budgets that
    reference them keep working when no categories file is uploaded.

    All files are validated first; any validation error aborts with no
    changes made. Returns (results_dict, error_msg).
    """
    present = {k: t for k, t in (csv_texts or {}).items()
               if t and k in CSV_RESTORE_REQUIRED}
    if not present:
        return None, "Choose at least one CSV file to restore from."
    labels = {"categories": "Categories", "budgets": "Budgets",
              "transactions": "Transactions"}
    for key, text in present.items():
        _, err = validate_csv_text(text, key, labels[key])
        if err:
            return None, err
    try:
        rec_removed = db.execute("SELECT COUNT(*) FROM recurring_transactions").fetchone()[0]
    except DB_ERRORS:
        rec_removed = 0
    try:
        # FK-safe wipe: children first. Users are deliberately preserved.
        for table in ("transactions", "budgets", "recurring_transactions", "categories"):
            db.execute(f"DELETE FROM {table}")
        reseeded = category_models.seed_defaults(db)
        db.commit()
        results = {"recurring_transactions_removed": rec_removed,
                   "recurrences_removed": rec_removed, "defaults_reseeded": reseeded}
        if "categories" in present:
            results["categories"] = import_categories(db, present["categories"])
        else:
            results["categories"] = (0, 0)
        if "budgets" in present:
            results["budgets"] = import_budgets(db, present["budgets"])
        else:
            results["budgets"] = (0, 0)
        if "transactions" in present:
            results["transactions"] = import_transactions(
                db, present["transactions"], user_id)
        else:
            results["transactions"] = (0, 0)
    except DB_ERRORS as e:
        try:
            db.rollback()
        except DB_ERRORS:
            pass
        return None, f"Database error during CSV restore ({e})."
    return results, None


def summarize_csv_results(results):
    """'2 categories, 1 budget, 4 transactions' + skipped-row note."""
    parts = []
    skipped = 0
    for key, label in (("categories", "categories"), ("budgets", "budgets"),
                       ("transactions", "transactions")):
        imported, skip = results.get(key, (0, 0))
        skipped += skip
        if imported:
            parts.append(f"{imported} {label}")
    if results.get("defaults_reseeded"):
        parts.append(f"{results['defaults_reseeded']} default categories re-seeded")
    summary = ", ".join(parts) or "0 rows"
    if skipped:
        summary += f" ({skipped} row(s) skipped)"
    return summary


# ---------- database backup / restore (JSON, engine-agnostic) ----------
# NOTE: JSON is the legacy format — new backups are SQL dumps (see below).
# Restore still accepts JSON so backups downloaded before the SQL switch
# keep working.

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


def _opt_timeout(row, label="user"):
    """Per-user timeout override from a backup row (None = site default).

    Raises ValueError with a friendly message on out-of-range values.
    """
    value = row.get("session_timeout_minutes")
    if value in (None, ""):
        return None
    try:
        minutes = int(value)
    except (ValueError, TypeError):
        raise ValueError(
            f"{label}: session timeout must be 1–1440 minutes "
            f"(got {value!r}).")
    if not 1 <= minutes <= 1440:
        raise ValueError(
            f"{label}: session timeout must be 1–1440 minutes "
            f"(got {minutes}).")
    return minutes


def _opt_id(row, key, label="row"):
    """Optional FK id from a backup row (None = unset). Old backups lack the key."""
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        ref_id = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"{label}: '{key}' must be a positive id (got {value!r}).")
    if ref_id <= 0:
        raise ValueError(f"{label}: '{key}' must be a positive id (got {value!r}).")
    return ref_id


def _opt_backup_date(row, key, label):
    """Optional YYYY-MM-DD date from a backup row (None = unset)."""
    value = row.get(key)
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value).strip(), "%Y-%m-%d").date().isoformat()
    except (ValueError, TypeError, AttributeError):
        raise ValueError(
            f"{label}: {key} must look like YYYY-MM-DD (got {value!r}).")


def _normalize_backup_data(data):
    """Map legacy backup keys to current table names (old backups keep working)."""
    data = dict(data)
    for old, new in BACKUP_ALIASES.items():
        if old in data and new not in data:
            data[new] = data.pop(old)
        elif old in data:
            data.pop(old, None)
    return data


def _validate_backup(payload):
    """Return (data, error_msg). data is None when the payload is invalid.

    Errors are written for end users (shown verbatim after "Restore failed:").
    Legacy keys (e.g. 'recurrences') are accepted and normalized.
    """
    if not isinstance(payload, dict):
        return None, "Backup file is not a JSON object. Please upload an Expense Tracker (.json) backup."
    if payload.get("app") not in (None, "exptracker"):
        return None, (
            f"This doesn't look like an Expense Tracker backup "
            f"(found app={payload.get('app')!r}). Please upload a file "
            f"downloaded via “Download backup”.")
    version = payload.get("version", BACKUP_VERSION)
    try:
        version = int(version)
    except (ValueError, TypeError):
        return None, "Backup version is unreadable. The file may be corrupted."
    if version > BACKUP_VERSION:
        return None, (
            f"Backup version v{version} is newer than this app supports "
            f"(v{BACKUP_VERSION}). Please update the app, then try again.")
    data = payload.get("data")
    if not isinstance(data, dict):
        return None, "Backup file is missing the 'data' object. The file may be corrupted."
    data = _normalize_backup_data(data)
    for table in BACKUP_TABLES:
        rows = data.get(table, [])
        if not isinstance(rows, list):
            return None, f"Backup section '{table}' must be a list. The file may be corrupted."
        for row in rows:
            if not isinstance(row, dict):
                return None, f"Backup section '{table}' contains an invalid row. The file may be corrupted."
    total = sum(len(data.get(t, [])) for t in BACKUP_TABLES)
    if total == 0:
        return None, "Backup contains no data (0 rows). Nothing to restore — choose a non-empty backup file."
    return data, None


def describe_backup(payload):
    """Friendly summary of a backup payload for previews and success messages.

    Returns (info_dict, error_msg). info_dict has app/version/exported_at/counts/total.
    """
    data, err = _validate_backup(payload)
    if err:
        return None, err
    counts = {t: len(data.get(t, [])) for t in BACKUP_TABLES}
    return {
        "app": payload.get("app", "exptracker"),
        "version": payload.get("version", BACKUP_VERSION),
        "exported_at": payload.get("exported_at"),
        "counts": counts,
        "total": sum(counts.values()),
    }, None


def summarize_counts(counts):
    """'5 categories, 1 budget, 4 transactions, 1 user, 1 recurring schedule' (skips zeros)."""
    labels = (("categories", "categories"), ("budgets", "budgets"),
              ("transactions", "transactions"), ("users", "users"),
              ("recurring_transactions", "recurring_transactions"))
    # Legacy key from old backups.
    if "recurring_transactions" not in counts and "recurrences" in counts:
        counts = {**counts, "recurring_transactions": counts.get("recurrences", 0)}
    parts = [f"{counts.get(k, 0)} {label}"
             for k, label in labels if counts.get(k, 0)]
    return ", ".join(parts) or "0 rows"


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
        db.execute("DELETE FROM recurring_transactions")
        db.execute("DELETE FROM categories")
        db.execute("DELETE FROM users")

        for n, row in enumerate(data.get("users", []), start=1):
            label = f"Users row {n} ('{row.get('username', '?')}')"
            try:
                uid = int(row["id"])
                username = str(row["username"]).strip()
                pwd_hash = str(row["password_hash"])
                if uid <= 0 or not username or not pwd_hash:
                    raise ValueError("missing id, username or password.")
            except (KeyError, ValueError, TypeError, AttributeError) as e:
                raise ValueError(f"{label} is incomplete ({e}).")
            role = str(row.get("role") or "admin").strip().lower()
            if role not in ("admin", "viewer"):
                role = "admin"
            try:
                timeout = _opt_timeout(row, label)
            except ValueError as e:
                raise ValueError(str(e))
            db.execute(
                "INSERT INTO users (id, username, password_hash, created_at,"
                " session_timeout_minutes, role, totp_secret, totp_enabled)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (uid, username, pwd_hash, row.get("created_at") or None,
                 timeout, role,
                 row.get("totp_secret") or None,
                 1 if row.get("totp_enabled") in (1, "1", True) else 0),
            )
        for n, row in enumerate(data.get("categories", []), start=1):
            label = f"Categories row {n} ('{row.get('name', '?')}')"
            ctype = str(row.get("type", "")).strip().lower()
            if ctype not in ("income", "expense"):
                raise ValueError(
                    f"{label}: type must be 'income' or 'expense' "
                    f"(got {row.get('type')!r}).")
            try:
                cid = int(row["id"])
                name = str(row["name"]).strip()
                if cid <= 0 or not name:
                    raise ValueError("missing id or name.")
            except (KeyError, ValueError, TypeError, AttributeError) as e:
                raise ValueError(f"{label} is incomplete ({e}).")
            savings = row.get("is_savings", 0)
            try:
                savings = int(savings or 0)
            except (ValueError, TypeError):
                raise ValueError(
                    f"{label}: is_savings must be 0 or 1 (got {row.get('is_savings')!r}).")
            if savings not in (0, 1) or (savings and ctype != "expense"):
                raise ValueError(
                    f"{label}: is_savings must be 0, or 1 on an expense category.")
            db.execute(
                "INSERT INTO categories (id, name, type, is_savings) VALUES (?,?,?,?)",
                (cid, name, ctype, savings),
            )
        for n, row in enumerate(data.get("budgets", []), start=1):
            label = f"Budgets row {n}"
            try:
                bid = int(row["id"])
                cat_id = int(row["category_id"])
                if bid <= 0 or cat_id <= 0:
                    raise ValueError("ids must be positive.")
            except (KeyError, ValueError, TypeError) as e:
                raise ValueError(f"{label} has an invalid id ({e}).")
            try:
                limit = to_cents(row["monthly_limit"])
            except (ValueError, TypeError):
                raise ValueError(
                    f"{label}: monthly_limit must be a positive amount "
                    f"(got {row.get('monthly_limit')!r}).")
            if limit <= 0:
                raise ValueError(
                    f"{label}: monthly_limit must be more than 0 "
                    f"(got {row.get('monthly_limit')!r}).")
            db.execute(
                "INSERT INTO budgets (id, category_id, monthly_limit) VALUES (?,?,?)",
                (bid, cat_id, limit),
            )
        for n, row in enumerate(data.get("transactions", []), start=1):
            label = f"Transactions row {n} ('{str(row.get('note') or '')[:30]}')"
            ttype = str(row.get("type", "")).strip().lower()
            if ttype not in ("income", "expense"):
                raise ValueError(
                    f"{label}: type must be 'income' or 'expense' "
                    f"(got {row.get('type')!r}).")
            try:
                datetime.strptime(str(row.get("date", "")).strip(), "%Y-%m-%d")
            except (ValueError, TypeError):
                raise ValueError(
                    f"{label}: date must look like YYYY-MM-DD "
                    f"(got {row.get('date')!r}).")
            amount, orig, cerr = _restore_amount(row)
            if cerr:
                raise ValueError(f"{label}: {cerr}.")
            if amount is None or amount <= 0:
                raise ValueError(
                    f"{label}: amount must be more than 0 "
                    f"(got {row.get('amount')!r}).")
            try:
                tid = int(row["id"])
                cat_id = int(row["category_id"])
                if tid <= 0 or cat_id <= 0:
                    raise ValueError("ids must be positive.")
            except (KeyError, ValueError, TypeError) as e:
                raise ValueError(f"{label} has an invalid id ({e}).")
            code = str(row.get("currency") or _base_currency()).upper()
            db.execute(
                """INSERT INTO transactions
                   (id, amount, type, category_id, date, note, created_at, user_id,
                    currency, orig_amount, split_group)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (tid, amount, ttype, cat_id,
                 str(row["date"]).strip(), str(row.get("note") or "")[:200],
                 row.get("created_at") or None, _opt_id(row, "user_id", label),
                 code, orig, row.get("split_group") or None),
            )
        for n, row in enumerate(data.get("recurring_transactions", []), start=1):
            label = f"Recurring row {n} ('{str(row.get('note') or '')[:30]}')"
            freq = str(row.get("frequency", "")).strip().lower()
            if freq not in ("daily", "weekly", "monthly", "yearly"):
                raise ValueError(
                    f"{label}: frequency must be daily, weekly, monthly or yearly "
                    f"(got {row.get('frequency')!r}).")
            try:
                datetime.strptime(str(row.get("next_run_date", "")).strip(), "%Y-%m-%d")
            except (ValueError, TypeError):
                raise ValueError(
                    f"{label}: next_run_date must look like YYYY-MM-DD "
                    f"(got {row.get('next_run_date')!r}).")
            start = _opt_backup_date(row, "start_date", label)
            end = _opt_backup_date(row, "end_date", label)
            if start and end and end < start:
                raise ValueError(
                    f"{label}: end_date must be on or after the start date.")
            try:
                amount = to_cents(row["amount"])
            except (ValueError, TypeError):
                raise ValueError(
                    f"{label}: amount must be a positive number "
                    f"(got {row.get('amount')!r}).")
            if amount <= 0:
                raise ValueError(
                    f"{label}: amount must be more than 0 "
                    f"(got {row.get('amount')!r}).")
            try:
                rid = int(row["id"])
                if rid <= 0:
                    raise ValueError("id must be positive.")
            except (KeyError, ValueError, TypeError) as e:
                raise ValueError(f"{label} has an invalid id ({e}).")
            code = str(row.get("currency") or _base_currency()).upper()
            try:
                orig = to_cents(row["orig_amount"]) \
                    if row.get("orig_amount") not in (None, "") else None
            except (ValueError, TypeError):
                raise ValueError(
                    f"{label}: orig_amount must be a positive number "
                    f"(got {row.get('orig_amount')!r}).")
            rtype = str(row.get("type", "")).strip().lower()
            if rtype not in ("income", "expense"):
                raise ValueError(
                    f"{label}: type must be 'income' or 'expense' "
                    f"(got {row.get('type')!r}).")
            db.execute(
                """INSERT INTO recurring_transactions
                   (id, user_id, amount, type, category_id, note, currency,
                    orig_amount, frequency, next_run_date, start_date, end_date,
                    active, last_run_at, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (rid, _opt_id(row, "user_id", label), amount, rtype,
                 _opt_id(row, "category_id", label), str(row.get("note") or "")[:200],
                 code, orig, freq, str(row.get("next_run_date")).strip(),
                 start, end,
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
    try:
        base = to_cents(row["amount"])
    except (ValueError, TypeError):
        return None, None, f"amount must be a positive number (got {row.get('amount')!r})"
    orig_raw = row.get("orig_amount")
    if code == _base_currency() or orig_raw in (None, ""):
        return base, None, None
    rates = _rates()
    if code not in rates:
        supported = ", ".join(sorted(rates) or [code])
        return None, None, f"unknown currency {code!r} (supported: {supported})"
    try:
        orig = to_cents(orig_raw)
    except (ValueError, TypeError):
        return None, None, f"orig_amount must be a positive number (got {orig_raw!r})"
    base = int(round(orig * float(rates[code])))
    return base, orig, None


# ---------- database backup / restore (SQL dump — primary format) ----------

SQL_BACKUP_MARKER = "-- exptracker SQL backup"

# Columns that exist in the live schema but must never appear in a dump
# (e.g. Postgres GENERATED columns, which reject explicit inserts).
_SKIP_DUMP_COLS = {"search_tsv"}

# Statements a dump may contain besides data writes (executed or skipped).
_SKIP_SQL_RE = re.compile(r"^(BEGIN|COMMIT|ROLLBACK|END|PRAGMA\b.*)$", re.I)
_DELETE_SQL_RE = re.compile(r'^DELETE\s+FROM\s+"?([A-Za-z_]\w*)"?\s*$', re.I)
_INSERT_SQL_RE = re.compile(
    r'^INSERT\s+INTO\s+"?([A-Za-z_]\w*)"?(?:\s*\([^;]*\))?\s*VALUES\s*\(.*\)$',
    re.I | re.S)


def _sql_literal(value):
    """Render a DB value as a SQL literal (exact round-trip, no money conversion)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def export_sql_backup(db):
    """Dump all backup tables to a SQL script (exact row copy, cents intact).

    Data-only dump: DELETEs (children first) + INSERTs with explicit ids and
    column lists, so foreign keys survive. Restoring assumes the current
    schema already exists (init_db/migrations create it); Postgres sequences
    are reset by the restore, not the dump.
    """
    engine = getattr(db, "engine", "sqlite")
    lines = [
        SQL_BACKUP_MARKER,
        "-- app: exptracker",
        f"-- version: {BACKUP_VERSION}",
        f"-- exported_at: {datetime.now(timezone.utc).isoformat()}",
        f"-- engine: {engine}",
        f"-- tables: {', '.join(BACKUP_TABLES)}",
        "",
    ]
    for table in ("transactions", "budgets", "recurring_transactions", "categories", "users"):
        lines.append(f'DELETE FROM "{table}";')
    lines.append("")
    for table in ("users", "categories", "budgets", "transactions", "recurring_transactions"):
        rows = db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
        for r in rows:
            cols = [c for c in dict(r).keys() if c not in _SKIP_DUMP_COLS]
            col_list = ", ".join(f'"{c}"' for c in cols)
            vals = ", ".join(_sql_literal(dict(r)[c]) for c in cols)
            lines.append(f'INSERT INTO "{table}" ({col_list}) VALUES ({vals});')
    lines.append("")
    return "\n".join(lines)


def _split_sql_statements(text):
    """Split SQL text into statements, respecting quotes and comments.

    Returns statements without trailing semicolons. Raises ValueError on
    unterminated quotes/comments.
    """
    stmts, buf = [], []
    i, n = 0, len(text)
    in_sq = in_dq = in_lc = in_bc = False
    while i < n:
        ch = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_lc:
            if ch == "\n":
                in_lc = False
                buf.append(ch)
            i += 1
            continue
        if in_bc:
            if ch == "*" and nxt == "/":
                in_bc = False
                i += 2
            else:
                i += 1
            continue
        if in_sq:
            buf.append(ch)
            if ch == "'":
                if nxt == "'":
                    buf.append(nxt)
                    i += 2
                    continue
                in_sq = False
            i += 1
            continue
        if in_dq:
            buf.append(ch)
            if ch == '"':
                if nxt == '"':
                    buf.append(nxt)
                    i += 2
                    continue
                in_dq = False
            i += 1
            continue
        if ch == "-" and nxt == "-":
            in_lc = True
            i += 2
            continue
        if ch == "/" and nxt == "*":
            in_bc = True
            i += 2
            continue
        if ch == "'":
            in_sq = True
            buf.append(ch)
            i += 1
            continue
        if ch == '"':
            in_dq = True
            buf.append(ch)
            i += 1
            continue
        if ch == ";":
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
            i += 1
            continue
        buf.append(ch)
        i += 1
    if in_sq or in_dq:
        raise ValueError("unterminated quoted string")
    if in_bc:
        raise ValueError("unterminated comment")
    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)
    return stmts


def restore_sql_backup(db, sql_text):
    """Replace all data with the contents of a SQL-dump backup.

    Only DELETE/INSERT statements against the known backup tables are
    executed (anything else — CREATE/DROP/ALTER/UPDATE/… — is rejected, so
    a crafted file cannot touch other tables). File DELETEs are validated
    but the wipe is redone in FK-safe order; INSERTs run in dependency
    order. All-or-nothing: any failure rolls back with no changes made.
    Legacy table names (e.g. recurrences) are accepted and mapped.

    Returns (counts_dict, error_msg) — counts is None on failure.
    """
    if not isinstance(sql_text, str) or not sql_text.strip():
        return None, "Backup file is empty. Choose a non-empty .sql backup file."
    head = sql_text[:4000]
    if "exptracker sql backup" not in head.lower():
        return None, (
            "This doesn't look like an Expense Tracker SQL backup "
            "(missing header). Please upload a .sql file downloaded via "
            "“Download backup”.")
    m = re.search(r"--\s*version:\s*(\S+)", head, re.I)
    if m:
        try:
            version = int(m.group(1))
        except (ValueError, TypeError):
            return None, "Backup version is unreadable. The file may be corrupted."
        if version > BACKUP_VERSION:
            return None, (
                f"Backup version v{version} is newer than this app supports "
                f"(v{BACKUP_VERSION}). Please update the app, then try again.")
    try:
        stmts = _split_sql_statements(sql_text)
    except ValueError as e:
        return None, f"Could not read SQL backup ({e}). The file may be corrupted."
    inserts_by_table = {t: [] for t in BACKUP_TABLES}
    for stmt in stmts:
        s = stmt.strip()
        if not s or _SKIP_SQL_RE.match(s):
            continue
        dm = _DELETE_SQL_RE.match(s)
        if dm:
            name = BACKUP_ALIASES.get(dm.group(1), dm.group(1))
            if name not in BACKUP_TABLES:
                return None, (
                    f"Backup targets unknown table '{dm.group(1)}'. "
                    f"The file may be corrupted.")
            continue  # wipe is redone below in FK-safe order
        im = _INSERT_SQL_RE.match(s)
        if im:
            raw_name = im.group(1)
            name = BACKUP_ALIASES.get(raw_name, raw_name)
            if name not in BACKUP_TABLES:
                return None, (
                    f"Backup targets unknown table '{raw_name}'. "
                    f"The file may be corrupted.")
            if name != raw_name:
                # Rewrite legacy table name to the current one.
                s = re.sub(r'^INSERT\s+INTO\s+"?' + re.escape(raw_name) + r'"?',
                           f'INSERT INTO "{name}"', s, count=1, flags=re.I)
            inserts_by_table[name].append(s)
            continue
        preview = (s[:60] + "…") if len(s) > 60 else s
        return None, (
            f"Unsupported statement ({preview}). Only DELETE/INSERT of the "
            f"backup tables are allowed in a SQL backup.")
    total = sum(len(v) for v in inserts_by_table.values())
    if total == 0:
        return None, (
            "Backup contains no data (0 rows). Nothing to restore — "
            "choose a non-empty backup file.")
    try:
        # FK-safe wipe: children first (mirrors the JSON restore).
        for table in ("transactions", "budgets", "recurring_transactions",
                      "categories", "users"):
            db.execute(f"DELETE FROM {table}")
        # Parents first so foreign keys resolve.
        for table in ("users", "categories", "budgets",
                      "transactions", "recurring_transactions"):
            for stmt in inserts_by_table[table]:
                db.execute_raw(stmt)
        if getattr(db, "engine", "sqlite") == "pg":
            for table in BACKUP_TABLES:
                db.execute_raw(
                    "SELECT setval(pg_get_serial_sequence('" + table + "', 'id'), "
                    "COALESCE((SELECT MAX(id) FROM " + table + "), 1), "
                    "(SELECT COUNT(*) FROM " + table + ") > 0)"
                )
        db.commit()
    except DB_ERRORS as e:
        db.rollback()
        return None, f"Invalid backup data ({e}). No changes were made."
    counts = {t: len(inserts_by_table[t]) for t in BACKUP_TABLES}
    return counts, None
