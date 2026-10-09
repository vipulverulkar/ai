"""Recurring transaction data access + schedule engine (Model layer)."""
import calendar
from datetime import date, datetime, timedelta

from ...db import DB_ERRORS
from ...helpers import to_cents, from_cents

FREQUENCIES = ("daily", "weekly", "monthly", "yearly")
MAX_CATCHUP_ITERATIONS = 366  # safety cap when running due items


def _advance(d, frequency, anchor=None):
    """Next occurrence date for a given frequency.

    Monthly/yearly schedules keep the original day-of-month (`anchor`)
    so Jan 31 -> Feb 28 -> Mar 31 instead of drifting to the 28th forever.
    """
    if frequency == "daily":
        return d + timedelta(days=1)
    if frequency == "weekly":
        return d + timedelta(weeks=1)
    if frequency == "monthly":
        yy, mm = (d.year + (d.month == 12), 1) if d.month == 12 else (d.year, d.month + 1)
        day = min(anchor or d.day, calendar.monthrange(yy, mm)[1])
        return d.replace(year=yy, month=mm, day=day)
    # yearly
    yy = d.year + 1
    day = min(anchor or d.day, calendar.monthrange(yy, d.month)[1])
    return d.replace(year=yy, day=day)


def all(db):
    rows = db.execute(
        """SELECT r.*, c.name AS category_name, u.username AS owner_name
           FROM recurring_transactions r
           LEFT JOIN categories c ON c.id=r.category_id
           LEFT JOIN users u ON u.id=r.user_id
           ORDER BY r.next_run_date, r.id""").fetchall()
    return [_row_out(r) for r in rows]


def count(db):
    return db.execute("SELECT COUNT(*) FROM recurring_transactions").fetchone()[0]


def page(db, per_page, offset):
    rows = db.execute(
        """SELECT r.*, c.name AS category_name, u.username AS owner_name
           FROM recurring_transactions r
           LEFT JOIN categories c ON c.id=r.category_id
           LEFT JOIN users u ON u.id=r.user_id
           ORDER BY r.next_run_date, r.id LIMIT ? OFFSET ?""",
        (per_page, offset)).fetchall()
    return [_row_out(r) for r in rows]


def get(db, rec_id):
    r = db.execute("SELECT * FROM recurring_transactions WHERE id=?", (rec_id,)).fetchone()
    return _row_out(r) if r else None


def _row_out(r):
    out = dict(r)
    out["amount"] = from_cents(r["amount"])
    return out


