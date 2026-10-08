"""Transaction data access, validation, CSV import, bulk ops (Model layer)."""
import csv
import io
import re
import uuid
from datetime import date, datetime

from flask import current_app

from ...db import DB_ERRORS
from ...helpers import month_bounds, parse_month, to_cents, from_cents

from ..categories import models as category_models

SORT_COLUMNS = {"date": "t.date", "amount": "t.amount", "category": "c.name"}
PER_PAGE_CHOICES = (10, 25, 50, 100)
IMPORT_ROW_LIMIT = 2000
MAX_SPLIT_LINES = 3  # optional extra split lines on the add form (2..4)

LIST_SQL = """SELECT t.*, c.name AS category_name, c.is_savings AS is_savings, u.username AS owner_name
               FROM transactions t JOIN categories c ON t.category_id=c.id
               LEFT JOIN users u ON u.id=t.user_id"""


def rate_to_base(code):
    """Conversion rate: 1 unit of `code` -> base-currency units."""
    rates = current_app.config.get("CURRENCY_RATES", {})
    return float(rates.get((code or "").upper(), 1.0))


def base_currency():
    return current_app.config.get("BASE_CURRENCY", "INR")


def recorded_by(db, username):
    """User id for username (default owner of a new transaction), or None."""
    row = db.execute("SELECT id FROM users WHERE username=?",
                     (username or "",)).fetchone()
    return row["id"] if row else None


def resolve_owner(db, raw_value, default_id):
    """Return (user_id_or_None, error_msg) for a form owner value.

    Blank means the default (usually the current user); a numeric id must
    belong to an existing user.
    """
    text = (raw_value or "").strip()
    if not text:
        return default_id, None
    if not text.isdigit():
        return None, "Please select a valid user."
    if not db.execute("SELECT id FROM users WHERE id=?",
                      (int(text),)).fetchone():
        return None, "Please select a valid user."
    return int(text), None


def convert_to_base(amount_raw, currency):
    """Return (base_cents, orig_cents_or_None, error) for a form amount+currency.

    The amount is entered in `currency`; it is stored as INTEGER cents in the
    base currency plus the original cents so the entry can be shown/replayed.
    """
    try:
        orig = to_cents(amount_raw)
    except (ValueError, TypeError):
        return None, None, "Amount must be a positive number."
    if orig <= 0:
        return None, None, "Amount must be a positive number."
    code = (currency or base_currency()).strip().upper()
    if code != base_currency() and code not in current_app.config.get("CURRENCY_RATES", {}):
        return None, None, f"Unsupported currency: {code}."
    rate = rate_to_base(code)
    base = int(round(orig * rate))
    if base <= 0:
        return None, None, "Amount converts to zero — increase it."
    return base, (orig if code != base_currency() else None), None


# ---------- validation ----------
def validate(db, amount_raw, ttype, category_id, date_str, note):
    """Return (amount_cents, cat_row, date_str, note, error_msg)."""
    try:
        amount = to_cents(amount_raw)
        if amount <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        return None, None, None, None, "Amount must be a positive number."
    if ttype not in ("income", "expense"):
        return None, None, None, None, "Invalid transaction type."
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None, None, None, None, "Invalid date (use YYYY-MM-DD)."
    if date_str > date.today().isoformat():
        return None, None, None, None, "Date cannot be in the future."
    try:
        cat = db.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    except (ValueError,) + DB_ERRORS:
        cat = None
    if not cat:
        return None, None, None, None, "Please select a valid category."
    if cat["type"] != ttype:
        return None, None, None, None, f"Category '{cat['name']}' is for {cat['type']}, not {ttype}."
    note = (note or "").strip()[:200]
    return amount, cat, date_str, note, None


def parse_splits(db, form, ttype, total_cents):
    """Validate optional split lines from the add form.

    Each line is `split_category_N` + `split_amount_N` (N in 2..MAX+1).
    Lines are validated against the transaction type; their base amounts
    must be strictly less than the main amount — the remainder stays on the
    main category. Splits apply when at least one extra line is filled.

    Returns (lines_or_None, error_msg) where lines is a list of
    (category_id, base_cents) — None when no split was requested.
    """
    lines = []
    for n in range(2, MAX_SPLIT_LINES + 2):
        cat_raw = (form.get(f"split_category_{n}") or "").strip()
        amt_raw = (form.get(f"split_amount_{n}") or "").strip()
        if not cat_raw and not amt_raw:
            continue
        if not cat_raw or not amt_raw:
            return None, "Each split line needs both a category and an amount."
        try:
            cat = db.execute("SELECT * FROM categories WHERE id=?", (cat_raw,)).fetchone()
        except (ValueError,) + DB_ERRORS:
            cat = None
        if not cat:
            return None, "Split line has an invalid category."
        if cat["type"] != ttype:
            return None, f"Split category '{cat['name']}' is for {cat['type']}, not {ttype}."
        amount = to_cents(amt_raw)
        if amount <= 0:
            return None, "Split amounts must be positive numbers."
        lines.append((cat["id"], amount))
    if not lines:
        return None, None
    if sum(a for _, a in lines) >= total_cents:
        return None, ("Split amounts must be less than the main amount — "
                      "the remainder stays on the main category.")
    return lines, None


