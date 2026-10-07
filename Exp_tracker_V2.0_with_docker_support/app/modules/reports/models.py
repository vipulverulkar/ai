"""Report data access (Model layer)."""
from datetime import date

from ...helpers import month_bounds


def daily(db, year, month):
    """One row per day for the given month."""
    s, e = month_bounds(year, month)
    rows = db.execute(
        """SELECT date, SUM(CASE WHEN type='income' THEN amount ELSE 0 END) AS income,
                  SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) AS expense
           FROM transactions WHERE date>=? AND date<? GROUP BY date ORDER BY date""",
        (s, e),
    ).fetchall()
    return [{"date": r["date"], "income": r["income"] or 0, "expense": r["expense"] or 0,
             "savings": (r["income"] or 0) - (r["expense"] or 0)} for r in rows]


def monthly(db, year):
    """One row per month for the given year (all 12 months, zero-filled)."""
    rows = db.execute(
        """
        SELECT substr(date,1,7) AS month,
               SUM(CASE WHEN type='income' THEN amount ELSE 0 END) AS income,
               SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) AS expense
        FROM transactions WHERE substr(date,1,4)=? GROUP BY month ORDER BY month
        """,
        (str(year),),
    ).fetchall()
    data = {r["month"]: dict(r) for r in rows}
    out = []
    for mm in range(1, 13):
        key = f"{year}-{mm:02d}"
        d = data.get(key, {"income": 0, "expense": 0})
        inc, exp = d["income"] or 0, d["expense"] or 0
        out.append({"month": key, "income": inc, "expense": exp, "savings": inc - exp})
    return out


def category_totals_for_month(db, year, month):
    s, e = month_bounds(year, month)
    return [dict(c) for c in db.execute(
        """SELECT c.name, c.type, SUM(t.amount) AS total
           FROM transactions t JOIN categories c ON t.category_id=c.id
           WHERE t.date>=? AND t.date<? GROUP BY c.id ORDER BY total DESC""",
        (s, e)).fetchall()]


def category_totals_for_year(db, year):
    return [dict(c) for c in db.execute(
        """SELECT c.name, c.type, SUM(t.amount) AS total
           FROM transactions t JOIN categories c ON t.category_id=c.id
           WHERE substr(t.date,1,4)=? GROUP BY c.id ORDER BY total DESC""",
        (str(year),)).fetchall()]


def available_years(db):
    """Years present in data, with the current year always included."""
    years = [r[0] for r in db.execute(
        "SELECT DISTINCT substr(date,1,4) AS y FROM transactions ORDER BY y DESC").fetchall()]
    current = str(date.today().year)
    if current not in years:
        years = [current] + years
    return years
