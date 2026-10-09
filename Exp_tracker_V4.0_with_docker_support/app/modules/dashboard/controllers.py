"""Dashboard routes (Controller layer)."""
from datetime import date

from flask import render_template, session

from ...db import get_db
from ..auth import models as auth_models
from ..budgets import models as budget_models
from ..categories import models as category_models
from . import bp, models


@bp.route("/")
def index():
    db = get_db()
    today = date.today()

    # Auto-process due recurring transactions so the dashboard is current.
    from ..recurring import models as recurring_models
    try:
        from flask import flash as _flash
        _, capped = recurring_models.run_due(db, today)
        if capped:
            _flash(f"{capped} overdue schedule(s) hit the catch-up limit and were "
                   "paused — oldest backlog was generated, newer missed runs were "
                   "dropped. Resume them from Recurring if needed.", "warning")
    except Exception:  # noqa: BLE001 — never block the dashboard on scheduling
        pass

    sums = models.totals(db, today)
    recent = models.recent(db)
    trend = models.trend(db, 6)
    top_cats = models.top_categories(db, today.year, today.month)
    top_total = sum(r["total"] or 0 for r in top_cats)
    max_top = max([r["total"] or 0 for r in top_cats] + [0])

    budgets = budget_models.status(db, today.year, today.month)
    over_budgets = [b for b in budgets if b["over"]]
    near_budgets = [b for b in budgets if b["near"]]

    return render_template(
        "dashboard/index.html",
        username=session.get("user", ""),
        today_income=sums["today_income"], today_expense=sums["today_expense"],
        month_income=sums["month_income"], month_expense=sums["month_expense"],
        month_saved=sums["month_saved"],
        total_income=sums["total_income"], total_expense=sums["total_expense"],
        total_saved=sums["total_saved"],
        balance=sums["balance"], savings_rate=sums["savings_rate"],
        categories=category_models.all(db), today=today.isoformat(),
        owners=auth_models.all_users(db),
        recent=recent, trend=trend,
        top_cats=top_cats, top_total=top_total, max_top=max_top,
        budgets=budgets, over_budgets=over_budgets, near_budgets=near_budgets,
    )