# ---------- FTS (SQLite FTS5 / Postgres tsvector) ----------
def fts_available(db):
    """True when full-text search is usable (FTS5 on SQLite, tsvector on PG)."""
    if db.engine == "sqlite":
        try:
            db.execute("SELECT 1 FROM transactions_fts LIMIT 1").fetchone()
            return True
        except DB_ERRORS:
            try:
                db.rollback()
            except DB_ERRORS:
                pass
            return False
    # Postgres: check for the generated tsvector column (cached per process).
    global _PG_TSV_OK
    if _PG_TSV_OK is not None:
        return _PG_TSV_OK
    try:
        rows = db.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name='transactions' AND column_name='search_tsv'").fetchall()
        _PG_TSV_OK = bool(rows)
    except DB_ERRORS:
        try:
            db.rollback()
        except DB_ERRORS:
            pass
        _PG_TSV_OK = False
    return _PG_TSV_OK


_PG_TSV_OK = None


def _fts_query(search):
    """Build a safe MATCH expression from free text ('"foo" AND "bar"')."""
    tokens = re.findall(r"\w+", search or "")
    return " AND ".join(f'"{t}"' for t in tokens)


# ---------- filter query builder ----------
def filter_query(db, f_type, f_category, f_owner, f_month, f_search, sort, order):
    """Build WHERE/ORDER BY clauses from parsed filter params.

    Values are always bound via `args`; identifiers come from whitelists.
    Note search uses the FTS5 index on SQLite when available, LIKE otherwise.
    """
    if sort not in SORT_COLUMNS:
        sort = "date"
    if order not in ("asc", "desc"):
        order = "desc"
    where = "WHERE t.deleted_at IS NULL"
    args = []
    if f_type in ("income", "expense"):
        where += " AND t.type = ?"
        args.append(f_type)
    if f_category != "all" and f_category.isdigit():
        where += " AND t.category_id = ?"
        args.append(int(f_category))
    if f_owner == "none":
        where += " AND t.user_id IS NULL"
    elif f_owner != "all" and f_owner.isdigit():
        where += " AND t.user_id = ?"
        args.append(int(f_owner))
    if f_month:
        yy, mm = parse_month(f_month)
        s, e = month_bounds(yy, mm)
        where += " AND t.date >= ? AND t.date < ?"
        args.extend([s, e])
    if f_search:
        if fts_available(db) and db.engine == "sqlite":
            match = _fts_query(f_search)
            if match:
                where += (" AND (t.id IN (SELECT rowid FROM transactions_fts"
                          " WHERE transactions_fts MATCH ?) OR c.name LIKE ?)")
                args.extend([match, f"%{f_search}%"])
            else:
                where += " AND c.name LIKE ?"
                args.append(f"%{f_search}%")
        elif fts_available(db):
            # Postgres tsvector (generated column + GIN index)
            where += (" AND (t.search_tsv @@ plainto_tsquery('simple', ?)"
                      " OR c.name LIKE ?)")
            args.extend([f_search, f"%{f_search}%"])
        else:
            where += " AND (t.note LIKE ? OR c.name LIKE ?)"
            args.extend([f"%{f_search}%", f"%{f_search}%"])
    direction = "ASC" if order == "asc" else "DESC"
    order_sql = f"{SORT_COLUMNS[sort]} {direction}, t.id DESC"
    return sort, order, where, args, order_sql


# ---------- CRUD ----------
def create(db, amount_cents, ttype, category_id, date_str, note, user_id=None,
           currency=None, orig_amount=None, split_group=None):
    db.execute(
        "INSERT INTO transactions (amount, type, category_id, date, note,"
        " user_id, currency, orig_amount, split_group) VALUES (?,?,?,?,?,?,?,?,?)",
        (amount_cents, ttype, category_id, date_str, note, user_id,
         currency or base_currency(), orig_amount, split_group),
    )
    db.commit()


def get(db, tx_id):
    row = db.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    if row is None:
        return None
    out = dict(row)
    out["amount"] = from_cents(row["amount"])
    if row["orig_amount"] is not None:
        out["orig_amount"] = from_cents(row["orig_amount"])
    return out


