"""Dashboard data access (Model layer). Amounts leave as rupees (floats)."""
from datetime import date

from ...helpers import from_cents, last_n_months, month_bounds


def _scalar(db, query, args=()):
    row = db.execute(query, args).fetchone()
    return row[0] if row and row[0] is not None else 0


def _spending(db, extra="", args=()):
    """Sum of true spending (savings buckets excluded)."""
    return _scalar(db,
        "SELECT SUM(t.amount) FROM transactions t JOIN categories c ON t.category_id=c.id"
        f" WHERE t.type='expense' AND c.is_savings=0 AND t.deleted_at IS NULL {extra}", args)


def _saved(db, extra="", args=()):
    """Sum parked in savings buckets."""
    return _scalar(db,
        "SELECT SUM(t.amount) FROM transactions t JOIN categories c ON t.category_id=c.id"
        f" WHERE t.type='expense' AND c.is_savings=1 AND t.deleted_at IS NULL {extra}", args)


def totals(db, today):
    """Income/spending/saved rollups for today, this month and all time (rupees)."""
    today_str = today.isoformat()
    m_start, m_end = month_bounds(today.year, today.month)
    out = {
        "today_income": from_cents(_scalar(db, "SELECT SUM(amount) FROM transactions WHERE type='income' AND deleted_at IS NULL AND date=?", (today_str,))),
        "today_expense": from_cents(_spending(db, "AND t.date=?", (today_str,))),
        "today_saved": from_cents(_saved(db, "AND t.date=?", (today_str,))),
        "month_income": from_cents(_scalar(db, "SELECT SUM(amount) FROM transactions WHERE type='income' AND deleted_at IS NULL AND date>=? AND date<?", (m_start, m_end))),
        "month_expense": from_cents(_spending(db, "AND t.date>=? AND t.date<?", (m_start, m_end))),
        "month_saved": from_cents(_saved(db, "AND t.date>=? AND t.date<?", (m_start, m_end))),
        "total_income": from_cents(_scalar(db, "SELECT SUM(amount) FROM transactions WHERE type='income' AND deleted_at IS NULL")),
        "total_expense": from_cents(_spending(db)),
        "total_saved": from_cents(_saved(db)),
    }
    out["balance"] = out["total_income"] - out["total_expense"]
    out["savings_rate"] = (round((out["month_income"] - out["month_expense"]) / out["month_income"] * 100, 1)
                           if out["month_income"] else 0)
    return out


def recent(db, limit=8):
    rows = db.execute(
        """SELECT t.*, c.name AS category_name FROM transactions t
           JOIN categories c ON t.category_id=c.id
           WHERE t.deleted_at IS NULL
           ORDER BY t.date DESC, t.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()
    for r in rows:
        r["amount"] = from_cents(r["amount"])
    return rows


def trend(db, n=6):
    """Income/spending/saved per month for the last n months (rupees)."""
    out = []
    for yy, mm in last_n_months(n):
        s, e = month_bounds(yy, mm)
        inc = from_cents(_scalar(db, "SELECT SUM(amount) FROM transactions WHERE type='income' AND deleted_at IS NULL AND date>=? AND date<?", (s, e)))
        exp = from_cents(_spending(db, "AND t.date>=? AND t.date<?", (s, e)))
        svd = from_cents(_saved(db, "AND t.date>=? AND t.date<?", (s, e)))
        out.append({"month": f"{yy}-{mm:02d}", "label": date(yy, mm, 1).strftime("%b"),
                    "income": inc, "expense": exp, "saved": svd, "savings": inc - exp})
    return out


def top_categories(db, year, month, limit=5):
    m_start, m_end = month_bounds(year, month)
    rows = db.execute(
        """SELECT c.name, SUM(t.amount) AS total FROM transactions t
           JOIN categories c ON t.category_id=c.id
           WHERE t.type='expense' AND c.is_savings=0 AND t.deleted_at IS NULL AND t.date>=? AND t.date<?
           GROUP BY c.id ORDER BY total DESC LIMIT ?""",
        (m_start, m_end, limit),
    ).fetchall()
    for r in rows:
        r["total"] = from_cents(r["total"])
    return rows
