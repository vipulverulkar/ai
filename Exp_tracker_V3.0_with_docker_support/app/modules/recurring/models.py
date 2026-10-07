"""Recurring transaction data access + schedule engine (Model layer)."""
import calendar
from datetime import date, datetime, timedelta

from ...db import DB_ERRORS
from ...helpers import to_cents, from_cents

FREQUENCIES = ("daily", "weekly", "monthly", "yearly")
MAX_CATCHUP_ITERATIONS = 366  # safety cap when running due items


def _advance(d, frequency):
    """Next occurrence date for a given frequency."""
    if frequency == "daily":
        return d + timedelta(days=1)
    if frequency == "weekly":
        return d + timedelta(weeks=1)
    if frequency == "monthly":
        yy, mm = (d.year + (d.month == 12), 1) if d.month == 12 else (d.year, d.month + 1)
        return d.replace(year=yy, month=mm, day=min(d.day, calendar.monthrange(yy, mm)[1]))
    # yearly
    yy = d.year + 1
    return d.replace(year=yy, day=min(d.day, calendar.monthrange(yy, d.month)[1]))


def all(db):
    rows = db.execute(
        """SELECT r.*, c.name AS category_name, u.username AS owner_name
           FROM recurrences r
           LEFT JOIN categories c ON c.id=r.category_id
           LEFT JOIN users u ON u.id=r.user_id
           ORDER BY r.next_run_date, r.id""").fetchall()
    return [_row_out(r) for r in rows]


def get(db, rec_id):
    r = db.execute("SELECT * FROM recurrences WHERE id=?", (rec_id,)).fetchone()
    return _row_out(r) if r else None


def _row_out(r):
    out = dict(r)
    out["amount"] = from_cents(r["amount"])
    return out


def create(db, amount_cents, ttype, category_id, note, frequency, next_run,
           user_id=None, currency=None, orig_amount=None):
    from ..transactions import models as tx_models
    db.execute(
        """INSERT INTO recurrences (user_id, amount, type, category_id, note,
           currency, orig_amount, frequency, next_run_date)
           VALUES (?,?,?,?,?,?,?,?,?)""",
        (user_id, amount_cents, ttype, category_id, note,
         currency or tx_models.base_currency(), orig_amount,
         frequency, next_run))
    db.commit()


def set_active(db, rec_id, active):
    db.execute("UPDATE recurrences SET active=? WHERE id=?", (1 if active else 0, rec_id))
    db.commit()


def delete(db, rec_id):
    db.execute("DELETE FROM recurrences WHERE id=?", (rec_id,))
    db.commit()


def validate(db, amount_raw, ttype, category_id, frequency, next_run_raw):
    """Return (amount_cents, cat_row, frequency, next_run, error_msg)."""
    try:
        amount = to_cents(amount_raw)
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return None, None, None, None, "Amount must be a positive number."
    if ttype not in ("income", "expense"):
        return None, None, None, None, "Invalid transaction type."
    try:
        cat = db.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    except (ValueError,) + DB_ERRORS:
        cat = None
    if not cat:
        return None, None, None, None, "Please select a valid category."
    if cat["type"] != ttype:
        return None, None, None, None, f"Category '{cat['name']}' is for {cat['type']}, not {ttype}."
    if frequency not in FREQUENCIES:
        return None, None, None, None, "Frequency must be daily, weekly, monthly or yearly."
    try:
        next_run = datetime.strptime(next_run_raw, "%Y-%m-%d").date().isoformat()
    except (ValueError, TypeError):
        return None, None, None, None, "Next run date is invalid (use YYYY-MM-DD)."
    return amount, cat, frequency, next_run, None


def due_count(db, today):
    return db.execute(
        "SELECT COUNT(*) FROM recurrences WHERE active=1 AND next_run_date<=?",
        (today.isoformat(),)).fetchone()[0]


def run_due(db, today):
    """Generate transactions for every due recurrence (idempotent per date).

    Each due item produces one transaction dated on its next_run_date, the
    schedule advances, and the loop repeats until the schedule passes today
    (capped for safety). Returns the number of transactions created.
    """
    rows = db.execute(
        "SELECT * FROM recurrences WHERE active=1 AND next_run_date<=?",
        (today.isoformat(),)).fetchall()
    created = 0
    today_iso = today.isoformat()
    for r in rows:
        iterations = 0
        while iterations < MAX_CATCHUP_ITERATIONS:
            run_on = r["next_run_date"]
            if run_on > today_iso or not r["category_id"]:
                break
            db.execute(
                """INSERT INTO transactions (amount, type, category_id, date, note,
                   user_id) VALUES (?,?,?,?,?,?)""",
                (r["amount"], r["type"], r["category_id"], run_on,
                 r["note"] or "", r["user_id"]))
            db.execute(
                "UPDATE recurrences SET next_run_date=?, last_run_at=? WHERE id=?",
                (_advance(datetime.strptime(run_on, "%Y-%m-%d").date(),
                          r["frequency"]).isoformat(),
                 today_iso, r["id"]))
            created += 1
            iterations += 1
            # refresh the row so the while-loop condition uses the new date
            r = db.execute("SELECT * FROM recurrences WHERE id=?", (r["id"],)).fetchone()
        # skip runaway schedules (e.g. daily recurrence abandoned for years)
        if iterations >= MAX_CATCHUP_ITERATIONS and r["next_run_date"] <= today_iso:
            db.execute("UPDATE recurrences SET active=0 WHERE id=?", (r["id"],))
    if created:
        db.commit()
    return created
