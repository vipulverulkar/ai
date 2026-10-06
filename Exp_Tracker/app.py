import sqlite3
import os
from datetime import date, datetime
from flask import Flask, render_template, request, redirect, url_for, flash, g

app = Flask(__name__)
app.secret_key = "exptracker-secret-change-me"

DB_PATH = os.environ.get(
    "EXPENSE_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "expenses.db"),
)

DEFAULT_CATEGORIES = [
    ("Salary", "income"),
    ("Freelance", "income"),
    ("Investment", "income"),
    ("Food", "expense"),
    ("Transport", "expense"),
    ("Shopping", "expense"),
    ("Bills", "expense"),
    ("Entertainment", "expense"),
    ("Health", "expense"),
    ("Other", "expense"),
]


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            type TEXT NOT NULL CHECK (type IN ('income','expense'))
        )
        """
    )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            amount REAL NOT NULL CHECK (amount > 0),
            type TEXT NOT NULL CHECK (type IN ('income','expense')),
            category_id INTEGER NOT NULL,
            date TEXT NOT NULL,
            note TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT
        )
        """
    )
    for name, ctype in DEFAULT_CATEGORIES:
        db.execute(
            "INSERT OR IGNORE INTO categories (name, type) VALUES (?, ?)",
            (name, ctype),
        )
    db.commit()
    db.close()


def parse_month(month_str):
    """month_str 'YYYY-MM' -> (year, month). Defaults to current month."""
    try:
        dt = datetime.strptime(month_str, "%Y-%m")
        return dt.year, dt.month
    except (ValueError, TypeError):
        today = date.today()
        return today.year, today.month


def month_bounds(year, month):
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 1)
    else:
        end = date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


# ---------- Routes ----------

@app.route("/")
def index():
    db = get_db()
    today_str = date.today().isoformat()
    year_m, month_m = date.today().year, date.today().month
    m_start, m_end = month_bounds(year_m, month_m)

    def scalar(q, args=()):
        row = db.execute(q, args).fetchone()
        return (row[0] if row and row[0] is not None else 0)

    today_income = scalar(
        "SELECT SUM(amount) FROM transactions WHERE type='income' AND date=?", (today_str,))
    today_expense = scalar(
        "SELECT SUM(amount) FROM transactions WHERE type='expense' AND date=?", (today_str,))
    month_income = scalar(
        "SELECT SUM(amount) FROM transactions WHERE type='income' AND date>=? AND date<?",
        (m_start, m_end))
    month_expense = scalar(
        "SELECT SUM(amount) FROM transactions WHERE type='expense' AND date>=? AND date<?",
        (m_start, m_end))
    total_income = scalar("SELECT SUM(amount) FROM transactions WHERE type='income'")
    total_expense = scalar("SELECT SUM(amount) FROM transactions WHERE type='expense'")

    categories = db.execute("SELECT * FROM categories ORDER BY type, name").fetchall()

    return render_template(
        "index.html",
        today_income=today_income, today_expense=today_expense,
        month_income=month_income, month_expense=month_expense,
        total_income=total_income, total_expense=total_expense,
        balance=total_income - total_expense,
        categories=categories,
        today=today_str,
    )


