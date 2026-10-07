"""Expense Tracker — Flask + SQLite.

Features: dashboard, transactions (filter/sort/paginate/CSV),
budgets, category management, daily/monthly reports, JSON API.
"""
import csv
import io
import logging
import os
import sqlite3
from datetime import date, datetime

from flask import (
    Flask,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    Response,
    url_for,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("exptracker")

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")
if app.secret_key == "dev-only-change-me-in-production":
    log.warning("SECRET_KEY not set — using insecure dev default. Set SECRET_KEY env var.")
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024  # 2 MB (CSV imports)

DB_PATH = os.environ.get(
    "EXPENSE_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "expenses.db"),
)
CURRENCY = os.environ.get("CURRENCY_SYMBOL", "₹")
APP_VERSION = "2.0.0"

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


# ---------- DB ----------
def _ensure_db_dir():
    parent = os.path.dirname(os.path.abspath(DB_PATH))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def get_db():
    if "db" not in g:
        _ensure_db_dir()
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
    _ensure_db_dir()
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
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS budgets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category_id INTEGER UNIQUE NOT NULL,
            monthly_limit REAL NOT NULL CHECK (monthly_limit > 0),
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
        )
        """
    )
    db.execute("CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tx_cat ON transactions(category_id)")
    db.execute("CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(type)")
    for name, ctype in DEFAULT_CATEGORIES:
        db.execute(
            "INSERT OR IGNORE INTO categories (name, type) VALUES (?, ?)",
            (name, ctype),
        )
    db.commit()
    db.close()


# ---------- Helpers ----------
def format_inr(value, decimals=2):
    """Format a number Indian-style: 1234567.89 -> '12,34,567.89'."""
    try:
        v = float(value or 0)
    except (ValueError, TypeError):
        return f"0.{'0' * decimals}"
    neg = v < 0
    v = abs(v)
    s = f"{v:.{decimals}f}"
    if "." in s:
        intpart, dec = s.split(".")
    else:
        intpart, dec = s, ""
    if len(intpart) > 3:
        last3 = intpart[-3:]
        rest = intpart[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        intpart = ",".join(groups) + "," + last3
    out = f"{intpart}.{dec}" if dec else intpart
    return f"-{out}" if neg else out


@app.template_filter("money")
def money_filter(value):
    return format_inr(value, 2)


@app.template_filter("money0")
def money0_filter(value):
    return format_inr(value, 0)


def parse_month(month_str):
    """'YYYY-MM' -> (year, month). Defaults to current month."""
    try:
        dt = datetime.strptime(month_str, "%Y-%m")
        return dt.year, dt.month
    except (ValueError, TypeError):
        today = date.today()
        return today.year, today.month


def month_bounds(year, month):
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def last_n_months(n=6):
    today = date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


def validate_txn(amount_raw, ttype, category_id, date_str, note):
    """Return (amount, cat_row, date_str, note, error_msg)."""
    try:
        amount = round(float(str(amount_raw).replace(",", "").strip()), 2)
        if amount <= 0:
            raise ValueError
    except (ValueError, AttributeError):
        return None, None, None, None, "Amount must be a positive number."
    if ttype not in ("income", "expense"):
        return None, None, None, None, "Invalid transaction type."
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return None, None, None, None, "Invalid date (use YYYY-MM-DD)."
    if date_str > date.today().isoformat():
        return None, None, None, None, "Date cannot be in the future."
    db = get_db()
    try:
        cat = db.execute("SELECT * FROM categories WHERE id=?", (category_id,)).fetchone()
    except (sqlite3.Error, ValueError):
        cat = None
    if not cat:
        return None, None, None, None, "Please select a valid category."
    if cat["type"] != ttype:
        return None, None, None, None, f"Category '{cat['name']}' is for {cat['type']}, not {ttype}."
    note = (note or "").strip()[:200]
    return amount, cat, date_str, note, None


def budget_status(year, month):
    """Per-budget spend for given month. Returns list of dicts."""
    db = get_db()
    s, e = month_bounds(year, month)
    rows = db.execute(
        """
        SELECT b.id AS budget_id, b.monthly_limit, c.id AS category_id, c.name,
               COALESCE(SUM(CASE WHEN t.date>=? AND t.date<? THEN t.amount ELSE 0 END),0) AS spent
        FROM budgets b JOIN categories c ON c.id = b.category_id
        LEFT JOIN transactions t ON t.category_id = c.id AND t.type='expense'
        GROUP BY b.id ORDER BY c.name
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


