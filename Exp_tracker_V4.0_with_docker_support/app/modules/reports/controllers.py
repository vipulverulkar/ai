"""Report routes (Controller layer)."""
import io
import pandas as pd
from datetime import date
from flask import Response, flash, redirect, render_template, request, send_file, url_for

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
    if view == "budgets":
        return _budgets(db, today)
    if view == "forecast":
        return _forecast(db)
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


def _budgets(db, today):
    month_str = request.args.get("month", today.strftime("%Y-%m"))
    y, m = parse_month(month_str)
    month_str = f"{y}-{m:02d}"
    rows = models.budget_variance(db, y, m)
    tot_limit = sum(r["limit"] for r in rows)
    tot_spent = sum(r["spent"] for r in rows)
    return render_template("reports/reports.html", view="budgets",
                           month=month_str, variance_rows=rows,
                           tot_limit=tot_limit, tot_spent=tot_spent,
                           tot_variance=tot_limit - tot_spent,
                           period_label=month_str)


def _forecast(db):
    data = models.forecast(db)
    return render_template("reports/reports.html", view="forecast",
                           forecast=data, period_label="next 3 months")


@bp.route("/reports/export-xlsx")
def export_xlsx():
    """Export the current report view as an Excel file."""
    db = get_db()
    today = date.today()
    view = request.args.get("view", "daily")
    
    if view == "monthly":
        try:
            year = int(request.args.get("year", str(today.year)))
        except ValueError:
            year = today.year
        rows = models.monthly(db, year)
        period = f"Year {year}"
        df = pd.DataFrame(rows)
        cat_rows = models.category_totals_for_year(db, year)
        df_cats = pd.DataFrame(cat_rows)
    elif view == "budgets":
        month_str = request.args.get("month", today.strftime("%Y-%m"))
        y, m = parse_month(month_str)
        rows = models.budget_variance(db, y, m)
        period = f"Budget Variance {month_str}"
        df = pd.DataFrame(rows)
        df_cats = pd.DataFrame()
    else: # daily
        month_str = request.args.get("month", today.strftime("%Y-%m"))
        y, m = parse_month(month_str)
        rows = models.daily(db, y, m)
        period = f"Month {month_str}"
        df = pd.DataFrame(rows)
        cat_rows = models.category_totals_for_month(db, y, m)
        df_cats = pd.DataFrame(cat_rows)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Summary', index=False)
        if not df_cats.empty:
            df_cats.to_excel(writer, sheet_name='Categories', index=False)
    
    buf.seek(0)
    stamp = today.strftime("%Y%m%d")
    return send_file(buf, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", 
                     as_attachment=True, download_name=f"exptracker-report-{stamp}.xlsx")



@bp.route("/reports/export-pdf")
def export_pdf():
    """PDF summary of a month (or year) — requires reportlab."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table
        from reportlab.lib.styles import getSampleStyleSheet
    except ImportError:
        flash("PDF export needs the reportlab package (pip install reportlab).", "error")
        return redirect(url_for("reports.index"))

    db = get_db()
    today = date.today()
    view = request.args.get("view", "daily")
    if view == "monthly":
        try:
            year = int(request.args.get("year", str(today.year)))
        except ValueError:
            year = today.year
        rows = models.monthly(db, year)
        period = f"Year {year}"
        table_head = ["Month", "Income", "Expense", "Savings"]
        table_rows = [[r["month"], f"{r['income']:,.2f}", f"{r['expense']:,.2f}",
                       f"{r['savings']:,.2f}"] for r in rows]
        tot_inc = sum(r["income"] for r in rows)
        tot_exp = sum(r["expense"] for r in rows)
        cat_rows = models.category_totals_for_year(db, year)
    else:
        month_str = request.args.get("month", today.strftime("%Y-%m"))
        y, m = parse_month(month_str)
        rows = models.daily(db, y, m)
        period = f"Month {y}-{m:02d}"
        table_head = ["Date", "Income", "Expense", "Savings"]
        table_rows = [[r["date"], f"{r['income']:,.2f}", f"{r['expense']:,.2f}",
                       f"{r['savings']:,.2f}"] for r in rows]
        tot_inc = sum(r["income"] for r in rows)
        tot_exp = sum(r["expense"] for r in rows)
        cat_rows = models.category_totals_for_month(db, y, m)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=15 * mm,
                            leftMargin=15 * mm, rightMargin=15 * mm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("Expense Tracker — Report", styles["Title"]),
        Paragraph(f"Period: {period}", styles["Heading2"]),
        Spacer(1, 6 * mm),
        Paragraph(f"Total income: {tot_inc:,.2f} · Total expense: {tot_exp:,.2f} "
                  f"· Savings: {tot_inc - tot_exp:,.2f}", styles["Normal"]),
        Spacer(1, 6 * mm),
        Paragraph("Breakdown", styles["Heading3"]),
        Table([table_head] + table_rows, repeatRows=1,
              style=[("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                     ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)]),
    ]
    if cat_rows:
        story += [Spacer(1, 6 * mm), Paragraph("By category", styles["Heading3"]),
                  Table([["Category", "Type", "Total"]] +
                        [[c["name"], c["type"], f"{(c['total'] or 0):,.2f}"]
                         for c in cat_rows],
                        style=[("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
                               ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey)])]
    doc.build(story)
    buf.seek(0)
    stamp = today.strftime("%Y%m%d")
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"exptracker-report-{stamp}.pdf")
