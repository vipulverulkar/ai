"""Report data access (Model layer). Amounts leave as rupees (floats)."""
from datetime import date

from ...helpers import from_cents, month_bounds


def daily(db, year, month):
    """One row per day for the given month (spending excludes savings buckets)."""
    s, e = month_bounds(year, month)
    rows = db.execute(
        """SELECT t.date,
                  SUM(CASE WHEN t.type='income' THEN t.amount ELSE 0 END) AS income,
                  SUM(CASE WHEN t.type='expense' AND c.is_savings=0 THEN t.amount ELSE 0 END) AS expense,
                  SUM(CASE WHEN t.type='expense' AND c.is_savings=1 THEN t.amount ELSE 0 END) AS saved
           FROM transactions t JOIN categories c ON t.category_id=c.id
           WHERE t.deleted_at IS NULL AND t.date>=? AND t.date<?
           GROUP BY t.date ORDER BY t.date""",
        (s, e),
    ).fetchall()
    return [{"date": r["date"], "income": from_cents(r["income"]),
             "expense": from_cents(r["expense"]), "saved": from_cents(r["saved"]),
             "savings": from_cents(r["income"]) - from_cents(r["expense"])} for r in rows]


def monthly(db, year):
    """One row per month for the given year (all 12 months, zero-filled)."""
    rows = db.execute(
        """
        SELECT substr(t.date,1,7) AS month,
               SUM(CASE WHEN t.type='income' THEN t.amount ELSE 0 END) AS income,
               SUM(CASE WHEN t.type='expense' AND c.is_savings=0 THEN t.amount ELSE 0 END) AS expense,
               SUM(CASE WHEN t.type='expense' AND c.is_savings=1 THEN t.amount ELSE 0 END) AS saved
        FROM transactions t JOIN categories c ON t.category_id=c.id
        WHERE t.deleted_at IS NULL AND substr(t.date,1,4)=?
        GROUP BY month ORDER BY month
        """,
        (str(year),),
    ).fetchall()
    data = {r["month"]: dict(r) for r in rows}
    out = []
    for mm in range(1, 13):
        key = f"{year}-{mm:02d}"
        d = data.get(key, {"income": 0, "expense": 0, "saved": 0})
        inc, exp, svd = from_cents(d["income"]), from_cents(d["expense"]), from_cents(d["saved"])
        out.append({"month": key, "income": inc, "expense": exp, "saved": svd,
                    "savings": inc - exp})
    return out


def category_totals_for_month(db, year, month):
    s, e = month_bounds(year, month)
    rows = db.execute(
        """SELECT c.name, c.type, SUM(t.amount) AS total
           FROM transactions t JOIN categories c ON t.category_id=c.id
           WHERE t.deleted_at IS NULL AND t.date>=? AND t.date<?
           GROUP BY c.id ORDER BY total DESC""",
        (s, e)).fetchall()
    for r in rows:
        r["total"] = from_cents(r["total"])
    return [dict(r) for r in rows]


def category_totals_for_year(db, year):
    rows = db.execute(
        """SELECT c.name, c.type, SUM(t.amount) AS total
           FROM transactions t JOIN categories c ON t.category_id=c.id
           WHERE t.deleted_at IS NULL AND substr(t.date,1,4)=?
           GROUP BY c.id ORDER BY total DESC""",
        (str(year),)).fetchall()
    for r in rows:
        r["total"] = from_cents(r["total"])
    return [dict(r) for r in rows]


def available_years(db):
    """Years present in data, with the current year always included."""
    years = [r[0] for r in db.execute(
        "SELECT DISTINCT substr(date,1,4) AS y FROM transactions"
        " WHERE deleted_at IS NULL ORDER BY y DESC").fetchall()]
    current = str(date.today().year)
    if current not in years:
        years = [current] + years
    return years


