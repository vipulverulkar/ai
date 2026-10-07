"""Dashboard data access (Model layer)."""
from datetime import date

from ...helpers import last_n_months, month_bounds


def _scalar(db, query, args=()):
    row = db.execute(query, args).fetchone()
    return row[0] if row and row[0] is not None else 0


def totals(db, today):
    """Income/expense rollups for today, this month and all time."""
    today_str = today.isoformat()
    m_start, m_end = month_bounds(today.year, today.month)
    out = {
        "today_income": _scalar(db, "SELECT SUM(amount) FROM transactions WHERE type='income' AND date=?", (today_str,)),
        "today_expense": _scalar(db, "SELECT SUM(amount) FROM transactions WHERE type='expense' AND date=?", (today_str,)),
        "month_income": _scalar(db, "SELECT SUM(amount) FROM transactions WHERE type='income' AND date>=? AND date<?", (m_start, m_end)),
        "month_expense": _scalar(db, "SELECT SUM(amount) FROM transactions WHERE type='expense' AND date>=? AND date<?", (m_start, m_end)),
        "total_income": _scalar(db, "SELECT SUM(amount) FROM transactions WHERE type='income'"),
        "total_expense": _scalar(db, "SELECT SUM(amount) FROM transactions WHERE type='expense'"),
    }
    out["balance"] = out["total_income"] - out["total_expense"]
    out["savings_rate"] = (round((out["month_income"] - out["month_expense"]) / out["month_income"] * 100, 1)
                           if out["month_income"] else 0)
    return out


def recent(db, limit=8):
    return db.execute(
        """SELECT t.*, c.name AS category_name FROM transactions t
           JOIN categories c ON t.category_id=c.id
           ORDER BY t.date DESC, t.id DESC LIMIT ?""",
        (limit,),
    ).fetchall()


def trend(db, n=6):
    """Income/expense/savings per month for the last n months."""
    out = []
    for yy, mm in last_n_months(n):
        s, e = month_bounds(yy, mm)
        inc = _scalar(db, "SELECT SUM(amount) FROM transactions WHERE type='income' AND date>=? AND date<?", (s, e))
        exp = _scalar(db, "SELECT SUM(amount) FROM transactions WHERE type='expense' AND date>=? AND date<?", (s, e))
        out.append({"month": f"{yy}-{mm:02d}", "label": date(yy, mm, 1).strftime("%b"),
                    "income": inc or 0, "expense": exp or 0, "savings": (inc or 0) - (exp or 0)})
    return out


def top_categories(db, year, month, limit=5):
    m_start, m_end = month_bounds(year, month)
    return db.execute(
        """SELECT c.name, SUM(t.amount) AS total FROM transactions t
           JOIN categories c ON t.category_id=c.id
           WHERE t.type='expense' AND t.date>=? AND t.date<? GROUP BY c.id
           ORDER BY total DESC LIMIT ?""",
        (m_start, m_end, limit),
    ).fetchall()