def update(db, tx_id, amount_cents, ttype, category_id, date_str, note,
           user_id=None, currency=None, orig_amount=None):
    db.execute(
        "UPDATE transactions SET amount=?, type=?, category_id=?, date=?,"
        " note=?, user_id=?, currency=?, orig_amount=? WHERE id=?",
        (amount_cents, ttype, category_id, date_str, note, user_id,
         currency or base_currency(), orig_amount, tx_id),
    )
    db.commit()


def delete(db, tx_id):
    """Soft delete a transaction by setting deleted_at."""
    db.execute("UPDATE transactions SET deleted_at = CURRENT_TIMESTAMP WHERE id=?", (tx_id,))
    db.commit()


# ---------- trash (soft-deleted rows) ----------
def deleted_rows(db, limit=200):
    rows = db.execute(
        f"""SELECT t.*, c.name AS category_name, u.username AS owner_name
            FROM transactions t JOIN categories c ON t.category_id=c.id
            LEFT JOIN users u ON u.id=t.user_id
            WHERE t.deleted_at IS NOT NULL
            ORDER BY t.deleted_at DESC, t.id DESC LIMIT ?""", (limit,)).fetchall()
    for r in rows:
        r["amount"] = from_cents(r["amount"])
        if r["orig_amount"] is not None:
            r["orig_amount"] = from_cents(r["orig_amount"])
    return rows


def count_deleted(db):
    return db.execute(
        "SELECT COUNT(*) FROM transactions WHERE deleted_at IS NOT NULL").fetchone()[0]


def deleted_page(db, per_page, offset):
    rows = db.execute(
        f"""SELECT t.*, c.name AS category_name, u.username AS owner_name
            FROM transactions t JOIN categories c ON t.category_id=c.id
            LEFT JOIN users u ON u.id=t.user_id
            WHERE t.deleted_at IS NOT NULL
            ORDER BY t.deleted_at DESC, t.id DESC LIMIT ? OFFSET ?""",
        (per_page, offset)).fetchall()
    for r in rows:
        r["amount"] = from_cents(r["amount"])
        if r["orig_amount"] is not None:
            r["orig_amount"] = from_cents(r["orig_amount"])
    return rows


def restore(db, tx_id):
    """Undo a soft delete. Returns True when a row was restored."""
    cur = db.execute(
        "UPDATE transactions SET deleted_at=NULL WHERE id=? AND deleted_at IS NOT NULL",
        (tx_id,))
    db.commit()
    return (cur.rowcount or 0) > 0


def purge(db, tx_id):
    """Permanently delete a soft-deleted row. Returns True when removed."""
    cur = db.execute(
        "DELETE FROM transactions WHERE id=? AND deleted_at IS NOT NULL", (tx_id,))
    db.commit()
    return (cur.rowcount or 0) > 0


# ---------- split groups ----------
def by_group(db, group):
    """All live rows sharing a split group (amounts in rupees)."""
    rows = db.execute(
        f"""{LIST_SQL} WHERE t.split_group=? AND t.deleted_at IS NULL
            ORDER BY t.id""", (group,)).fetchall()
    for r in rows:
        r["amount"] = from_cents(r["amount"])
        if r["orig_amount"] is not None:
            r["orig_amount"] = from_cents(r["orig_amount"])
    return rows


def delete_group(db, group):
    """Soft delete every live row of a split group. Returns count."""
    cur = db.execute(
        "UPDATE transactions SET deleted_at=CURRENT_TIMESTAMP"
        " WHERE split_group=? AND deleted_at IS NULL", (group,))
    db.commit()
    return cur.rowcount or 0


def duplicate(db, tx_id):
    """Copy a transaction with today's date (same owner). Returns the source row or None."""
    tx = db.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    if not tx:
        return None
    db.execute(
        "INSERT INTO transactions (amount,type,category_id,date,note,user_id,"
        "currency,orig_amount) VALUES (?,?,?,?,?,?,?,?)",
        (tx["amount"], tx["type"], tx["category_id"], date.today().isoformat(),
         tx["note"] or "", tx["user_id"], tx["currency"] or base_currency(),
         tx["orig_amount"]),
    )
    db.commit()
    return dict(tx)


# ---------- bulk ----------
def bulk_soft_delete(db, ids):
    """Soft delete every id (existing, not already deleted). Returns count."""
    n = 0
    for tx_id in ids:
        cur = db.execute(
            "UPDATE transactions SET deleted_at=CURRENT_TIMESTAMP"
            " WHERE id=? AND deleted_at IS NULL", (tx_id,))
        n += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
    db.commit()
    return n