@app.context_processor
def inject_globals():
    return {"currency": CURRENCY, "app_version": APP_VERSION,
            "current_year": date.today().year}


@app.after_request
def security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    return resp


@app.errorhandler(404)
def not_found(e):
    return render_template("error.html", code=404,
                           message="The page you asked for doesn't exist."), 404


@app.errorhandler(413)
def too_large(e):
    flash("Upload too large (max 2 MB).", "error")
    return redirect(url_for("transactions"))


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", code=500,
                           message="Something went wrong. Please try again."), 500


# ---------- Routes ----------
@app.route("/healthz")
def healthz():
    try:
        db = get_db()
        db.execute("SELECT 1").fetchone()
        return jsonify(status="ok", version=APP_VERSION), 200
    except Exception:  # noqa: BLE001
        return jsonify(status="error"), 500


@app.route("/")
def index():
    db = get_db()
    today_str = date.today().isoformat()
    y, m = date.today().year, date.today().month
    m_start, m_end = month_bounds(y, m)

    def scalar(q, args=()):
        row = db.execute(q, args).fetchone()
        return row[0] if row and row[0] is not None else 0

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

    savings_rate = (round((month_income - month_expense) / month_income * 100, 1)
                    if month_income else 0)

    categories = db.execute("SELECT * FROM categories ORDER BY type, name").fetchall()
    recent = db.execute(
        """SELECT t.*, c.name AS category_name FROM transactions t
           JOIN categories c ON t.category_id=c.id
           ORDER BY t.date DESC, t.id DESC LIMIT 8"""
    ).fetchall()

    # 6-month trend
    trend = []
    for yy, mm in last_n_months(6):
        s, e = month_bounds(yy, mm)
        inc = scalar("SELECT SUM(amount) FROM transactions WHERE type='income' AND date>=? AND date<?", (s, e))
        exp = scalar("SELECT SUM(amount) FROM transactions WHERE type='expense' AND date>=? AND date<?", (s, e))
        trend.append({"month": f"{yy}-{mm:02d}", "label": date(yy, mm, 1).strftime("%b"),
                      "income": inc or 0, "expense": exp or 0, "savings": (inc or 0) - (exp or 0)})

    top_cats = db.execute(
        """SELECT c.name, SUM(t.amount) AS total FROM transactions t
           JOIN categories c ON t.category_id=c.id
           WHERE t.type='expense' AND t.date>=? AND t.date<? GROUP BY c.id
           ORDER BY total DESC LIMIT 5""",
        (m_start, m_end),
    ).fetchall()
    top_total = sum(r["total"] or 0 for r in top_cats)
    max_top = max([r["total"] or 0 for r in top_cats] + [0])

    budgets = budget_status(y, m)
    over_budgets = [b for b in budgets if b["over"]]
    near_budgets = [b for b in budgets if b["near"]]

    return render_template(
        "index.html",
        today_income=today_income, today_expense=today_expense,
        month_income=month_income, month_expense=month_expense,
        total_income=total_income, total_expense=total_expense,
        balance=total_income - total_expense, savings_rate=savings_rate,
        categories=categories, today=today_str, recent=recent, trend=trend,
        top_cats=top_cats, top_total=top_total, max_top=max_top,
        budgets=budgets, over_budgets=over_budgets, near_budgets=near_budgets,
    )


def _txn_filter_args():
    f_type = request.args.get("type", "all")
    f_category = request.args.get("category", "all")
    f_month = request.args.get("month", "")
    f_search = request.args.get("q", "").strip()
    sort = request.args.get("sort", "date")
    order = request.args.get("order", "desc")
    if sort not in ("date", "amount", "category"):
        sort = "date"
    if order not in ("asc", "desc"):
        order = "desc"
    where = "WHERE 1=1"
    args = []
    if f_type in ("income", "expense"):
        where += " AND t.type = ?"
        args.append(f_type)
    if f_category != "all" and f_category.isdigit():
        where += " AND t.category_id = ?"
        args.append(int(f_category))
    if f_month:
        yy, mm = parse_month(f_month)
        s, e = month_bounds(yy, mm)
        where += " AND t.date >= ? AND t.date < ?"
        args.extend([s, e])
    if f_search:
        where += " AND (t.note LIKE ? OR c.name LIKE ?)"
        args.extend([f"%{f_search}%", f"%{f_search}%"])
    order_col = {"date": "t.date", "amount": "t.amount", "category": "c.name"}[sort]
    direction = "ASC" if order == "asc" else "DESC"
    order_sql = f"{order_col} {direction}, t.id DESC"
    return f_type, f_category, f_month, f_search, sort, order, where, args, order_sql