@app.route("/transactions")
def transactions():
    db = get_db()
    categories = db.execute("SELECT * FROM categories ORDER BY type, name").fetchall()

    # Filters for transaction list
    f_type = request.args.get("type", "all")
    f_category = request.args.get("category", "all")
    f_month = request.args.get("month", "")
    f_search = request.args.get("q", "").strip()

    try:
        per_page = int(request.args.get("per_page", 10))
    except (ValueError, TypeError):
        per_page = 10
    if per_page not in (10, 25, 50, 100):
        per_page = 10

    where = "WHERE 1=1"
    args = []
    if f_type in ("income", "expense"):
        where += " AND t.type = ?"
        args.append(f_type)
    if f_category != "all" and f_category.isdigit():
        where += " AND t.category_id = ?"
        args.append(int(f_category))
    if f_month:
        try:
            y, m = parse_month(f_month)
            s, e = month_bounds(y, m)
            where += " AND t.date >= ? AND t.date < ?"
            args.extend([s, e])
        except ValueError:
            pass
    if f_search:
        where += " AND (t.note LIKE ? OR c.name LIKE ?)"
        args.extend([f"%{f_search}%", f"%{f_search}%"])

    total = db.execute(
        f"SELECT COUNT(*) FROM transactions t JOIN categories c ON t.category_id = c.id {where}",
        args,
    ).fetchone()[0]

    total_pages = max(1, -(-total // per_page))  # ceil division, at least 1
    try:
        page = int(request.args.get("page", 1))
    except (ValueError, TypeError):
        page = 1
    page = max(1, min(page, total_pages))

    offset = (page - 1) * per_page
    txns = db.execute(
        f"""SELECT t.*, c.name AS category_name
        FROM transactions t JOIN categories c ON t.category_id = c.id
        {where} ORDER BY t.date DESC, t.id DESC LIMIT ? OFFSET ?""",
        args + [per_page, offset],
    ).fetchall()

    start = offset + 1 if total else 0
    end = min(offset + per_page, total)

    # Page numbers with ellipsis (None = …)
    pages = []
    for p in range(1, total_pages + 1):
        if p == 1 or p == total_pages or abs(p - page) <= 2:
            pages.append(p)
        elif pages[-1] is not None:
            pages.append(None)

    return render_template(
        "transactions.html",
        transactions=txns, categories=categories,
        f_type=f_type, f_category=f_category, f_month=f_month, f_search=f_search,
        page=page, per_page=per_page, total=total, total_pages=total_pages,
        start=start, end=end, pages=pages,
    )


@app.route("/add", methods=["POST"])
def add_transaction():
    amount = request.form.get("amount", "").strip()
    ttype = request.form.get("type", "expense")
    category_id = request.form.get("category_id", "")
    date_str = request.form.get("date", "") or date.today().isoformat()
    note = request.form.get("note", "").strip()

    try:
        amount = float(amount)
        if amount <= 0:
            raise ValueError
    except ValueError:
        flash("Amount must be a positive number.", "error")
        return redirect(url_for("index"))

    if ttype not in ("income", "expense"):
        flash("Invalid type.", "error")
        return redirect(url_for("index"))

    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        flash("Invalid date.", "error")
        return redirect(url_for("index"))

    db = get_db()
    cat = db.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    if not cat:
        flash("Please select a valid category.", "error")
        return redirect(url_for("index"))
    if cat["type"] != ttype:
        flash(f"Category '{cat['name']}' is an {cat['type']} category. Type mismatch.", "error")
        return redirect(url_for("index"))

    db.execute(
        "INSERT INTO transactions (amount, type, category_id, date, note) VALUES (?,?,?,?,?)",
        (amount, ttype, cat["id"], date_str, note),
    )
    db.commit()
    flash("Transaction added.", "success")
    return redirect(url_for("index"))


@app.route("/edit/<int:tx_id>", methods=["GET", "POST"])
def edit_transaction(tx_id):
    db = get_db()
    tx = db.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    if not tx:
        flash("Transaction not found.", "error")
        return redirect(url_for("transactions"))
    categories = db.execute("SELECT * FROM categories ORDER BY type, name").fetchall()

    if request.method == "POST":
        amount = request.form.get("amount", "").strip()
        ttype = request.form.get("type", "expense")
        category_id = request.form.get("category_id", "")
        date_str = request.form.get("date", "")
        note = request.form.get("note", "").strip()
        try:
            amount = float(amount)
            if amount <= 0:
                raise ValueError
        except ValueError:
            flash("Amount must be a positive number.", "error")
            return redirect(url_for("edit_transaction", tx_id=tx_id))
        if ttype not in ("income", "expense"):
            flash("Invalid type.", "error")
            return redirect(url_for("edit_transaction", tx_id=tx_id))
        try:
            datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            flash("Invalid date.", "error")
            return redirect(url_for("edit_transaction", tx_id=tx_id))
        cat = db.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
        if not cat:
            flash("Please select a valid category.", "error")
            return redirect(url_for("edit_transaction", tx_id=tx_id))
        if cat["type"] != ttype:
            flash(f"Category '{cat['name']}' is an {cat['type']} category.", "error")
            return redirect(url_for("edit_transaction", tx_id=tx_id))
        db.execute(
            "UPDATE transactions SET amount=?, type=?, category_id=?, date=?, note=? WHERE id=?",
            (amount, ttype, cat["id"], date_str, note, tx_id),
        )
        db.commit()
        flash("Transaction updated.", "success")
        return redirect(url_for("transactions"))

    return render_template("edit.html", tx=tx, categories=categories)


@app.route("/delete/<int:tx_id>", methods=["POST"])
def delete_transaction(tx_id):
    db = get_db()
    db.execute("DELETE FROM transactions WHERE id=?", (tx_id,))
    db.commit()
    flash("Transaction deleted.", "success")
    return redirect(url_for("transactions"))


@app.route("/categories", methods=["GET", "POST"])
def categories():
    db = get_db()
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        ctype = request.form.get("type", "expense")
        if not name:
            flash("Category name is required.", "error")
            return redirect(url_for("categories"))
        if ctype not in ("income", "expense"):
            flash("Invalid category type.", "error")
            return redirect(url_for("categories"))
        try:
            db.execute("INSERT INTO categories (name, type) VALUES (?, ?)", (name, ctype))
            db.commit()
            flash(f"Category '{name}' added.", "success")
        except sqlite3.IntegrityError:
            flash(f"Category '{name}' already exists.", "error")
        return redirect(url_for("categories"))

    cats = db.execute("SELECT * FROM categories ORDER BY type, name").fetchall()
    usage = {
        r["category_id"]: r["cnt"]
        for r in db.execute(
            "SELECT category_id, COUNT(*) AS cnt FROM transactions GROUP BY category_id"
        ).fetchall()
    }
    return render_template("categories.html", categories=cats, usage=usage)


@app.route("/categories/delete/<int:cat_id>", methods=["POST"])
def delete_category(cat_id):
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) FROM transactions WHERE category_id=?", (cat_id,)
    ).fetchone()[0]
    if count > 0:
        flash(f"Cannot delete: {count} transaction(s) use this category.", "error")
        return redirect(url_for("categories"))
    db.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    db.commit()
    flash("Category deleted.", "success")
    return redirect(url_for("categories"))