def bulk_set_category(db, ids, category_id):
    """Re-categorize transactions whose type matches the category.

    Returns (updated, skipped) — mismatches (e.g. expense category for an
    income row) are left untouched so accounting stays consistent.
    """
    cat = category_models.get(db, category_id)
    if not cat:
        return 0, len(ids)
    updated = skipped = 0
    for tx_id in ids:
        row = db.execute(
            "SELECT type FROM transactions WHERE id=? AND deleted_at IS NULL",
            (tx_id,)).fetchone()
        if not row:
            skipped += 1
            continue
        if row["type"] != cat["type"]:
            skipped += 1
            continue
        db.execute("UPDATE transactions SET category_id=? WHERE id=?",
                   (category_id, tx_id))
        updated += 1
    db.commit()
    return updated, skipped


# ---------- list / aggregates ----------
def count_filtered(db, where, args):
    return db.execute(
        f"SELECT COUNT(*) FROM transactions t JOIN categories c ON t.category_id=c.id {where}",
        args,
    ).fetchone()[0]


def sums_filtered(db, where, args):
    row = db.execute(
        f"""SELECT SUM(CASE WHEN t.type='income' THEN t.amount ELSE 0 END) AS inc,
                    SUM(CASE WHEN t.type='expense' AND c.is_savings=0 THEN t.amount ELSE 0 END) AS exp,
                    SUM(CASE WHEN t.type='expense' AND c.is_savings=1 THEN t.amount ELSE 0 END) AS svd
            FROM transactions t JOIN categories c ON t.category_id=c.id {where}""",
        args,
    ).fetchone()
    return from_cents(row["inc"]), from_cents(row["exp"]), from_cents(row["svd"])


def list_filtered(db, where, args, order_sql, per_page, offset):
    rows = db.execute(
        f"{LIST_SQL} {where} ORDER BY {order_sql} LIMIT ? OFFSET ?",
        args + [per_page, offset],
    ).fetchall()
    for r in rows:
        r["amount"] = from_cents(r["amount"])
        if r["orig_amount"] is not None:
            r["orig_amount"] = from_cents(r["orig_amount"])
    return rows


def export_rows(db, where, args, order_sql):
    return db.execute(
        f"""SELECT t.id, t.date, t.type, c.name AS category, t.amount, t.note,
                    t.currency, t.orig_amount, u.username AS owner
            FROM transactions t JOIN categories c ON t.category_id=c.id
            LEFT JOIN users u ON u.id=t.user_id
            {where} ORDER BY {order_sql}""",
        args,
    ).fetchall()


def import_csv(db, text, user_id=None):
    """Import CSV text — required columns date,type,category,amount; optional note,owner,currency.

    Unknown categories are auto-created. The optional owner column names the
    user the expense is managed for; unknown or blank owners fall back to
    user_id (the importer). Optional currency: when set (and not the base
    currency) the amount is interpreted in that currency and converted to
    base cents at the configured static rate. Rows commit individually so a
    bad row never rolls back good ones. Returns (inserted, skipped).
    """
    reader = csv.DictReader(io.StringIO(text))
    cats = {r["name"].lower(): r for r in db.execute("SELECT * FROM categories").fetchall()}
    users = {r["username"].lower(): r["id"] for r in
             db.execute("SELECT id, username FROM users").fetchall()}
    inserted, skipped = 0, 0
    for i, row in enumerate(reader, start=1):
        if i > IMPORT_ROW_LIMIT:
            break
        try:
            date_str = (row.get("date") or "").strip()
            ttype = (row.get("type") or "expense").strip().lower()
            cat_name = (row.get("category") or "").strip()
            amount_raw = (row.get("amount") or "").strip()
            note = (row.get("note") or "").strip()[:200]
            datetime.strptime(date_str, "%Y-%m-%d")
            code = (row.get("currency") or "").strip().upper() or base_currency()
            if code != base_currency() and code not in current_app.config.get("CURRENCY_RATES", {}):
                raise ValueError
            orig = to_cents(amount_raw)
            amount = int(round(orig * rate_to_base(code)))
            if amount <= 0 or ttype not in ("income", "expense") or not cat_name:
                raise ValueError
            key = cat_name.lower()
            if key not in cats:
                category_models.insert(db, cat_name, ttype)
                cats[key] = category_models.get_by_name(db, cat_name)
            cat = cats[key]
            if cat["type"] != ttype:
                raise ValueError
            owner_id = users.get((row.get("owner") or "").strip().lower(), user_id)
            db.execute(
                "INSERT INTO transactions (amount,type,category_id,date,note,"
                "user_id,currency,orig_amount) VALUES (?,?,?,?,?,?,?,?)",
                (amount, ttype, cat["id"], date_str, note, owner_id,
                 code, orig if code != base_currency() else None))
            db.commit()
            inserted += 1
        except (ValueError, KeyError) + DB_ERRORS:
            db.rollback()  # required to keep a Postgres connection usable
            skipped += 1
    return inserted, skipped


def new_split_group():
    """Shared id linking the rows of one split transaction."""
    return uuid.uuid4().hex[:12]