# ---------- budget variance ----------
def budget_variance(db, year, month):
    """Budget vs actual for the month: list of dicts with variance fields."""
    from ..budgets import models as budget_models
    out = []
    for b in budget_models.status(db, year, month):
        variance = b["limit"] - b["spent"]
        out.append({
            "name": b["name"], "category_id": b["category_id"],
            "limit": b["limit"], "spent": b["spent"],
            "pct": b["pct"], "remaining": b["remaining"],
            "variance": variance,
            "over": b["over"], "near": b["near"],
        })
    return out


# ---------- cash-flow forecast ----------
def forecast(db, months_ahead=3):
    """Simple cash-flow projection for the next N months.

    Method: the average of the last 3 full months of actual income/expense
    (which already includes recurring behaviour), projected flat, plus the
    current balance. Active recurring commitments are shown for context.
    """
    from ...helpers import from_cents, month_bounds
    today = date.today()

    # last 3 full months (excluding the current, usually incomplete month)
    hist = []
    y, m = today.year, today.month
    for _ in range(4):  # current + 3 back; drop the current below
        hist.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    hist = hist[1:]  # last 3 complete months

    incomes, expenses = [], []
    for yy, mm in hist:
        s, e = month_bounds(yy, mm)
        row = db.execute(
            """SELECT SUM(CASE WHEN t.type='income' THEN t.amount ELSE 0 END) AS i,
                      SUM(CASE WHEN t.type='expense' AND c.is_savings=0 THEN t.amount ELSE 0 END) AS e
               FROM transactions t JOIN categories c ON t.category_id=c.id
               WHERE t.deleted_at IS NULL AND t.date>=? AND t.date<?""",
            (s, e)).fetchone()
        incomes.append(from_cents(row["i"]))
        expenses.append(from_cents(row["e"]))
    avg_inc = round(sum(incomes) / 3, 2)
    avg_exp = round(sum(expenses) / 3, 2)

    # current balance (all time; savings buckets stay part of your money)
    row = db.execute(
        """SELECT SUM(CASE WHEN t.type='income' THEN t.amount ELSE 0 END) AS i,
                  SUM(CASE WHEN t.type='expense' AND c.is_savings=0 THEN t.amount ELSE 0 END) AS e
           FROM transactions t JOIN categories c ON t.category_id=c.id
           WHERE t.deleted_at IS NULL""").fetchone()
    balance = from_cents(row["i"]) - from_cents(row["e"])

    # recurring commitments for context (normalized to a monthly figure)
    norm = {"daily": 30.44, "weekly": 4.348, "monthly": 1.0, "yearly": 1 / 12}
    rec = db.execute(
        "SELECT r.amount, r.type, r.frequency, COALESCE(c.is_savings, 0) AS is_sav"
        " FROM recurrences r LEFT JOIN categories c ON c.id=r.category_id"
        " WHERE r.active=1 AND r.category_id IS NOT NULL").fetchall()
    rec_inc = round(sum(from_cents(r["amount"]) * norm[r["frequency"]]
                        for r in rec if r["type"] == "income"), 2)
    rec_exp = round(sum(from_cents(r["amount"]) * norm[r["frequency"]]
                        for r in rec if r["type"] == "expense" and not r["is_sav"]), 2)
    rec_saved = round(sum(from_cents(r["amount"]) * norm[r["frequency"]]
                          for r in rec if r["type"] == "expense" and r["is_sav"]), 2)

    out = []
    running = balance
    yy, mm = today.year, today.month
    for _ in range(months_ahead):
        mm += 1
        if mm == 13:
            mm, yy = 1, yy + 1
        running = round(running + avg_inc - avg_exp, 2)
        out.append({"month": f"{yy}-{mm:02d}", "income": avg_inc,
                    "expense": avg_exp, "net": round(avg_inc - avg_exp, 2),
                    "projected_balance": running})
    return {"months": out, "balance": balance,
            "recurring_income": rec_inc, "recurring_expense": rec_exp,
            "recurring_saved": rec_saved}