def create(db, amount_cents, ttype, category_id, note, frequency, start,
           user_id=None, currency=None, orig_amount=None, end_date=None):
    from ..transactions import models as tx_models
    try:
        anchor = int(start[8:10])
    except (ValueError, TypeError, IndexError):
        anchor = None
    db.execute(
        """INSERT INTO recurring_transactions (user_id, amount, type, category_id, note,
           currency, orig_amount, frequency, next_run_date, start_date, end_date,
           anchor_day)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        (user_id, amount_cents, ttype, category_id, note,
         currency or tx_models.base_currency(), orig_amount,
         frequency, start, start, end_date, anchor))
    db.commit()


def is_ended(row):
    """True when the schedule ran past its end date (no more runs due)."""
    try:
        end = row["end_date"] or None
        nxt = row["next_run_date"] or None
    except (KeyError, IndexError, TypeError):
        return False
    return bool(end and nxt) and nxt > end


def set_active(db, rec_id, active):
    db.execute("UPDATE recurring_transactions SET active=? WHERE id=?", (1 if active else 0, rec_id))
    db.commit()


def delete(db, rec_id):
    db.execute("DELETE FROM recurring_transactions WHERE id=?", (rec_id,))
    db.commit()


def validate(db, amount_raw, ttype, category_id, frequency, start_raw,
               end_raw=None):
    """Return (amount_cents, cat_row, frequency, start, end, error_msg).

    start is required (YYYY-MM-DD); end is optional but must not precede
    the start when given.
    """
    try:
        amount = to_cents(amount_raw)
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return None, None, None, None, None, "Amount must be a positive number."
    if ttype not in ("income", "expense"):
        return None, None, None, None, None, "Invalid transaction type."
    try:
        cat = db.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    except (ValueError,) + DB_ERRORS:
        cat = None
    if not cat:
        return None, None, None, None, None, "Please select a valid category."
    if cat["type"] != ttype:
        return None, None, None, None, None, f"Category '{cat['name']}' is for {cat['type']}, not {ttype}."
    if frequency not in FREQUENCIES:
        return None, None, None, None, None, "Frequency must be daily, weekly, monthly or yearly."
    try:
        start = datetime.strptime((start_raw or "").strip(), "%Y-%m-%d").date().isoformat()
    except (ValueError, TypeError, AttributeError):
        return None, None, None, None, None, "Start date is invalid (use YYYY-MM-DD)."
    end = None
    if (end_raw or "").strip():
        try:
            end = datetime.strptime(end_raw.strip(), "%Y-%m-%d").date().isoformat()
        except (ValueError, TypeError, AttributeError):
            return None, None, None, None, None, "End date is invalid (use YYYY-MM-DD)."
        if end < start:
            return None, None, None, None, None, "End date must be on or after the start date."
    return amount, cat, frequency, start, end, None


def due_count(db, today):
    return db.execute(
        "SELECT COUNT(*) FROM recurring_transactions WHERE active=1 AND next_run_date<=?"
        " AND (end_date IS NULL OR next_run_date <= end_date)",
        (today.isoformat(),)).fetchone()[0]


def _row_anchor(r):
    try:
        anchor = r["anchor_day"]
    except (KeyError, IndexError):
        anchor = None
    if anchor:
        return int(anchor)
    try:
        return int((r["start_date"] or r["next_run_date"])[8:10])
    except (ValueError, TypeError, IndexError, KeyError):
        return None


def run_due(db, today):
    """Generate transactions for every due recurrence (idempotent per date).

    Each due item produces one transaction dated on its next_run_date, the
    schedule advances (keeping its day-of-month anchor), and the loop
    repeats until the schedule passes today or its end date (capped for
    safety). Schedules that run past their end date are auto-finished.
    Returns (created, capped): transactions created, and schedules
    auto-deactivated after hitting the catch-up cap (caller should warn —
    their oldest backlog was generated but the tail was dropped).
    """
    capped = 0
    if getattr(db, "engine", "sqlite") == "sqlite":
        # Serialize concurrent dashboard loads so two readers can't
        # generate the same dated rows (single commit at the end).
        db.execute("BEGIN IMMEDIATE")
    db.execute("UPDATE recurring_transactions SET active=0 WHERE active=1"
               " AND end_date IS NOT NULL AND next_run_date > end_date")
    if getattr(db, "engine", "sqlite") == "pg":
        rows = db.execute(
            "SELECT * FROM recurring_transactions WHERE active=1 AND next_run_date<=?"
            " AND (end_date IS NULL OR next_run_date <= end_date)"
            " FOR UPDATE",
            (today.isoformat(),)).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM recurring_transactions WHERE active=1 AND next_run_date<=?"
            " AND (end_date IS NULL OR next_run_date <= end_date)",
            (today.isoformat(),)).fetchall()
    created = 0
    today_iso = today.isoformat()
    for r in rows:
        iterations = 0
        anchor = _row_anchor(r)
        while iterations < MAX_CATCHUP_ITERATIONS:
            run_on = r["next_run_date"]
            end = r["end_date"] if "end_date" in r.keys() else None
            if run_on > today_iso or not r["category_id"]:
                break
            if end and run_on > end:
                break
            db.execute(
                """INSERT INTO transactions (amount, type, category_id, date, note,
                   user_id, currency, orig_amount) VALUES (?,?,?,?,?,?,?,?)""",
                (r["amount"], r["type"], r["category_id"], run_on,
                 r["note"] or "", r["user_id"],
                 r["currency"] if "currency" in r.keys() and r["currency"] else "INR",
                 r["orig_amount"] if "orig_amount" in r.keys() else None))
            db.execute(
                "UPDATE recurring_transactions SET next_run_date=?, last_run_at=? WHERE id=?",
                (_advance(datetime.strptime(run_on, "%Y-%m-%d").date(),
                          r["frequency"], anchor).isoformat(),
                 today_iso, r["id"]))
            created += 1
            iterations += 1
            # refresh the row so the while-loop condition uses the new date
            r = db.execute("SELECT * FROM recurring_transactions WHERE id=?", (r["id"],)).fetchone()
        # skip runaway schedules (e.g. daily recurrence abandoned for years)
        if iterations >= MAX_CATCHUP_ITERATIONS and r["next_run_date"] <= today_iso:
            db.execute("UPDATE recurring_transactions SET active=0 WHERE id=?", (r["id"],))
            capped += 1
        r = db.execute("SELECT * FROM recurring_transactions WHERE id=?", (r["id"],)).fetchone()
        if r["end_date"] and r["next_run_date"] > r["end_date"]:
            db.execute("UPDATE recurring_transactions SET active=0 WHERE id=?", (r["id"],))
    db.commit()
    return created, capped
