"""Budget data access (Model layer)."""
from ...helpers import month_bounds


def status(db, year, month):
    """Per-budget spend for the given month. Returns a list of dicts."""
    s, e = month_bounds(year, month)
    rows = db.execute(
        """
        SELECT b.id AS budget_id, b.monthly_limit, c.id AS category_id, c.name,
               COALESCE(SUM(CASE WHEN t.date>=? AND t.date<? THEN t.amount ELSE 0 END),0) AS spent
        FROM budgets b JOIN categories c ON c.id = b.category_id
        LEFT JOIN transactions t ON t.category_id = c.id AND t.type='expense'
        GROUP BY b.id, b.monthly_limit, c.id, c.name ORDER BY c.name
        """,
        (s, e),
    ).fetchall()
    out = []
    for r in rows:
        limit = r["monthly_limit"] or 0
        spent = r["spent"] or 0
        pct = min(100.0, (spent / limit * 100) if limit else 0)
        out.append({
            "budget_id": r["budget_id"], "category_id": r["category_id"],
            "name": r["name"], "limit": limit, "spent": spent,
            "remaining": limit - spent, "pct": round(pct, 1),
            "over": spent > limit,
            "near": (not spent > limit) and pct >= 80,
        })
    return out


def limits_map(db):
    """{category_id: monthly_limit}."""
    return {r["category_id"]: r["monthly_limit"] for r in
            db.execute("SELECT * FROM budgets").fetchall()}


def upsert(db, category_id, limit):
    """Insert or update the monthly limit for a category (no commit)."""
    db.execute(
        """INSERT INTO budgets (category_id, monthly_limit) VALUES (?,?)
           ON CONFLICT(category_id) DO UPDATE SET monthly_limit=excluded.monthly_limit""",
        (category_id, limit))


def set_limit(db, category_id, limit):
    """Upsert the monthly limit for a category (commits)."""
    upsert(db, category_id, limit)
    db.commit()


def clear(db, category_id):
    db.execute("DELETE FROM budgets WHERE category_id=?", (category_id,))
    db.commit()