@app.route("/transactions")
def transactions():
    db = get_db()
    categories = db.execute("SELECT * FROM categories ORDER BY type, name").fetchall()
    f_type, f_category, f_month, f_search, sort, order, where, args, order_sql = _txn_filter_args()

    try:
        per_page = int(request.args.get("per_page", 10))
    except (ValueError, TypeError):
        per_page = 10
    if per_page not in (10, 25, 50, 100):
        per_page = 10

    total = db.execute(
        f"SELECT COUNT(*) FROM transactions t JOIN categories c ON t.category_id=c.id {where}",
        args,
    ).fetchone()[0]
    sums = db.execute(
        f"""SELECT SUM(CASE WHEN t.type='income' THEN t.amount ELSE 0 END) AS inc,
                    SUM(CASE WHEN t.type='expense' THEN t.amount ELSE 0 END) AS exp
            FROM transactions t JOIN categories c ON t.category_id=c.id {where}""",
        args,
    ).fetchone()
    filt_income, filt_expense = (sums["inc"] or 0), (sums["exp"] or 0)

    total_pages = max(1, -(-total // per_page))
    try:
        page = int(request.args.get("page", 1))
    except (ValueError, TypeError):
        page = 1
    page = max(1, min(page, total_pages))
    offset = (page - 1) * per_page
    txns = db.execute(
        f"""SELECT t.*, c.name AS category_name
        FROM transactions t JOIN categories c ON t.category_id=c.id
        {where} ORDER BY {order_sql} LIMIT ? OFFSET ?""",
        args + [per_page, offset],
    ).fetchall()

    start = offset + 1 if total else 0
    end = min(offset + per_page, total)
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
        sort=sort, order=order,
        page=page, per_page=per_page, total=total, total_pages=total_pages,
        start=start, end=end, pages=pages,
        filt_income=filt_income, filt_expense=filt_expense,
        filt_net=filt_income - filt_expense,
    )


@app.route("/transactions/export")
def export_transactions():
    db = get_db()
    _, _, _, _, _, _, where, args, order_sql = _txn_filter_args()
    rows = db.execute(
        f"""SELECT t.id, t.date, t.type, c.name AS category, t.amount, t.note
            FROM transactions t JOIN categories c ON t.category_id=c.id
            {where} ORDER BY {order_sql}""",
        args,
    ).fetchall()
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "date", "type", "category", "amount", "note"])
    for r in rows:
        w.writerow([r["id"], r["date"], r["type"], r["category"], f"{r['amount']:.2f}", r["note"] or ""])
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return Response(buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename=expenses-{stamp}.csv"})


@app.route("/transactions/import", methods=["POST"])
def import_transactions():
    f = request.files.get("file")
    if not f or not f.filename.lower().endswith(".csv"):
        flash("Please upload a .csv file.", "error")
        return redirect(url_for("transactions"))
    try:
        text = f.read().decode("utf-8-sig")
    except Exception:  # noqa: BLE001
        flash("Could not read CSV file.", "error")
        return redirect(url_for("transactions"))
    reader = csv.DictReader(io.StringIO(text))
    db = get_db()
    cats = {r["name"].lower(): r for r in
            db.execute("SELECT * FROM categories").fetchall()}
    inserted, skipped = 0, 0
    for i, row in enumerate(reader, start=1):
        if i > 2000:
            break
        try:
            date_str = (row.get("date") or "").strip()
            ttype = (row.get("type") or "expense").strip().lower()
            cat_name = (row.get("category") or "").strip()
            amount_raw = (row.get("amount") or "").strip()
            note = (row.get("note") or "").strip()[:200]
            datetime.strptime(date_str, "%Y-%m-%d")
            amount = round(float(amount_raw.replace(",", "")), 2)
            if amount <= 0 or ttype not in ("income", "expense") or not cat_name:
                raise ValueError
            key = cat_name.lower()
            if key not in cats:
                cur = db.execute("INSERT INTO categories (name, type) VALUES (?,?)",
                                 (cat_name, ttype))
                cats[key] = {"id": cur.lastrowid, "name": cat_name, "type": ttype}
            cat = cats[key]
            if cat["type"] != ttype:
                raise ValueError
            db.execute(
                "INSERT INTO transactions (amount,type,category_id,date,note) VALUES (?,?,?,?,?)",
                (amount, ttype, cat["id"], date_str, note))
            inserted += 1
        except (ValueError, KeyError, sqlite3.Error):
            skipped += 1
    db.commit()
    if inserted:
        flash(f"Imported {inserted} transaction(s){f' ({skipped} skipped)' if skipped else ''}.", "success")
    else:
        flash(f"No rows imported ({skipped} skipped). Check CSV format: date,type,category,amount,note.", "error")
    return redirect(url_for("transactions"))


@app.route("/add", methods=["POST"])
def add_transaction():
    amount, cat, date_str, note, err = validate_txn(
        request.form.get("amount", ""), request.form.get("type", "expense"),
        request.form.get("category_id", ""), request.form.get("date", "") or date.today().isoformat(),
        request.form.get("note", ""))
    if err:
        flash(err, "error")
        return redirect(url_for("index"))
    db = get_db()
    db.execute(
        "INSERT INTO transactions (amount, type, category_id, date, note) VALUES (?,?,?,?,?)",
        (amount, request.form.get("type", "expense"), cat["id"], date_str, note),
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
        amount, cat, date_str, note, err = validate_txn(
            request.form.get("amount", ""), request.form.get("type", "expense"),
            request.form.get("category_id", ""), request.form.get("date", ""),
            request.form.get("note", ""))
        if err:
            flash(err, "error")
            return redirect(url_for("edit_transaction", tx_id=tx_id))
        db.execute(
            "UPDATE transactions SET amount=?, type=?, category_id=?, date=?, note=? WHERE id=?",
            (amount, request.form.get("type", "expense"), cat["id"], date_str, note, tx_id),
        )
        db.commit()
        flash("Transaction updated.", "success")
        return redirect(url_for("transactions"))
    return render_template("edit.html", tx=tx, categories=categories)


@app.route("/duplicate/<int:tx_id>", methods=["POST"])
def duplicate_transaction(tx_id):
    db = get_db()
    tx = db.execute("SELECT * FROM transactions WHERE id=?", (tx_id,)).fetchone()
    if not tx:
        flash("Transaction not found.", "error")
        return redirect(url_for("transactions"))
    db.execute(
        "INSERT INTO transactions (amount,type,category_id,date,note) VALUES (?,?,?,?,?)",
        (tx["amount"], tx["type"], tx["category_id"], date.today().isoformat(), tx["note"] or ""),
    )
    db.commit()
    flash("Transaction duplicated for today.", "success")
    return redirect(url_for("transactions"))


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
        name = request.form.get("name", "").strip()[:50]
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
    usage = {r["category_id"]: r["cnt"] for r in db.execute(
        "SELECT category_id, COUNT(*) AS cnt FROM transactions GROUP BY category_id").fetchall()}
    return render_template("categories.html", categories=cats, usage=usage)


@app.route("/categories/edit/<int:cat_id>", methods=["GET", "POST"])
def edit_category(cat_id):
    db = get_db()
    cat = db.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()
    if not cat:
        flash("Category not found.", "error")
        return redirect(url_for("categories"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()[:50]
        if not name:
            flash("Category name is required.", "error")
            return redirect(url_for("edit_category", cat_id=cat_id))
        try:
            db.execute("UPDATE categories SET name=? WHERE id=?", (name, cat_id))
            db.commit()
            flash("Category renamed.", "success")
        except sqlite3.IntegrityError:
            flash(f"Category '{name}' already exists.", "error")
            return redirect(url_for("edit_category", cat_id=cat_id))
        return redirect(url_for("categories"))
    return render_template("edit_category.html", cat=cat)


@app.route("/categories/delete/<int:cat_id>", methods=["POST"])
def delete_category(cat_id):
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) FROM transactions WHERE category_id=?", (cat_id,)).fetchone()[0]
    if count > 0:
        flash(f"Cannot delete: {count} transaction(s) use this category.", "error")
        return redirect(url_for("categories"))
    db.execute("DELETE FROM budgets WHERE category_id=?", (cat_id,))
    db.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    db.commit()
    flash("Category deleted.", "success")
    return redirect(url_for("categories"))


@app.route("/budgets", methods=["GET", "POST"])
def budgets():
    db = get_db()
    if request.method == "POST":
        category_id = request.form.get("category_id", "")
        limit_raw = request.form.get("monthly_limit", "").strip()
        if not category_id.isdigit():
            flash("Select a valid category.", "error")
            return redirect(url_for("budgets"))
        cat = db.execute("SELECT * FROM categories WHERE id=?", (int(category_id),)).fetchone()
        if not cat or cat["type"] != "expense":
            flash("Budgets apply to expense categories.", "error")
            return redirect(url_for("budgets"))
        if not limit_raw:  # clear budget
            db.execute("DELETE FROM budgets WHERE category_id=?", (cat["id"],))
            db.commit()
            flash(f"Budget for '{cat['name']}' removed.", "success")
            return redirect(url_for("budgets"))
        try:
            limit = round(float(limit_raw.replace(",", "")), 2)
            if limit <= 0:
                raise ValueError
        except ValueError:
            flash("Limit must be a positive number.", "error")
            return redirect(url_for("budgets"))
        db.execute(
            """INSERT INTO budgets (category_id, monthly_limit) VALUES (?,?)
               ON CONFLICT(category_id) DO UPDATE SET monthly_limit=excluded.monthly_limit""",
            (cat["id"], limit))
        db.commit()
        flash(f"Budget for '{cat['name']}' set to {CURRENCY}{format_inr(limit)}/month.", "success")
        return redirect(url_for("budgets"))
    y, m = date.today().year, date.today().month
    month_str = request.args.get("month", f"{y}-{m:02d}")
    y, m = parse_month(month_str)
    month_str = f"{y}-{m:02d}"
    expense_cats = db.execute(
        "SELECT * FROM categories WHERE type='expense' ORDER BY name").fetchall()
    limits = {r["category_id"]: r["monthly_limit"] for r in
              db.execute("SELECT * FROM budgets").fetchall()}
    status = budget_status(y, m)
    total_limit = sum(b["limit"] for b in status)
    total_spent = sum(b["spent"] for b in status)
    return render_template("budgets.html", expense_cats=expense_cats, limits=limits,
                           status=status, month=month_str,
                           total_limit=total_limit, total_spent=total_spent)


@app.route("/budgets/delete/<int:category_id>", methods=["POST"])
def delete_budget(category_id):
    db = get_db()
    db.execute("DELETE FROM budgets WHERE category_id=?", (category_id,))
    db.commit()
    flash("Budget removed.", "success")
    return redirect(url_for("budgets"))


@app.route("/reports")
def reports():
    db = get_db()
    view = request.args.get("view", "daily")
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
            FROM transactions WHERE substr(date,1,4)=? GROUP BY month ORDER BY month
            """,
            (str(year),),
        ).fetchall()
        months = [f"{year}-{mm:02d}" for mm in range(1, 13)]
        data = {r["month"]: dict(r) for r in rows}
        monthly = []
        for mm in months:
            d = data.get(mm, {"income": 0, "expense": 0})
            monthly.append({"month": mm, "income": d["income"] or 0,
                            "expense": d["expense"] or 0,
                            "savings": (d["income"] or 0) - (d["expense"] or 0)})
        tot_inc = sum(x["income"] for x in monthly)
        tot_exp = sum(x["expense"] for x in monthly)
        max_month = max([max(x["income"], x["expense"]) for x in monthly] + [0])
        cat_rows = [dict(c) for c in db.execute(
            """SELECT c.name, c.type, SUM(t.amount) AS total
               FROM transactions t JOIN categories c ON t.category_id=c.id
               WHERE substr(t.date,1,4)=? GROUP BY c.id ORDER BY total DESC""",
            (str(year),)).fetchall()]
        max_cat = max([c["total"] or 0 for c in cat_rows] + [0])
        years = [r[0] for r in db.execute(
            "SELECT DISTINCT substr(date,1,4) AS y FROM transactions ORDER BY y DESC").fetchall()]
        if str(today.year) not in years:
            years = [str(today.year)] + years
        savings_rate = round((tot_inc - tot_exp) / tot_inc * 100, 1) if tot_inc else 0
        return render_template("reports.html", view=view, year=year, years=years,
                               monthly=monthly, tot_inc=tot_inc, tot_exp=tot_exp,
                               max_month=max_month, max_cat=max_cat, cat_rows=cat_rows,
                               period_label=str(year), savings_rate=savings_rate)

    month_str = request.args.get("month", today.strftime("%Y-%m"))
    y, m = parse_month(month_str)
    month_str = f"{y}-{m:02d}"
    s, e = month_bounds(y, m)
    rows = db.execute(
        """SELECT date, SUM(CASE WHEN type='income' THEN amount ELSE 0 END) AS income,
                  SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) AS expense
           FROM transactions WHERE date>=? AND date<? GROUP BY date ORDER BY date""",
        (s, e),
    ).fetchall()
    daily = [{"date": r["date"], "income": r["income"] or 0, "expense": r["expense"] or 0,
              "savings": (r["income"] or 0) - (r["expense"] or 0)} for r in rows]
    tot_inc = sum(d["income"] for d in daily)
    tot_exp = sum(d["expense"] for d in daily)
    max_day = max([max(d["income"], d["expense"]) for d in daily] + [0])
    cat_rows = [dict(c) for c in db.execute(
        """SELECT c.name, c.type, SUM(t.amount) AS total
           FROM transactions t JOIN categories c ON t.category_id=c.id
           WHERE t.date>=? AND t.date<? GROUP BY c.id ORDER BY total DESC""",
        (s, e)).fetchall()]
    max_cat = max([c["total"] or 0 for c in cat_rows] + [0])
    savings_rate = round((tot_inc - tot_exp) / tot_inc * 100, 1) if tot_inc else 0
    return render_template("reports.html", view=view, month=month_str,
                           daily=daily, tot_inc=tot_inc, tot_exp=tot_exp,
                           max_day=max_day, max_cat=max_cat,
                           cat_rows=cat_rows, period_label=month_str,
                           savings_rate=savings_rate)


# ---------- JSON API ----------
@app.route("/api/summary")
def api_summary():
    db = get_db()
    month = request.args.get("month", "")
    year = request.args.get("year", "")
    if month:
        y, m = parse_month(month)
        s, e = month_bounds(y, m)
        label = f"{y}-{m:02d}"
    elif year and year.isdigit():
        s, e, label = f"{year}-01-01", f"{int(year)+1}-01-01", year
        filt = "substr(t.date,1,4)=?"
        filt_args = (year,)
        rows = db.execute(
            f"""SELECT c.name, c.type, SUM(t.amount) AS total FROM transactions t
                JOIN categories c ON t.category_id=c.id WHERE {filt} GROUP BY c.id ORDER BY total DESC""",
            filt_args).fetchall()
        tot = db.execute(
            f"""SELECT SUM(CASE WHEN type='income' THEN amount ELSE 0 END),
                        SUM(CASE WHEN type='expense' THEN amount ELSE 0 END)
                FROM transactions t WHERE {filt}""", filt_args).fetchone()
        inc, exp = (tot[0] or 0), (tot[1] or 0)
        return jsonify(period=label, income=inc, expense=exp, savings=inc - exp,
                       by_category=[dict(r) for r in rows])
    else:
        today = date.today()
        s, e = month_bounds(today.year, today.month)
        label = f"{today.year}-{today.month:02d}"
    rows = db.execute(
        """SELECT c.name, c.type, SUM(t.amount) AS total FROM transactions t
           JOIN categories c ON t.category_id=c.id
           WHERE t.date>=? AND t.date<? GROUP BY c.id ORDER BY total DESC""",
        (s, e)).fetchall()
    tot = db.execute(
        """SELECT SUM(CASE WHEN type='income' THEN amount ELSE 0 END),
                  SUM(CASE WHEN type='expense' THEN amount ELSE 0 END)
           FROM transactions WHERE date>=? AND date<?""", (s, e)).fetchone()
    inc, exp = (tot[0] or 0), (tot[1] or 0)
    return jsonify(period=label, income=inc, expense=exp, savings=inc - exp,
                   by_category=[dict(r) for r in rows])


@app.route("/api/transactions")
def api_transactions():
    try:
        limit = min(int(request.args.get("limit", 50)), 500)
    except ValueError:
        limit = 50
    f_type = request.args.get("type", "all")
    where, args = "WHERE 1=1", []
    if f_type in ("income", "expense"):
        where += " AND t.type=?"
        args.append(f_type)
    rows = get_db().execute(
        f"""SELECT t.id, t.date, t.type, c.name AS category, t.amount, t.note
            FROM transactions t JOIN categories c ON t.category_id=c.id
            {where} ORDER BY t.date DESC, t.id DESC LIMIT ?""", args + [limit]).fetchall()
    return jsonify([dict(r) for r in rows])


# Ensure tables exist on import too (needed when served by gunicorn,
# where the __main__ block below never runs). init_db is idempotent.
init_db()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
