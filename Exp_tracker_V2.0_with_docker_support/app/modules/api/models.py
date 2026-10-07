"""API data access (Model layer)."""
from datetime import date

from ...helpers import month_bounds, parse_month

CATEGORY_SQL = """SELECT c.name, c.type, SUM(t.amount) AS total FROM transactions t
                  JOIN categories c ON t.category_id=c.id
                  WHERE {clause} GROUP BY c.id ORDER BY total DESC"""

TOTAL_SQL = """SELECT SUM(CASE WHEN type='income' THEN amount ELSE 0 END) AS income,
                      SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) AS expense
               FROM transactions t WHERE {clause}"""


def _resolve_period(month, year):
    """Return (label, clause, args) for ?month=YYYY-MM, ?year=YYYY, or current month."""
    if month:
        y, m = parse_month(month)
        s, e = month_bounds(y, m)
        return f"{y}-{m:02d}", "t.date>=? AND t.date<?", (s, e)
    if year and year.isdigit():
        return year, "substr(t.date,1,4)=?", (year,)
    today = date.today()
    s, e = month_bounds(today.year, today.month)
    return f"{today.year}-{today.month:02d}", "t.date>=? AND t.date<?", (s, e)


def summary(db, month, year):
    """Aggregate income/expense and per-category totals for a month or year."""
    label, clause, args = _resolve_period(month, year)
    rows = db.execute(CATEGORY_SQL.format(clause=clause), args).fetchall()
    tot = db.execute(TOTAL_SQL.format(clause=clause), args).fetchone()
    inc, exp = (tot["income"] or 0), (tot["expense"] or 0)
    return {
        "period": label,
        "income": inc,
        "expense": exp,
        "savings": inc - exp,
        "by_category": [dict(r) for r in rows],
    }


def latest(db, limit, f_type):
    """Most recent transactions, optionally filtered by type."""
    where, args = "WHERE 1=1", []
    if f_type in ("income", "expense"):
        where += " AND t.type=?"
        args.append(f_type)
    rows = db.execute(
        f"""SELECT t.id, t.date, t.type, c.name AS category, t.amount, t.note,
                    u.username AS owner
            FROM transactions t JOIN categories c ON t.category_id=c.id
            LEFT JOIN users u ON u.id=t.user_id
            {where} ORDER BY t.date DESC, t.id DESC LIMIT ?""",
        args + [limit]).fetchall()
    return [dict(r) for r in rows]
