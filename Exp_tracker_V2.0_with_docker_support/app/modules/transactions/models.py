"""Transaction data access, validation and CSV import (Model layer)."""
import csv
import io
from datetime import date, datetime

from ...db import DB_ERRORS
from ...helpers import month_bounds, parse_month
from ..categories import models as category_models

SORT_COLUMNS = {"date": "t.date", "amount": "t.amount", "category": "c.name"}
PER_PAGE_CHOICES = (10, 25, 50, 100)
IMPORT_ROW_LIMIT = 2000

LIST_SQL = """SELECT t.*, c.name AS category_name, u.username AS owner_name
              FROM transactions t JOIN categories c ON t.category_id=c.id
              LEFT JOIN users u ON u.id=t.user_id"""


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


# ---------- validation ----------
def validate(db, amount_raw, ttype, category_id, date_str, note):
    """Return (amount, cat_row, date_str, note, error_msg)."""
    try:
        amount = round(float(str(amount_raw).replace(",", "").strip()), 2)
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


# ---------- filter query builder ----------
def filter_query(f_type, f_category, f_owner, f_month, f_search, sort, order):
    """Build WHERE/ORDER BY clauses from parsed filter params."""
    if sort not in SORT_COLUMNS:
        sort = "date"
    if order not in ("asc", "desc"):
        order = "desc"
    where = "WHERE 1=1"
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
        where += " AND (t.note LIKE ? OR c.name LIKE ?)"
        args.extend([f"%{f_search}%", f"%{f_search}%"])
    direction = "ASC" if order == "asc" else "DESC"
    order_sql = f"{SORT_COLUMNS[sort]} {direction}, t.id DESC"
    return sort, order, where, args, order_sql


# ---------- CRUD ----------
def create(db, amount, ttype, category_id, date_str, note, user_id=None):
    db.execute(
        "INSERT INTO transactions (amount, type, category_id, date, note,"
        " user_id) VALUES (?,?,?,?,?,?)",
        (amount, ttype, category_id, date_str, note, user_id),
    )
    db.commit()


def get(db, tx_id):
    return db.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()


def update(db, tx_id, amount, ttype, category_id, date_str, note, user_id=None):
    db.execute(
        "UPDATE transactions SET amount=?, type=?, category_id=?, date=?,"
        " note=?, user_id=? WHERE id=?",
        (amount, ttype, category_id, date_str, note, user_id, tx_id),
    )
    db.commit()


def delete(db, tx_id):
    db.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
    db.commit()


def duplicate(db, tx_id):
    """Copy a transaction with today's date (same owner). Returns the source row or None."""
    tx = get(db, tx_id)
    if not tx:
        return None
    db.execute(
        "INSERT INTO transactions (amount,type,category_id,date,note,user_id)"
        " VALUES (?,?,?,?,?,?)",
        (tx["amount"], tx["type"], tx["category_id"], date.today().isoformat(),
         tx["note"] or "", tx["user_id"]),
    )
    db.commit()
    return tx


# ---------- list / aggregates ----------
def count_filtered(db, where, args):
    return db.execute(
        f"SELECT COUNT(*) FROM transactions t JOIN categories c ON t.category_id=c.id {where}",
        args,
    ).fetchone()[0]


def sums_filtered(db, where, args):
    row = db.execute(
        f"""SELECT SUM(CASE WHEN t.type='income' THEN t.amount ELSE 0 END) AS inc,
                    SUM(CASE WHEN t.type='expense' THEN t.amount ELSE 0 END) AS exp
            FROM transactions t JOIN categories c ON t.category_id=c.id {where}""",
        args,
    ).fetchone()
    return (row["inc"] or 0), (row["exp"] or 0)


def list_filtered(db, where, args, order_sql, per_page, offset):
    return db.execute(
        f"{LIST_SQL} {where} ORDER BY {order_sql} LIMIT ? OFFSET ?",
        args + [per_page, offset],
    ).fetchall()


def export_rows(db, where, args, order_sql):
    return db.execute(
        f"""SELECT t.id, t.date, t.type, c.name AS category, t.amount, t.note,
                    u.username AS owner
            FROM transactions t JOIN categories c ON t.category_id=c.id
            LEFT JOIN users u ON u.id=t.user_id
            {where} ORDER BY {order_sql}""",
        args,
    ).fetchall()


def import_csv(db, text, user_id=None):
    """Import CSV text (date,type,category,amount,note[,owner]).

    Unknown categories are auto-created. The optional owner column names the
    user the expense is managed for; unknown or blank owners fall back to
    user_id (the importer). Rows commit individually so a bad row never rolls
    back good ones. Returns (inserted, skipped).
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
            amount = round(float(amount_raw.replace(",", "")), 2)
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
                "INSERT INTO transactions (amount,type,category_id,date,note,user_id)"
                " VALUES (?,?,?,?,?,?)",
                (amount, ttype, cat["id"], date_str, note, owner_id))
            db.commit()
            inserted += 1
        except (ValueError, KeyError) + DB_ERRORS:
            db.rollback()  # required to keep a Postgres connection usable
            skipped += 1
    return inserted, skipped
