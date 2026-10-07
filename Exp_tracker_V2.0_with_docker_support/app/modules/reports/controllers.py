"""Report routes (Controller layer)."""
from datetime import date

from flask import render_template, request

from ...db import get_db
from ...helpers import parse_month
from . import bp, models


@bp.route("/reports")
def index():
    db = get_db()
    view = request.args.get("view", "daily")
    today = date.today()
    if view == "monthly":
        return _monthly(db, today)
    return _daily(db, today)


def _daily(db, today):
    month_str = request.args.get("month", today.strftime("%Y-%m"))
    y, m = parse_month(month_str)
    month_str = f"{y}-{m:02d}"
    daily = models.daily(db, y, m)
    tot_inc = sum(d["income"] for d in daily)
    tot_exp = sum(d["expense"] for d in daily)
    max_day = max([max(d["income"], d["expense"]) for d in daily] + [0])
    cat_rows = models.category_totals_for_month(db, y, m)
    max_cat = max([c["total"] or 0 for c in cat_rows] + [0])
    savings_rate = round((tot_inc - tot_exp) / tot_inc * 100, 1) if tot_inc else 0
    return render_template("reports/reports.html", view="daily", month=month_str,
                           daily=daily, tot_inc=tot_inc, tot_exp=tot_exp,
                           max_day=max_day, max_cat=max_cat,
                           cat_rows=cat_rows, period_label=month_str,
                           savings_rate=savings_rate)


def _monthly(db, today):
    year = request.args.get("year", str(today.year))
    try:
        year = int(year)
    except ValueError:
        year = today.year
    monthly = models.monthly(db, year)
    tot_inc = sum(x["income"] for x in monthly)
    tot_exp = sum(x["expense"] for x in monthly)
    max_month = max([max(x["income"], x["expense"]) for x in monthly] + [0])
    cat_rows = models.category_totals_for_year(db, year)
    max_cat = max([c["total"] or 0 for c in cat_rows] + [0])
    savings_rate = round((tot_inc - tot_exp) / tot_inc * 100, 1) if tot_inc else 0
    return render_template("reports/reports.html", view="monthly", year=year,
                           years=models.available_years(db), monthly=monthly,
                           tot_inc=tot_inc, tot_exp=tot_exp,
                           max_month=max_month, max_cat=max_cat, cat_rows=cat_rows,
                           period_label=str(year), savings_rate=savings_rate)