@app.route("/reports")
def reports():
    db = get_db()
    view = request.args.get("view", "daily")  # daily | monthly
    today = date.today()

    if view == "monthly":
        year = request.args.get("year", str(today.year))
        try:
            year = int(year)
        except ValueError:
            year = today.year
        rows = db.execute(
            """
            SELECT substr(date,1,7) AS month,
                   SUM(CASE WHEN type='income' THEN amount ELSE 0 END) AS income,
                   SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) AS expense
            FROM transactions
            WHERE substr(date,1,4) = ?
            GROUP BY month ORDER BY month
            """,
            (str(year),),
        ).fetchall()
        months = [f"{year}-{m:02d}" for m in range(1, 13)]
        data = {r["month"]: dict(r) for r in rows}
        monthly = []
        for m in months:
            d = data.get(m, {"income": 0, "expense": 0})
            monthly.append({
                "month": m,
                "income": d["income"] or 0,
                "expense": d["expense"] or 0,
                "savings": (d["income"] or 0) - (d["expense"] or 0),
            })
        tot_inc = sum(x["income"] for x in monthly)
        tot_exp = sum(x["expense"] for x in monthly)
        max_month = max([max(x["income"], x["expense"]) for x in monthly] + [0])
        cat_rows = [dict(c) for c in db.execute(
            """
            SELECT c.name, c.type, SUM(t.amount) AS total
            FROM transactions t JOIN categories c ON t.category_id=c.id
            WHERE substr(t.date,1,4)=? GROUP BY c.id ORDER BY total DESC
            """,
            (str(year),),
        ).fetchall()]
        max_cat = max([c["total"] or 0 for c in cat_rows] + [0])
        years = [r[0] for r in db.execute(
            "SELECT DISTINCT substr(date,1,4) AS y FROM transactions ORDER BY y DESC").fetchall()]
        if str(today.year) not in years:
            years = [str(today.year)] + years
        return render_template("reports.html", view=view, year=year, years=years,
                               monthly=monthly, tot_inc=tot_inc, tot_exp=tot_exp,
                               max_month=max_month, max_cat=max_cat,
                               cat_rows=cat_rows, period_label=str(year))

    # daily view (default): breakdown per day for a given month
    month_str = request.args.get("month", today.strftime("%Y-%m"))
    y, m = parse_month(month_str)
    month_str = f"{y}-{m:02d}"
    s, e = month_bounds(y, m)
    rows = db.execute(
        """
        SELECT date,
               SUM(CASE WHEN type='income' THEN amount ELSE 0 END) AS income,
               SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) AS expense
        FROM transactions WHERE date>=? AND date<? GROUP BY date ORDER BY date
        """,
        (s, e),
    ).fetchall()
    daily = [{"date": r["date"], "income": r["income"] or 0,
              "expense": r["expense"] or 0,
              "savings": (r["income"] or 0) - (r["expense"] or 0)} for r in rows]
    tot_inc = sum(d["income"] for d in daily)
    tot_exp = sum(d["expense"] for d in daily)
    max_day = max([max(d["income"], d["expense"]) for d in daily] + [0])
    cat_rows = [dict(c) for c in db.execute(
        """
        SELECT c.name, c.type, SUM(t.amount) AS total
        FROM transactions t JOIN categories c ON t.category_id=c.id
        WHERE t.date>=? AND t.date<? GROUP BY c.id ORDER BY total DESC
        """,
        (s, e),
    ).fetchall()]
    max_cat = max([c["total"] or 0 for c in cat_rows] + [0])
    return render_template("reports.html", view=view, month=month_str,
                           daily=daily, tot_inc=tot_inc, tot_exp=tot_exp,
                           max_day=max_day, max_cat=max_cat,
                           cat_rows=cat_rows, period_label=month_str)


# Ensure tables exist on import too (needed when served by gunicorn,
# where the __main__ block below never runs). init_db is idempotent.
init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
