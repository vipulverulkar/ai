"""
Daily Expense Tracker - Desktop App
====================================
Standalone desktop app (like MS Access .accdb, but using SQLite .db single file).
No server needed. Just run:  python expense_tracker.py

Features:
- CRUD for Income / Expense transactions
- Category management (separate Income & Expense categories)
- Dashboard with monthly summary
- Daily report + Monthly report with charts + CSV export
- Graphs tab: category pie chart, monthly trend line, yearly bar chart
- Search / filter, SQLite standalone database file (expenses.db)
Stdlib only: tkinter + sqlite3 + csv (no pip install needed).
"""

import csv
import calendar
import contextlib
import os
import sqlite3
from datetime import date, datetime, timedelta
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ---------------------------------------------------------------- DB layer
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "expenses.db")

DEFAULT_INCOME_CATS = [
    "Salary",
    "Business",
    "Freelance",
    "Interest",
    "Gift Received",
    "Other Income",
]
DEFAULT_EXPENSE_CATS = [
    "Food",
    "Groceries",
    "Rent",
    "Transport",
    "Utilities",
    "Shopping",
    "Health",
    "Education",
    "Entertainment",
    "Savings",
    "Other Expense",
]


def get_conn():
    """Create a new SQLite connection with sane pragmas.

    WAL mode improves concurrent read/write and crash safety for a
    single-file desktop DB. foreign_keys is enforced per-connection.
    timeout=5s avoids 'database is locked' on quick successive writes.
    """
    conn = sqlite3.connect(
        DB_PATH, timeout=5.0, isolation_level=None, detect_types=sqlite3.PARSE_DECLTYPES
    )
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=5000")
        # use WAL checkpoint periodically; safe default
    except sqlite3.OperationalError:
        pass
    return conn


def _txn_has_category_id(cur):
    cur.execute("PRAGMA table_info(transactions)")
    cols = [r[1] for r in cur.fetchall()]
    return "category_id" in cols


def _get_category_id(cur, name, txn_type):
    """Lookup category id for (name, type) or None."""
    row = cur.execute(
        "SELECT id FROM categories WHERE name=? AND type=?", (name, txn_type)
    ).fetchone()
    return row[0] if row else None


def init_db():
    with contextlib.closing(get_conn()) as conn:
        # enable write transaction explicitly
        # (isolation_level=None => autocommit off for explicit BEGIN)
        conn.execute("BEGIN")
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id   INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL CHECK(type IN ('Income','Expense')),
                UNIQUE(name, type)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                date     TEXT NOT NULL,          -- YYYY-MM-DD
                type     TEXT NOT NULL CHECK(type IN ('Income','Expense')),
                category TEXT NOT NULL,
                amount   REAL NOT NULL CHECK(amount > 0),
                note     TEXT DEFAULT ''
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_txn_type ON transactions(type)")
        # --- migration: add category_id FK column (non-breaking) ---------
        if not _txn_has_category_id(cur):
            cur.execute(
                "ALTER TABLE transactions ADD COLUMN category_id INTEGER "
                "REFERENCES categories(id) ON UPDATE CASCADE ON DELETE SET NULL"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_txn_category_id " "ON transactions(category_id)"
            )
            # backfill category_id where possible
            for cid, name, ctype in cur.execute("SELECT id, name, type FROM categories").fetchall():
                cur.execute(
                    "UPDATE transactions SET category_id=? "
                    "WHERE category=? AND type=? AND category_id IS NULL",
                    (cid, name, ctype),
                )
        else:
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_txn_category_id " "ON transactions(category_id)"
            )
        # seed categories once
        cur.execute("SELECT COUNT(*) FROM categories")
        if cur.fetchone()[0] == 0:
            for c in DEFAULT_INCOME_CATS:
                cur.execute("INSERT INTO categories(name,type) VALUES(?, 'Income')", (c,))
            for c in DEFAULT_EXPENSE_CATS:
                cur.execute("INSERT INTO categories(name,type) VALUES(?, 'Expense')", (c,))
        conn.commit()


def db_vacuum():
    """Compact the DB file (like MS Access Compact & Repair)."""
    with contextlib.closing(get_conn()) as conn:
        conn.execute("VACUUM")


def db_integrity_check():
    """Return integrity_check result ('ok' if healthy)."""
    with contextlib.closing(get_conn()) as conn:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        return row[0] if row else "ok"


# ---- CRUD helpers ---------------------------------------------------------
def _validate_date(s):
    datetime.strptime(s, "%Y-%m-%d")
    return s


def db_add_txn(txn_date, txn_type, category, amount, note=""):
    _validate_date(txn_date)
    if txn_type not in ("Income", "Expense"):
        raise ValueError("type must be Income or Expense")
    if amount is None or float(amount) <= 0:
        raise ValueError("amount must be > 0")
    category = category.strip()
    if not category:
        raise ValueError("category required")
    with contextlib.closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        try:
            cid = _get_category_id(cur, category, txn_type)
            if _txn_has_category_id(cur):
                cur.execute(
                    "INSERT INTO transactions(date,type,category,category_id,amount,note) "
                    "VALUES(?,?,?,?,?,?)",
                    (txn_date, txn_type, category, cid, float(amount), note.strip()),
                )
            else:
                cur.execute(
                    "INSERT INTO transactions(date,type,category,amount,note) VALUES(?,?,?,?,?)",
                    (txn_date, txn_type, category, float(amount), note.strip()),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def db_update_txn(txn_id, txn_date, txn_type, category, amount, note=""):
    _validate_date(txn_date)
    if txn_type not in ("Income", "Expense"):
        raise ValueError("type must be Income or Expense")
    if float(amount) <= 0:
        raise ValueError("amount must be > 0")
    category = category.strip()
    if not category:
        raise ValueError("category required")
    with contextlib.closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        try:
            if _txn_has_category_id(cur):
                cid = _get_category_id(cur, category, txn_type)
                cur.execute(
                    "UPDATE transactions SET date=?, type=?, category=?, "
                    "category_id=?, amount=?, note=? WHERE id=?",
                    (txn_date, txn_type, category, cid, float(amount), note.strip(), txn_id),
                )
            else:
                cur.execute(
                    "UPDATE transactions SET date=?,type=?,category=?,amount=?,note=? WHERE id=?",
                    (txn_date, txn_type, category, float(amount), note.strip(), txn_id),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def db_delete_txn(txn_id):
    with contextlib.closing(get_conn()) as conn:
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def db_query_txns(date_from=None, date_to=None, txn_type="All", category="All", search=""):
    with contextlib.closing(get_conn()) as conn:
        q = "SELECT id,date,type,category,amount,note FROM transactions WHERE 1=1"
        params = []
        if date_from:
            _validate_date(date_from)
            q += " AND date >= ?"
            params.append(date_from)
        if date_to:
            _validate_date(date_to)
            q += " AND date <= ?"
            params.append(date_to)
        if txn_type in ("Income", "Expense"):
            q += " AND type = ?"
            params.append(txn_type)
        if category != "All":
            q += " AND category = ?"
            params.append(category)
        if search.strip():
            # escape LIKE wildcards so search is literal, then wrap with %
            esc = search.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            q += (
                " AND (category LIKE ? ESCAPE '\\' OR note LIKE ? ESCAPE '\\'"
                " OR CAST(amount AS TEXT) LIKE ?)"
            )
            s = f"%{esc}%"
            params += [s, s, s]
        q += " ORDER BY date DESC, id DESC"
        rows = conn.execute(q, params).fetchall()
        return rows


def db_totals(date_from=None, date_to=None):
    """Optimized: single SQL aggregation instead of fetching all rows."""
    with contextlib.closing(get_conn()) as conn:
        q = (
            "SELECT "
            "  SUM(CASE WHEN type='Income' THEN amount ELSE 0 END),"
            "  SUM(CASE WHEN type='Expense' THEN amount ELSE 0 END)"
            " FROM transactions WHERE 1=1"
        )
        params = []
        if date_from:
            _validate_date(date_from)
            q += " AND date >= ?"
            params.append(date_from)
        if date_to:
            _validate_date(date_to)
            q += " AND date <= ?"
            params.append(date_to)
        inc, exp = conn.execute(q, params).fetchone()
        inc = float(inc or 0)
        exp = float(exp or 0)
        return inc, exp, inc - exp


def db_category_summary(date_from=None, date_to=None, txn_type="Expense"):
    with contextlib.closing(get_conn()) as conn:
        q = "SELECT category, SUM(amount) FROM transactions WHERE type=? "
        params = [txn_type]
        if date_from:
            _validate_date(date_from)
            q += " AND date >= ?"
            params.append(date_from)
        if date_to:
            _validate_date(date_to)
            q += " AND date <= ?"
            params.append(date_to)
        q += " GROUP BY category ORDER BY SUM(amount) DESC"
        rows = conn.execute(q, params).fetchall()
        return rows


def db_daily_summary(txn_date):
    return db_totals(txn_date, txn_date)


def db_month_bounds(year, month):
    first = f"{year:04d}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    last = f"{year:04d}-{month:02d}-{last_day:02d}"
    return first, last


def db_daily_series(year, month):
    """Return (income_per_day, expense_per_day) lists, one entry per day of month."""
    d1, d2 = db_month_bounds(year, month)
    with contextlib.closing(get_conn()) as conn:
        per_day = conn.execute(
            """SELECT date,
                      SUM(CASE WHEN type='Income' THEN amount ELSE 0 END),
                      SUM(CASE WHEN type='Expense' THEN amount ELSE 0 END)
               FROM transactions WHERE date BETWEEN ? AND ?
               GROUP BY date""",
            (d1, d2),
        ).fetchall()
        have = {r[0]: (r[1] or 0, r[2] or 0) for r in per_day}
    ndays = calendar.monthrange(year, month)[1]
    inc, exp = [], []
    for day in range(1, ndays + 1):
        i_, e_ = have.get(f"{year:04d}-{month:02d}-{day:02d}", (0, 0))
        inc.append(i_)
        exp.append(e_)
    return inc, exp


def db_yearly_summary(year):
    """Return [(month, income, expense), ...] for Jan..Dec of the given year."""
    with contextlib.closing(get_conn()) as conn:
        rows = conn.execute(
            """SELECT CAST(substr(date, 6, 2) AS INTEGER),
                      SUM(CASE WHEN type='Income' THEN amount ELSE 0 END),
                      SUM(CASE WHEN type='Expense' THEN amount ELSE 0 END)
               FROM transactions WHERE substr(date, 1, 4) = ?
               GROUP BY substr(date, 6, 2)""",
            (f"{year:04d}",),
        ).fetchall()
        have = {r[0]: (r[1] or 0, r[2] or 0) for r in rows}
    return [(m, *have.get(m, (0, 0))) for m in range(1, 13)]


def db_get_categories(txn_type=None):
    with contextlib.closing(get_conn()) as conn:
        if txn_type:
            rows = conn.execute(
                "SELECT id,name,type FROM categories WHERE type=? ORDER BY name", (txn_type,)
            ).fetchall()
        else:
            rows = conn.execute("SELECT id,name,type FROM categories ORDER BY type,name").fetchall()
        return rows


def db_add_category(name, txn_type):
    name = name.strip()
    if not name:
        return False
    if txn_type not in ("Income", "Expense"):
        return False
    with contextlib.closing(get_conn()) as conn:
        try:
            conn.execute("BEGIN")
            conn.execute("INSERT INTO categories(name,type) VALUES(?,?)", (name, txn_type))
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            conn.rollback()
            return False


def db_delete_category(cat_id):
    with contextlib.closing(get_conn()) as conn:
        conn.execute("BEGIN")
        try:
            conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
            # keep history: null out category_id for orphans (if column exists)
            cur = conn.cursor()
            if _txn_has_category_id(cur):
                conn.execute(
                    "UPDATE transactions SET category_id=NULL WHERE category_id=?", (cat_id,)
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def db_count_txns_for_category(name, txn_type):
    with contextlib.closing(get_conn()) as conn:
        # count via denormalized text (authoritative) + category_id if present
        n = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE category=? AND type=?", (name, txn_type)
        ).fetchone()[0]
        return n


def db_update_category(cat_id, new_name, new_type, update_txns=True):
    """Rename / re-type a category. Optionally retag matching transactions too.
    Returns (True, n_updated_txns) or (False, error_message)."""
    new_name = new_name.strip()
    if not new_name:
        return False, "Name cannot be empty."
    if new_type not in ("Income", "Expense"):
        return False, "Type must be Income or Expense."
    with contextlib.closing(get_conn()) as conn:
        cur = conn.cursor()
        cur.execute("BEGIN")
        try:
            old = cur.execute("SELECT name, type FROM categories WHERE id=?", (cat_id,)).fetchone()
            if not old:
                conn.rollback()
                return False, "Category not found."
            old_name, old_type = old
            if (old_name, old_type) == (new_name, new_type):
                conn.rollback()
                return True, 0
            dup = cur.execute(
                "SELECT id FROM categories WHERE name=? AND type=? AND id<>?",
                (new_name, new_type, cat_id),
            ).fetchone()
            if dup:
                conn.rollback()
                return False, f"'{new_name}' already exists under {new_type}."
            cur.execute(
                "UPDATE categories SET name=?, type=? WHERE id=?", (new_name, new_type, cat_id)
            )
            n = 0
            if update_txns:
                has_cid = _txn_has_category_id(cur)
                if has_cid:
                    cur.execute(
                        "UPDATE transactions SET category=?, type=?, category_id=? "
                        "WHERE category=? AND type=?",
                        (new_name, new_type, cat_id, old_name, old_type),
                    )
                else:
                    cur.execute(
                        "UPDATE transactions SET category=?, type=? " "WHERE category=? AND type=?",
                        (new_name, new_type, old_name, old_type),
                    )
                n = cur.rowcount
            conn.commit()
            return True, n
        except Exception as e:
            conn.rollback()
            return False, str(e)


# ---------------------------------------------------------------- App UI
class ExpenseApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Daily Expense Tracker")
        self.geometry("1080x680")
        self.minsize(960, 600)
        self._style()
        self._build_layout()
        self.refresh_all()

    # -- styling ----------------------------------------------------------
    def _style(self):
        # Modern light theme — inspired by Linear / Stripe dashboards
        BG = "#F1F5F9"  # slate-100 app background
        CARD_BG = "#FFFFFF"
        BORDER = "#E2E8F0"  # slate-200
        TEXT_PRIMARY = "#0F172A"  # slate-900
        TEXT_SECONDARY = "#475569"  # slate-600
        TEXT_MUTED = "#94A3B8"  # slate-400
        PRIMARY = "#2563EB"  # blue-600
        PRIMARY_DARK = "#1D4ED8"
        SUCCESS = "#059669"
        DANGER = "#DC2626"

        self.configure(bg=BG)

        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        # --- base ---
        style.configure(".", background=BG, foreground=TEXT_PRIMARY, font=("Segoe UI", 9))
        style.configure("TFrame", background=BG)
        style.configure("TLabel", background=BG, foreground=TEXT_PRIMARY, font=("Segoe UI", 9))
        style.configure("TSeparator", background=BORDER)

        # --- notebook ---
        style.configure(
            "TNotebook",
            background=BG,
            borderwidth=0,
            tabmargins=[0, 0, 0, 0],
            padding=0,
        )
        style.configure(
            "TNotebook.Tab",
            padding=(18, 10),
            font=("Segoe UI", 9, "bold"),
            background="#FFFFFF",
            foreground="#64748B",
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", "#FFFFFF"), ("active", "#F8FAFC")],
            foreground=[("selected", PRIMARY), ("active", TEXT_PRIMARY)],
            padding=[("selected", (20, 11))],
        )
        # add bottom border to selected tab via mapping not perfect in clam;
        # we also set tab lightcolor/darkcolor to mimic
        style.configure("TNotebook.Tab", focuscolor=BG)

        # --- cards ---
        style.configure(
            "Card.TFrame",
            background=CARD_BG,
            relief="solid",
            borderwidth=1,
            bordercolor=BORDER,
        )
        style.configure("Card.TLabel", background=CARD_BG)
        style.configure(
            "CardTitle.TLabel",
            background=CARD_BG,
            font=("Segoe UI", 8, "bold"),
            foreground=TEXT_MUTED,
        )
        style.configure(
            "CardValue.TLabel",
            background=CARD_BG,
            font=("Segoe UI", 20, "bold"),
            foreground=TEXT_PRIMARY,
        )
        style.configure(
            "CardSub.TLabel",
            background=CARD_BG,
            font=("Segoe UI", 8),
            foreground=TEXT_SECONDARY,
        )
        style.configure("CardAccent.TFrame", background=PRIMARY, relief="flat", borderwidth=0)

        # --- header ---
        style.configure("Header.TFrame", background="#FFFFFF", relief="flat")
        style.configure(
            "Header.TLabel",
            background="#FFFFFF",
            font=("Segoe UI", 15, "bold"),
            foreground=TEXT_PRIMARY,
        )
        style.configure(
            "SubHeader.TLabel",
            background="#FFFFFF",
            font=("Segoe UI", 8),
            foreground=TEXT_SECONDARY,
        )
        style.configure(
            "HeaderSub.TLabel",
            background="#FFFFFF",
            font=("Segoe UI", 7),
            foreground=TEXT_MUTED,
        )

        # --- buttons ---
        style.configure(
            "Accent.TButton",
            background=PRIMARY,
            foreground="white",
            font=("Segoe UI", 9, "bold"),
            padding=(16, 8),
            borderwidth=0,
            relief="flat",
            focusthickness=0,
            focuscolor=PRIMARY,
        )
        style.map(
            "Accent.TButton",
            background=[("active", PRIMARY_DARK), ("pressed", "#1E3A8A"), ("disabled", "#CBD5E1")],
            foreground=[("disabled", "#94A3B8")],
        )
        style.configure(
            "Secondary.TButton",
            background="#FFFFFF",
            foreground="#334155",
            font=("Segoe UI", 9),
            padding=(10, 7),
            borderwidth=1,
            relief="solid",
            bordercolor=BORDER,
        )
        style.map(
            "Secondary.TButton",
            background=[("active", "#F8FAFC"), ("pressed", "#F1F5F9")],
            bordercolor=[("active", "#CBD5E1")],
        )
        style.configure(
            "Ghost.TButton",
            background=BG,
            foreground=TEXT_SECONDARY,
            font=("Segoe UI", 9),
            padding=(8, 7),
            borderwidth=0,
            relief="flat",
        )
        style.map(
            "Ghost.TButton",
            background=[("active", "#E2E8F0")],
            foreground=[("active", TEXT_PRIMARY)],
        )
        style.configure(
            "Danger.TButton",
            background="#FEF2F2",
            foreground=DANGER,
            font=("Segoe UI", 9, "bold"),
            padding=(10, 7),
            borderwidth=1,
            relief="solid",
            bordercolor="#FECACA",
        )
        style.map("Danger.TButton", background=[("active", "#FEE2E2")])
        style.configure(
            "Success.TButton",
            background="#ECFDF5",
            foreground=SUCCESS,
            font=("Segoe UI", 9, "bold"),
            padding=(10, 7),
            borderwidth=1,
            relief="solid",
            bordercolor="#A7F3D0",
        )
        style.map("Success.TButton", background=[("active", "#D1FAE5")])

        # --- entries ---
        style.configure(
            "TEntry",
            fieldbackground="#FFFFFF",
            background="#FFFFFF",
            foreground=TEXT_PRIMARY,
            bordercolor="#CBD5E1",
            lightcolor="#CBD5E1",
            darkcolor="#CBD5E1",
            borderwidth=1,
            relief="solid",
            padding=6,
            insertcolor=TEXT_PRIMARY,
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", PRIMARY)],
            lightcolor=[("focus", PRIMARY)],
            darkcolor=[("focus", PRIMARY)],
        )
        style.configure(
            "TCombobox",
            fieldbackground="#FFFFFF",
            background="#FFFFFF",
            foreground=TEXT_PRIMARY,
            bordercolor="#CBD5E1",
            arrowcolor=TEXT_SECONDARY,
            padding=5,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", "#FFFFFF")],
            bordercolor=[("focus", PRIMARY)],
            selectbackground=[("readonly", "#FFFFFF")],
            selectforeground=[("readonly", TEXT_PRIMARY)],
        )
        style.configure(
            "TSpinbox",
            fieldbackground="#FFFFFF",
            background="#FFFFFF",
            foreground=TEXT_PRIMARY,
            bordercolor="#CBD5E1",
            padding=5,
        )

        # --- treeview ---
        style.configure(
            "Treeview",
            background="#FFFFFF",
            fieldbackground="#FFFFFF",
            foreground=TEXT_PRIMARY,
            bordercolor=BORDER,
            borderwidth=1,
            relief="solid",
            rowheight=30,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Treeview.Heading",
            background="#F8FAFC",
            foreground=TEXT_SECONDARY,
            font=("Segoe UI", 8, "bold"),
            relief="flat",
            borderwidth=0,
            padding=(10, 8),
        )
        style.map(
            "Treeview",
            background=[("selected", "#DBEAFE")],
            foreground=[("selected", PRIMARY_DARK)],
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#F1F5F9")],
            foreground=[("active", TEXT_PRIMARY)],
        )

        # --- labelframe ---
        style.configure(
            "TLabelframe",
            background="#FFFFFF",
            bordercolor=BORDER,
            borderwidth=1,
            relief="solid",
            padding=0,
        )
        style.configure(
            "TLabelframe.Label",
            background="#FFFFFF",
            foreground=TEXT_PRIMARY,
            font=("Segoe UI", 9, "bold"),
            padding=(6, 2),
        )
        style.configure(
            "CardHeader.TLabelframe.Label",
            background="#FFFFFF",
            foreground=TEXT_SECONDARY,
            font=("Segoe UI", 8, "bold"),
        )

        # --- scrollbar ---
        style.configure(
            "Vertical.TScrollbar",
            background=BG,
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=TEXT_MUTED,
            relief="flat",
            borderwidth=0,
            groovewidth=0,
        )
        style.map(
            "Vertical.TScrollbar",
            background=[("active", "#CBD5E1")],
            arrowcolor=[("active", TEXT_SECONDARY)],
        )

        # keep reference for use in canvas drawing etc.
        self._palette = {
            "BG": BG,
            "CARD_BG": CARD_BG,
            "BORDER": BORDER,
            "TEXT_PRIMARY": TEXT_PRIMARY,
            "TEXT_SECONDARY": TEXT_SECONDARY,
            "TEXT_MUTED": TEXT_MUTED,
            "PRIMARY": PRIMARY,
            "PRIMARY_DARK": PRIMARY_DARK,
            "SUCCESS": SUCCESS,
            "DANGER": DANGER,
        }

    # -- layout -----------------------------------------------------------
    def _build_layout(self):
        # Header — white, with subtle border & shadow
        header = ttk.Frame(self, style="Header.TFrame", padding=(18, 14, 18, 12))
        header.pack(fill="x", padx=0, pady=0)
        # left: branding
        left = ttk.Frame(header, style="Header.TFrame")
        left.pack(side="left", fill="y")
        # logo badge
        logo = tk.Canvas(left, width=38, height=38, bg="#FFFFFF", highlightthickness=0)
        logo.pack(side="left", padx=(0, 12))
        # draw rounded badge with icon
        logo.create_oval(2, 2, 36, 36, fill="#EFF6FF", outline="#DBEAFE", width=1)
        logo.create_text(19, 19, text="₹", font=("Segoe UI", 16, "bold"), fill="#2563EB")
        # title stack
        titles = ttk.Frame(left, style="Header.TFrame")
        titles.pack(side="left", fill="y")
        ttk.Label(titles, text="Daily Expense Tracker", style="Header.TLabel").pack(anchor="w")
        # subtitle with DB pill
        sub = ttk.Frame(titles, style="Header.TFrame")
        sub.pack(anchor="w", pady=(1, 0))
        ttk.Label(sub, text="Personal finance •", style="SubHeader.TLabel").pack(side="left")
        # DB pill
        db_short = os.path.basename(DB_PATH)
        pill = tk.Canvas(sub, height=18, bg="#FFFFFF", highlightthickness=0)
        pill.pack(side="left", padx=(6, 0))

        # pill will be drawn after idle
        def _draw_pill():
            try:
                w = 12 + len(db_short) * 6
                pill.config(width=w)
                pill.delete("all")
                pill.create_oval(0, 0, 18, 18, fill="#F1F5F9", outline="#E2E8F0")
                pill.create_oval(w - 18, 0, w, 18, fill="#F1F5F9", outline="#E2E8F0")
                pill.create_rectangle(9, 0, w - 9, 18, fill="#F1F5F9", outline="#F1F5F9")
                pill.create_rectangle(9, 0, w - 9, 1, fill="#E2E8F0", outline="#E2E8F0")
                pill.create_rectangle(9, 17, w - 9, 18, fill="#E2E8F0", outline="#E2E8F0")
                pill.create_text(w // 2, 9, text=db_short, font=("Segoe UI", 7), fill="#475569")
            except Exception:
                pass

        pill.after(50, _draw_pill)

        # right: actions
        right = ttk.Frame(header, style="Header.TFrame")
        right.pack(side="right", fill="y")
        ttk.Button(
            right, text="🔧  DB Tools", style="Secondary.TButton", command=self.open_db_tools
        ).pack(side="right", padx=(8, 0), ipady=1)
        ttk.Button(
            right,
            text="＋  Add Transaction",
            style="Accent.TButton",
            command=self.open_txn_dialog,
        ).pack(side="right", ipady=1)

        # subtle separator
        sep = ttk.Separator(self, orient="horizontal")
        sep.pack(fill="x", padx=0)

        # Notebook — with outer padding and card-like tabs
        nb_wrap = ttk.Frame(self, padding=(12, 10, 12, 12))
        nb_wrap.pack(fill="both", expand=True)
        self.nb = ttk.Notebook(nb_wrap)
        self.nb.pack(fill="both", expand=True)

        self.tab_dash = ttk.Frame(self.nb, padding=14)
        self.tab_txn = ttk.Frame(self.nb, padding=14)
        self.tab_cat = ttk.Frame(self.nb, padding=14)
        self.tab_rep = ttk.Frame(self.nb, padding=14)
        self.tab_graph = ttk.Frame(self.nb, padding=14)
        self.nb.add(self.tab_dash, text="  📊  Dashboard  ")
        self.nb.add(self.tab_txn, text="  🧾  Transactions  ")
        self.nb.add(self.tab_cat, text="  🗂  Categories  ")
        self.nb.add(self.tab_rep, text="  📅  Reports  ")
        self.nb.add(self.tab_graph, text="  📈  Graphs  ")

        self._build_dashboard()
        self._build_transactions()
        self._build_categories()
        self._build_reports()
        self._build_graphs()

        # Footer status bar
        footer = ttk.Frame(self, padding=(14, 6, 14, 7))
        footer.pack(fill="x", side="bottom")
        # subtle top border via separator
        foot_sep = tk.Canvas(footer, height=1, bg="#F1F5F9", highlightthickness=0)
        foot_sep.place(relx=0, rely=0, relwidth=1, height=1)
        # will be configured in refresh_all
        self.footer_var = tk.StringVar(value="Ready • DB: " + DB_PATH)
        ttk.Label(
            footer, textvariable=self.footer_var, font=("Segoe UI", 7), foreground="#64748B"
        ).pack(side="left")
        # version / hint
        ttk.Label(
            footer,
            text="Stdlib only • SQLite WAL • F1 Help",
            font=("Segoe UI", 7),
            foreground="#94A3B8",
        ).pack(side="right")
        self.bind(
            "<F1>",
            lambda e: messagebox.showinfo(
                "Help",
                (
                    "Shortcuts:\n"
                    "• Double-click transaction to edit\n"
                    "• Double-click category to rename\n"
                    "• Ctrl+N: Add transaction"
                ),
            ),
        )

    # ================= DASHBOARD =================
    def _build_dashboard(self):
        # month selector — card-like toolbar
        bar = tk.Canvas(
            self.tab_dash,
            bg="#FFFFFF",
            highlightthickness=1,
            highlightbackground="#E2E8F0",
            height=46,
        )
        bar.pack(fill="x", pady=(0, 12))
        bar.create_text(16, 23, text="📅", font=("Segoe UI", 11), anchor="w")
        bar.create_text(
            38, 23, text="Period", font=("Segoe UI", 8, "bold"), fill="#475569", anchor="w"
        )
        # embed controls inside canvas via window
        ctrl = ttk.Frame(bar, style="Card.TFrame")
        bar.create_window(92, 23, window=ctrl, anchor="w")
        today = date.today()
        self.dash_year = tk.IntVar(value=today.year)
        self.dash_month = tk.IntVar(value=today.month)
        ttk.Spinbox(
            ctrl,
            from_=2000,
            to=2100,
            width=6,
            textvariable=self.dash_year,
            command=self.refresh_dashboard,
        ).pack(side="left", padx=2)
        ttk.Label(ctrl, text=" / ", foreground="#94A3B8").pack(side="left")
        ttk.Spinbox(
            ctrl,
            from_=1,
            to=12,
            width=4,
            textvariable=self.dash_month,
            command=self.refresh_dashboard,
        ).pack(side="left", padx=2)
        # also react to typed input (Spinbox command only fires on arrow clicks)
        self.dash_year.trace_add("write", lambda *_: self.after(400, self._safe_dashboard_refresh))
        self.dash_month.trace_add("write", lambda *_: self.after(400, self._safe_dashboard_refresh))
        ttk.Button(
            ctrl,
            text="This Month",
            style="Secondary.TButton",
            command=lambda: (
                self.dash_year.set(date.today().year),
                self.dash_month.set(date.today().month),
                self.refresh_dashboard(),
            ),
        ).pack(side="left", padx=(8, 0))
        # refresh on right of canvas
        right_ctrl = ttk.Frame(bar, style="Card.TFrame")
        bar.create_window(860, 23, window=right_ctrl, anchor="e")
        ttk.Button(
            right_ctrl, text="↻  Refresh", style="Ghost.TButton", command=self.refresh_all
        ).pack()

        # Cards — 4 metrics with icon badges + accent top
        cards = ttk.Frame(self.tab_dash)
        cards.pack(fill="x", pady=(0, 12))
        self.card_vars = {}
        self.card_sub_vars = {}
        card_defs = [
            ("inc", "Income", "#059669", "#ECFDF5", "↑", "Total credited"),
            ("exp", "Expense", "#DC2626", "#FEF2F2", "↓", "Total debited"),
            ("bal", "Balance", "#2563EB", "#EFF6FF", "◆", "Net remaining"),
            ("rate", "Savings", "#7C3AED", "#F5F3FF", "%", "Savings rate"),
        ]
        for key, title, color, bg, icon, sub in card_defs:
            outer = tk.Canvas(
                cards, bg="#FFFFFF", highlightthickness=1, highlightbackground="#E2E8F0", height=92
            )
            outer.pack(side="left", fill="x", expand=True, padx=5)
            # top accent
            outer.create_rectangle(0, 0, 1000, 3, fill=color, outline=color)
            # icon badge
            outer.create_oval(14, 16, 42, 44, fill=bg, outline=color, width=1)
            outer.create_text(28, 30, text=icon, font=("Segoe UI", 10, "bold"), fill=color)
            # texts will be placed via labels over canvas using windows for crisp fonts
            inner = ttk.Frame(outer, style="Card.TFrame")
            outer.create_window(54, 28, window=inner, anchor="w")
            ttk.Label(inner, text=title.upper(), style="CardTitle.TLabel").pack(anchor="w")
            v = ttk.Label(inner, text="₹0", style="CardValue.TLabel", foreground=color)
            v.pack(anchor="w")
            self.card_vars[key] = v
            s_lbl = ttk.Label(outer, text=sub, style="CardSub.TLabel")
            outer.create_window(14, 72, window=s_lbl, anchor="w")
            # also store sub for dynamic hints
            self.card_sub_vars[key] = s_lbl

        mid = ttk.Frame(self.tab_dash)
        mid.pack(fill="both", expand=True)

        left = ttk.LabelFrame(
            mid, text="  ◷  Recent transactions — latest 10  ", padding=(0, 6, 0, 6)
        )
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        # custom header for left
        left_hdr = ttk.Frame(left)
        left_hdr.pack(fill="x", padx=8, pady=(2, 6))
        ttk.Label(
            left_hdr,
            text="Latest activity",
            font=("Segoe UI", 8, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).pack(side="left")
        ttk.Label(
            left_hdr,
            text="double-click to edit",
            font=("Segoe UI", 7),
            foreground="#94A3B8",
            background="#FFFFFF",
        ).pack(side="right")
        self.dash_tree = self._make_tree(left, height=10)
        self.dash_tree.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        right = ttk.LabelFrame(mid, text="  ◔  Expense by category  ", padding=(0, 6, 0, 6))
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))
        hdr = ttk.Frame(right)
        hdr.pack(fill="x", padx=8, pady=(2, 6))
        ttk.Label(
            hdr,
            text="This month",
            font=("Segoe UI", 8, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).pack(side="left")
        self.dash_chart = tk.Canvas(right, height=200, bg="#FFFFFF", highlightthickness=0, bd=0)
        self.dash_chart.pack(fill="both", expand=True, padx=8)
        # legend container with subtle bg
        leg_wrap = tk.Canvas(
            right, height=88, bg="#F8FAFC", highlightthickness=1, highlightbackground="#E2E8F0"
        )
        leg_wrap.pack(fill="x", padx=8, pady=(6, 4))
        self.dash_cat_text = tk.Text(
            leg_wrap,
            height=5,
            font=("Segoe UI", 8),
            bg="#F8FAFC",
            relief="flat",
            bd=0,
            highlightthickness=0,
            fg="#475569",
            padx=8,
            pady=6,
            wrap="word",
        )
        self.dash_cat_text.pack(fill="both", expand=True, padx=1, pady=1)
        self.dash_cat_text.configure(state="normal")

    def _make_tree(self, parent, height=12):
        cols = ("id", "date", "type", "category", "amount", "note")
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=height, style="Treeview")
        widths = {"id": 48, "date": 96, "type": 84, "category": 140, "amount": 108, "note": 240}
        headings = {
            "id": "#",
            "date": "Date",
            "type": "Type",
            "category": "Category",
            "amount": "Amount",
            "note": "Note",
        }
        for c in cols:
            tree.heading(
                c, text=headings.get(c, c.capitalize()), anchor="center" if c != "note" else "w"
            )
            tree.column(c, width=widths[c], anchor="center" if c != "note" else "w", minwidth=40)
        tree.column("id", width=48, minwidth=36)
        # modern scrollbar — overlay style
        vsb = ttk.Scrollbar(
            parent, orient="vertical", command=tree.yview, style="Vertical.TScrollbar"
        )
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y", padx=(1, 0))
        # striped + type colors — configured once
        tree.tag_configure("even", background="#FFFFFF")
        tree.tag_configure("odd", background="#F8FAFC")
        tree.tag_configure("inc", foreground="#059669")
        tree.tag_configure("exp", foreground="#DC2626")
        tree.tag_configure("muted", foreground="#94A3B8")
        return tree

    def refresh_dashboard(self):
        y, m = self.dash_year.get(), self.dash_month.get()
        try:
            d1, d2 = db_month_bounds(int(y), int(m))
        except Exception:
            return
        inc, exp, bal = db_totals(d1, d2)
        self.card_vars["inc"].config(text=f"₹{inc:,.2f}")
        self.card_vars["exp"].config(text=f"₹{exp:,.2f}")
        self.card_vars["bal"].config(text=f"₹{bal:,.2f}")
        rate = (bal / inc * 100) if inc else 0
        self.card_vars["rate"].config(text=f"{rate:.1f}%")
        # recent
        for i in self.dash_tree.get_children():
            self.dash_tree.delete(i)
        for r in db_query_txns(d1, d2)[:10]:
            self.dash_tree.insert("", "end", values=(r[0], r[1], r[2], r[3], f"{r[4]:.2f}", r[5]))
        # chart — pie (converted from bar)
        cats = db_category_summary(d1, d2, "Expense")
        self._draw_pie(self.dash_chart, cats)
        self.dash_cat_text.delete("1.0", "end")
        if not cats:
            self.dash_cat_text.insert("end", "No expenses this month.")
        else:
            total = sum(v for _, v in cats) or 1
            for i, (c, amt) in enumerate(cats[: len(self.PIE_COLORS)]):
                # colored dot uses same palette as pie
                self.dash_cat_text.insert("end", f"■ {c}: ₹{amt:,.2f} ({100 * amt / total:.1f}%)\n")

    def _safe_dashboard_refresh(self):
        try:
            self.refresh_dashboard()
        except tk.TclError, ValueError:
            pass

    def _draw_bar(self, canvas, data, color="#2563EB"):
        canvas.delete("all")
        canvas.update_idletasks()
        W, H = canvas.winfo_width(), canvas.winfo_height()
        if W < 60:
            W, H = 380, 220
        # soft background
        canvas.configure(bg="#FFFFFF")
        if not data:
            canvas.create_text(W // 2, H // 2 - 6, text="◌", fill="#CBD5E1", font=("Segoe UI", 22))
            canvas.create_text(
                W // 2,
                H // 2 + 16,
                text="No data for this period",
                fill="#94A3B8",
                font=("Segoe UI", 9),
            )
            return
        data = data[:7]
        mx = max(v for _, v in data) or 1
        left, top, bottom = 96, 12, H - 24
        bh = (H - top - bottom) / len(data)
        # faint track lines
        for i in range(len(data)):
            y = top + i * bh + bh / 2
            canvas.create_line(left, y, W - 18, y, fill="#F1F5F9", width=1, dash=(2, 4))
        for i, (cat, val) in enumerate(data):
            y0 = top + i * bh + 5
            y1 = y0 + bh - 10
            # track
            canvas.create_rectangle(
                left, y0, W - 18, y1, fill="#F8FAFC", outline="#F1F5F9", width=1
            )
            w = (W - left - 18) * (val / mx)
            # bar with subtle shadow
            if w > 4:
                canvas.create_rectangle(
                    left + 1, y0 + 1, left + w + 1, y1 + 1, fill="#E2E8F0", outline="", stipple=""
                )
                # main bar — use color with rounded feel via slightly inset
                canvas.create_rectangle(left, y0, left + w, y1, fill=color, outline="", width=0)
                # highlight top edge
                canvas.create_line(left, y0, left + w, y0, fill="white", width=1, stipple="gray50")
            canvas.create_text(
                left - 8,
                (y0 + y1) / 2,
                text=cat[:15],
                anchor="e",
                font=("Segoe UI", 8, "bold"),
                fill="#475569",
            )
            canvas.create_text(
                left + w + 6,
                (y0 + y1) / 2,
                text=f"₹{val:,.0f}",
                anchor="w",
                font=("Segoe UI", 8, "bold"),
                fill="#0F172A",
            )
            # faint % of max
            pct = val / mx * 100
            if w > 60:
                canvas.create_text(
                    left + w - 8,
                    (y0 + y1) / 2,
                    text=f"{pct:.0f}%",
                    anchor="e",
                    font=("Segoe UI", 7),
                    fill="white",
                )

    # ================= TRANSACTIONS =================
    def _build_transactions(self):
        # Filter card — white, rounded border
        f = ttk.Frame(self.tab_txn, style="Card.TFrame", padding=(12, 10, 12, 10))
        f.pack(fill="x", pady=(0, 10))
        ttk.Label(
            f,
            text="Filters",
            font=("Segoe UI", 9, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).grid(row=0, column=0, sticky="w", pady=(0, 6))
        ttk.Label(
            f,
            text="•  Refine by date, type or search",
            font=("Segoe UI", 7),
            foreground="#94A3B8",
            background="#FFFFFF",
        ).grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(0, 6))
        self.lbl_txn_sum = ttk.Label(
            f, text="", font=("Segoe UI", 8, "bold"), foreground="#0F172A", background="#FFFFFF"
        )
        self.lbl_txn_sum.grid(row=0, column=6, sticky="e", pady=(0, 6))
        f.columnconfigure(6, weight=1)

        today = date.today()
        first = today.replace(day=1).isoformat()
        last = today.isoformat()
        self.f_from = tk.StringVar(value=first)
        self.f_to = tk.StringVar(value=last)
        self.f_type = tk.StringVar(value="All")
        self.f_cat = tk.StringVar(value="All")
        self.f_search = tk.StringVar()

        inner = ttk.Frame(f, style="Card.TFrame")
        inner.grid(row=1, column=0, columnspan=7, sticky="ew")
        ttk.Label(
            inner,
            text="From",
            font=("Segoe UI", 7, "bold"),
            foreground="#475569",
            background="#FFFFFF",
        ).grid(row=0, column=0, sticky="w", padx=(0, 4))
        ttk.Entry(inner, textvariable=self.f_from, width=12).grid(
            row=1, column=0, padx=(0, 8), sticky="w"
        )
        ttk.Label(
            inner,
            text="To",
            font=("Segoe UI", 7, "bold"),
            foreground="#475569",
            background="#FFFFFF",
        ).grid(row=0, column=1, sticky="w", padx=(4, 4))
        ttk.Entry(inner, textvariable=self.f_to, width=12).grid(
            row=1, column=1, padx=(4, 10), sticky="w"
        )
        ttk.Label(
            inner,
            text="Type",
            font=("Segoe UI", 7, "bold"),
            foreground="#475569",
            background="#FFFFFF",
        ).grid(row=0, column=2, sticky="w", padx=(6, 4))
        ttk.Combobox(
            inner,
            textvariable=self.f_type,
            values=["All", "Income", "Expense"],
            width=9,
            state="readonly",
        ).grid(row=1, column=2, padx=4, sticky="w")
        ttk.Label(
            inner,
            text="Category",
            font=("Segoe UI", 7, "bold"),
            foreground="#475569",
            background="#FFFFFF",
        ).grid(row=0, column=3, sticky="w", padx=(6, 4))
        self.f_cat_box = ttk.Combobox(inner, textvariable=self.f_cat, width=13)
        self.f_cat_box.grid(row=1, column=3, padx=4, sticky="w")
        ttk.Label(
            inner,
            text="Search",
            font=("Segoe UI", 7, "bold"),
            foreground="#475569",
            background="#FFFFFF",
        ).grid(row=0, column=4, sticky="w", padx=(8, 4))
        ttk.Entry(inner, textvariable=self.f_search, width=22).grid(
            row=1, column=4, padx=4, sticky="w"
        )
        ttk.Button(
            inner, text="Apply", style="Accent.TButton", command=self.refresh_transactions
        ).grid(row=1, column=5, padx=(10, 4))
        ttk.Button(
            inner, text="Clear", style="Secondary.TButton", command=self._clear_filters
        ).grid(row=1, column=6, padx=2)

        # List card
        list_card = ttk.Frame(self.tab_txn, style="Card.TFrame", padding=(0, 0, 0, 0))
        list_card.pack(fill="both", expand=True)
        hdr = ttk.Frame(list_card, style="Card.TFrame", padding=(12, 10, 12, 8))
        hdr.pack(fill="x")
        ttk.Label(
            hdr,
            text="Transactions",
            font=("Segoe UI", 9, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).pack(side="left")
        ttk.Label(
            hdr,
            text="•  double-click row to edit",
            font=("Segoe UI", 7),
            foreground="#94A3B8",
            background="#FFFFFF",
        ).pack(side="left", padx=(8, 0))
        ttk.Label(
            hdr,
            text="↕ sortable • striped",
            font=("Segoe UI", 7),
            foreground="#94A3B8",
            background="#FFFFFF",
        ).pack(side="right")
        sep = ttk.Separator(list_card, orient="horizontal")
        sep.pack(fill="x")
        wrap = ttk.Frame(list_card, style="Card.TFrame", padding=(1, 0, 1, 1))
        wrap.pack(fill="both", expand=True)
        self.txn_tree = self._make_tree(wrap, height=16)
        self.txn_tree.pack(fill="both", expand=True, padx=1, pady=1)
        self.txn_tree.bind("<Double-1>", lambda e: self.open_txn_dialog(edit=True))

        btns = ttk.Frame(self.tab_txn, padding=(0, 8, 0, 0))
        btns.pack(fill="x")
        ttk.Button(btns, text="＋  Add", style="Accent.TButton", command=self.open_txn_dialog).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(
            btns,
            text="✏  Edit Selected",
            style="Secondary.TButton",
            command=lambda: self.open_txn_dialog(edit=True),
        ).pack(side="left", padx=4)
        ttk.Button(
            btns, text="🗑  Delete Selected", style="Danger.TButton", command=self.delete_selected
        ).pack(side="left", padx=4)
        ttk.Button(
            btns,
            text="⬇  Export CSV",
            style="Secondary.TButton",
            command=self.export_transactions_csv,
        ).pack(side="right")

    def _clear_filters(self):
        t = date.today()
        self.f_from.set(t.replace(day=1).isoformat())
        self.f_to.set(t.isoformat())
        self.f_type.set("All")
        self.f_cat.set("All")
        self.f_search.set("")
        self.refresh_transactions()

    def refresh_transactions(self):
        cats = ["All"] + sorted({c for _, c, _ in db_get_categories()})
        self.f_cat_box["values"] = cats
        try:
            rows = db_query_txns(
                self.f_from.get().strip() or None,
                self.f_to.get().strip() or None,
                self.f_type.get(),
                self.f_cat.get(),
                self.f_search.get(),
            )
        except Exception as ex:
            messagebox.showerror("Filter error", str(ex))
            return
        for i in self.txn_tree.get_children():
            self.txn_tree.delete(i)
        for idx, r in enumerate(rows):
            stripe = "even" if idx % 2 == 0 else "odd"
            tag = "inc" if r[2] == "Income" else "exp"
            self.txn_tree.insert(
                "", "end", values=(r[0], r[1], r[2], r[3], f"{r[4]:.2f}", r[5]), tags=(stripe, tag)
            )
        inc = sum(r[4] for r in rows if r[2] == "Income")
        exp = sum(r[4] for r in rows if r[2] == "Expense")
        bal = inc - exp
        # summary with colored dots
        self.lbl_txn_sum.config(
            text=(
                f"● Income ₹{inc:,.2f}   "
                f"● Expense ₹{exp:,.2f}   "
                f"◆ Balance ₹{bal:,.2f}  •  {len(rows)} rows"
            )
        )
        # update footer
        if hasattr(self, "footer_var"):
            self.footer_var.set(f"{len(rows)} transactions • Balance ₹{bal:,.2f} • DB: {DB_PATH}")

    def selected_txn_id(self):
        sel = self.txn_tree.selection()
        if not sel:
            messagebox.showinfo("Select", "Please select a transaction first.")
            return None
        vals = self.txn_tree.item(sel[0], "values")
        return int(vals[0]), vals

    def delete_selected(self):
        res = self.selected_txn_id()
        if not res:
            return
        tid, vals = res
        if messagebox.askyesno(
            "Delete", f"Delete transaction #{tid} ({vals[1]} {vals[3]} ₹{vals[4]})?"
        ):
            db_delete_txn(tid)
            self.refresh_all()

    def export_transactions_csv(self):
        rows = db_query_txns(
            self.f_from.get().strip() or None,
            self.f_to.get().strip() or None,
            self.f_type.get(),
            self.f_cat.get(),
            self.f_search.get(),
        )
        if not rows:
            messagebox.showinfo("Export", "No rows to export.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")], initialfile="transactions.csv"
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["ID", "Date", "Type", "Category", "Amount", "Note"])
            w.writerows(rows)
        messagebox.showinfo("Export", f"Exported {len(rows)} rows to:\n{path}")

    # ---- Add / Edit dialog ----
    def open_txn_dialog(self, edit=False):
        if edit:
            res = self.selected_txn_id()
            if not res:
                return
            tid, vals = res
            init = {
                "id": tid,
                "date": vals[1],
                "type": vals[2],
                "category": vals[3],
                "amount": vals[4],
                "note": vals[5],
            }
        else:
            init = {
                "id": None,
                "date": date.today().isoformat(),
                "type": "Expense",
                "category": "",
                "amount": "",
                "note": "",
            }

        dlg = tk.Toplevel(self)
        dlg.title("Edit Transaction" if edit else "Add Transaction")
        dlg.geometry("420x460")
        dlg.minsize(380, 420)
        dlg.configure(bg="#F1F5F9")
        dlg.transient(self)
        dlg.grab_set()

        # header banner
        hdr = tk.Canvas(dlg, height=64, bg="#FFFFFF", highlightthickness=0)
        hdr.pack(fill="x")
        hdr.create_rectangle(
            0,
            0,
            420,
            3,
            fill="#2563EB" if not edit or init["type"] == "Expense" else "#059669",
            outline="",
        )
        icon_bg = "#EFF6FF" if init["type"] == "Expense" else "#ECFDF5"
        icon_fg = "#2563EB" if init["type"] == "Expense" else "#059669"
        hdr.create_oval(16, 14, 48, 46, fill=icon_bg, outline="#E2E8F0")
        hdr.create_text(
            32, 30, text="✏" if edit else "＋", font=("Segoe UI", 13, "bold"), fill=icon_fg
        )
        hdr.create_text(
            60,
            20,
            text="Edit Transaction" if edit else "New Transaction",
            font=("Segoe UI", 11, "bold"),
            fill="#0F172A",
            anchor="w",
        )
        hdr.create_text(
            60,
            38,
            text="Fill the details below • Amount must be > 0",
            font=("Segoe UI", 7),
            fill="#64748B",
            anchor="w",
        )

        frm = ttk.Frame(dlg, padding=(18, 16, 18, 12), style="Card.TFrame")
        frm.pack(fill="both", expand=True, padx=12, pady=12)

        v_date = tk.StringVar(value=init["date"])
        v_type = tk.StringVar(value=init["type"])
        v_cat = tk.StringVar(value=init["category"])
        v_amt = tk.StringVar(value=str(init["amount"]))
        v_note = tk.StringVar(value=init["note"])

        def _field_label(txt):
            ttk.Label(
                frm,
                text=txt,
                font=("Segoe UI", 7, "bold"),
                foreground="#475569",
                background="#FFFFFF",
            ).pack(anchor="w", pady=(0, 2))

        _field_label("Date  •  YYYY-MM-DD")
        ttk.Entry(frm, textvariable=v_date).pack(fill="x", pady=(0, 10))
        _field_label("Type")
        type_box = ttk.Combobox(
            frm, textvariable=v_type, values=["Income", "Expense"], state="readonly"
        )
        type_box.pack(fill="x", pady=(0, 10))
        _field_label("Category")
        cat_box = ttk.Combobox(frm, textvariable=v_cat)
        cat_box.pack(fill="x", pady=(0, 10))

        def load_cats(*_):
            cat_box["values"] = [n for _, n, _ in db_get_categories(v_type.get())]
            if v_cat.get() not in cat_box["values"] and cat_box["values"]:
                v_cat.set(cat_box["values"][0])
            # update header accent
            try:
                col = "#DC2626" if v_type.get() == "Expense" else "#059669"
                hdr.delete("hdr_accent")
                hdr.create_rectangle(0, 0, 420, 3, fill=col, outline=col, tags="hdr_accent")
            except Exception:
                pass

        v_type.trace_add("write", load_cats)
        load_cats()
        if init["category"]:
            v_cat.set(init["category"])

        _field_label("Amount  •  ₹")
        ttk.Entry(frm, textvariable=v_amt).pack(fill="x", pady=(0, 10))
        _field_label("Note  •  optional")
        ttk.Entry(frm, textvariable=v_note).pack(fill="x", pady=(0, 14))

        def save():
            d = v_date.get().strip()
            try:
                datetime.strptime(d, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Invalid", "Date must be YYYY-MM-DD.", parent=dlg)
                return
            try:
                amt = float(v_amt.get())
                assert amt > 0
            except Exception:
                messagebox.showerror("Invalid", "Amount must be a number > 0.", parent=dlg)
                return
            if not v_cat.get().strip():
                messagebox.showerror("Invalid", "Please choose a category.", parent=dlg)
                return
            if edit:
                db_update_txn(
                    init["id"], d, v_type.get(), v_cat.get().strip(), amt, v_note.get().strip()
                )
            else:
                db_add_txn(d, v_type.get(), v_cat.get().strip(), amt, v_note.get().strip())
            dlg.destroy()
            self.refresh_all()
            self.nb.select(self.tab_txn)

        btns = ttk.Frame(frm, style="Card.TFrame")
        btns.pack(fill="x", pady=(4, 0))
        ttk.Button(btns, text="Cancel", style="Secondary.TButton", command=dlg.destroy).pack(
            side="right", padx=(8, 0)
        )
        ttk.Button(btns, text="💾  Save", style="Accent.TButton", command=save).pack(side="right")
        dlg.bind("<Return>", lambda e: save())

    # ================= CATEGORIES =================
    def _build_categories(self):
        topbar = ttk.Frame(self.tab_cat, style="Card.TFrame", padding=(12, 10, 12, 10))
        topbar.pack(fill="x", pady=(0, 10))
        ttk.Label(
            topbar,
            text="Manage your categories",
            font=("Segoe UI", 10, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).pack(side="left")
        ttk.Label(
            topbar,
            text="•  Income vs Expense • quick CRUD",
            font=("Segoe UI", 7),
            foreground="#94A3B8",
            background="#FFFFFF",
        ).pack(side="left", padx=(8, 0))
        ttk.Button(topbar, text="↻  Refresh", style="Ghost.TButton", command=self.refresh_all).pack(
            side="right", padx=4
        )
        ttk.Button(
            topbar,
            text="🗂  Category Manager",
            style="Accent.TButton",
            command=self.open_category_manager,
        ).pack(side="right")
        wrap = ttk.Frame(self.tab_cat)
        wrap.pack(fill="both", expand=True)
        self.cat_trees = {}
        for col, ttype in enumerate(["Income", "Expense"]):
            # accent color per type
            accent = "#059669" if ttype == "Income" else "#DC2626"
            bg_accent = "#ECFDF5" if ttype == "Income" else "#FEF2F2"
            icon = "↑" if ttype == "Income" else "↓"
            box = ttk.Frame(wrap, style="Card.TFrame", padding=0)
            box.grid(row=0, column=col, sticky="nsew", padx=6, pady=2)
            # header strip
            hdr = tk.Canvas(
                box, height=36, bg="#FFFFFF", highlightthickness=1, highlightbackground="#E2E8F0"
            )
            hdr.pack(fill="x")
            hdr.create_rectangle(0, 0, 400, 3, fill=accent, outline=accent)
            hdr.create_oval(10, 10, 30, 30, fill=bg_accent, outline=accent)
            hdr.create_text(20, 20, text=icon, font=("Segoe UI", 9, "bold"), fill=accent)
            hdr.create_text(
                38,
                20,
                text=f"{ttype}  •  categories",
                font=("Segoe UI", 9, "bold"),
                fill="#0F172A",
                anchor="w",
            )
            # tree container
            tree_wrap = ttk.Frame(box, style="Card.TFrame", padding=(6, 6, 6, 4))
            tree_wrap.pack(fill="both", expand=True)
            tree = ttk.Treeview(tree_wrap, columns=("id", "name"), show="headings", height=13)
            tree.heading("id", text="#")
            tree.heading("name", text="Category")
            tree.column("id", width=46, anchor="center", minwidth=36)
            tree.column("name", width=200, anchor="w")
            tree.pack(fill="both", expand=True, pady=(0, 4))
            tree.tag_configure("even", background="#FFFFFF")
            tree.tag_configure("odd", background="#F8FAFC")
            self.cat_trees[ttype] = tree
            tree.bind("<Double-1>", lambda e, t=ttype: self.rename_category(t))
            row = ttk.Frame(box, style="Card.TFrame", padding=(8, 6, 8, 8))
            row.pack(fill="x")
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, width=18).pack(side="left", padx=(0, 6))
            ttk.Button(
                row,
                text="＋ Add",
                style="Success.TButton" if ttype == "Income" else "Danger.TButton",
                command=lambda t=ttype, v=var: self.add_category(t, v),
            ).pack(side="left")
            ttk.Button(
                row,
                text="✏",
                style="Secondary.TButton",
                width=3,
                command=lambda t=ttype: self.rename_category(t),
            ).pack(side="left", padx=4)
            ttk.Button(
                row,
                text="🗑",
                style="Ghost.TButton",
                width=3,
                command=lambda t=ttype: self.delete_category(t),
            ).pack(side="right")
            setattr(self, f"cat_var_{ttype}", var)
        wrap.columnconfigure(0, weight=1)
        wrap.columnconfigure(1, weight=1)
        # tip card
        tip = tk.Canvas(
            self.tab_cat,
            bg="#EFF6FF",
            highlightthickness=1,
            highlightbackground="#DBEAFE",
            height=34,
        )
        tip.pack(fill="x", pady=(8, 0))
        tip.create_text(
            12, 17, text="💡  Tip:", font=("Segoe UI", 8, "bold"), fill="#1E40AF", anchor="w"
        )
        tip.create_text(
            54,
            17,
            text=(
                "Double-click a category or press ✏ to rename • "
                "Renaming can retag old transactions"
            ),
            font=("Segoe UI", 7),
            fill="#475569",
            anchor="w",
        )

    def add_category(self, ttype, var):
        name = var.get().strip()
        if not name:
            messagebox.showinfo("Category", "Enter a category name.")
            return
        if db_add_category(name, ttype):
            var.set("")
            self.refresh_all()
        else:
            messagebox.showwarning("Category", f"'{name}' already exists under {ttype}.")

    def delete_category(self, ttype):
        tree = self.cat_trees[ttype]
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Category", f"Select an {ttype} category to delete.")
            return
        vals = tree.item(sel[0], "values")
        if messagebox.askyesno("Delete", f"Delete {ttype} category '{vals[1]}'?"):
            db_delete_category(int(vals[0]))
            self.refresh_all()

    def rename_category(self, ttype):
        tree = self.cat_trees[ttype]
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Category", f"Select an {ttype} category to rename.")
            return
        cid, old_name = tree.item(sel[0], "values")
        cid = int(cid)
        n_txn = db_count_txns_for_category(old_name, ttype)

        dlg = tk.Toplevel(self)
        dlg.title(f"Edit {ttype} category")
        dlg.geometry("360x250")
        dlg.transient(self)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=16)
        frm.pack(fill="both", expand=True)

        v_name = tk.StringVar(value=old_name)
        v_type = tk.StringVar(value=ttype)
        v_update = tk.BooleanVar(value=True)

        ttk.Label(frm, text="Name:").pack(anchor="w")
        name_entry = ttk.Entry(frm, textvariable=v_name)
        name_entry.pack(fill="x", pady=(0, 8))
        name_entry.select_range(0, "end")
        name_entry.focus()
        ttk.Label(frm, text="Type:").pack(anchor="w")
        ttk.Combobox(frm, textvariable=v_type, values=["Income", "Expense"], state="readonly").pack(
            fill="x", pady=(0, 8)
        )
        ttk.Checkbutton(
            frm, variable=v_update, text=f"Also update {n_txn} existing transaction(s)"
        ).pack(anchor="w", pady=(0, 12))

        def save():
            ok, info = db_update_category(cid, v_name.get(), v_type.get(), v_update.get())
            if not ok:
                messagebox.showerror("Invalid", info, parent=dlg)
                return
            dlg.destroy()
            self.refresh_all()
            if info:
                messagebox.showinfo(
                    "Category",
                    f"Renamed '{old_name}' → '{v_name.get().strip()}'.\n"
                    f"{info} transaction(s) retagged.",
                )

        ttk.Button(frm, text="💾 Save", style="Accent.TButton", command=save).pack(fill="x")
        dlg.bind("<Return>", lambda e: save())

    def refresh_categories(self):
        for ttype, tree in self.cat_trees.items():
            for i in tree.get_children():
                tree.delete(i)
            for idx, (cid, name, _) in enumerate(db_get_categories(ttype)):
                stripe = "even" if idx % 2 == 0 else "odd"
                tree.insert("", "end", values=(cid, name), tags=(stripe,))

    # ---- Separate Category CRUD form (own window) ----
    def open_category_manager(self):
        # focus existing window instead of opening duplicates
        if getattr(self, "_cat_mgr", None) is not None and self._cat_mgr.winfo_exists():
            self._cat_mgr.lift()
            self._cat_mgr.focus()
            return
        mgr = tk.Toplevel(self)
        self._cat_mgr = mgr
        mgr.title("Category Manager — Create / View / Edit / Delete")
        mgr.geometry("620x520")
        mgr.minsize(540, 460)
        mgr.transient(self)

        # -- search / filter --
        filt = ttk.Frame(mgr, padding=(12, 10, 12, 0))
        filt.pack(fill="x")
        ttk.Label(filt, text="Search:").pack(side="left")
        v_search = tk.StringVar()
        ttk.Entry(filt, textvariable=v_search, width=24).pack(side="left", padx=6)
        ttk.Label(filt, text="Type:").pack(side="left", padx=(8, 0))
        v_filter = tk.StringVar(value="All")
        ttk.Combobox(
            filt,
            textvariable=v_filter,
            values=["All", "Income", "Expense"],
            width=10,
            state="readonly",
        ).pack(side="left", padx=6)

        # -- list (Read) --
        list_box = ttk.LabelFrame(mgr, text="Categories (double-click a row to edit)", padding=8)
        list_box.pack(fill="both", expand=True, padx=12, pady=8)
        tree = ttk.Treeview(
            list_box, columns=("id", "name", "type", "used"), show="headings", height=12
        )
        for col, txt, w, anc in [
            ("id", "ID", 50, "center"),
            ("name", "Name", 200, "w"),
            ("type", "Type", 90, "center"),
            ("used", "Txns", 70, "center"),
        ]:
            tree.heading(col, text=txt)
            tree.column(col, width=w, anchor=anc)
        vsb = ttk.Scrollbar(list_box, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # -- editor (Create / Update) --
        edit_box = ttk.LabelFrame(mgr, text="Add / Edit category", padding=8)
        edit_box.pack(fill="x", padx=12, pady=(0, 4))
        v_id = tk.IntVar(value=0)  # 0 = creating new
        v_name = tk.StringVar()
        v_type = tk.StringVar(value="Expense")
        v_retag = tk.BooleanVar(value=True)
        ttk.Label(edit_box, text="Name:").grid(row=0, column=0, sticky="w")
        name_entry = ttk.Entry(edit_box, textvariable=v_name, width=26)
        name_entry.grid(row=0, column=1, padx=6, pady=2, sticky="w")
        ttk.Label(edit_box, text="Type:").grid(row=0, column=2, sticky="w", padx=(10, 0))
        ttk.Combobox(
            edit_box, textvariable=v_type, values=["Income", "Expense"], width=10, state="readonly"
        ).grid(row=0, column=3, padx=6, pady=2)
        retag_chk = ttk.Checkbutton(
            edit_box, variable=v_retag, text="Retag existing transactions on rename"
        )
        retag_chk.grid(row=1, column=0, columnspan=4, sticky="w", pady=2)
        lbl_hint = ttk.Label(
            edit_box,
            text="Mode: adding new  •  select a row + Edit to modify",
            foreground="#666",
            font=("Segoe UI", 8),
        )
        lbl_hint.grid(row=2, column=0, columnspan=4, sticky="w")

        def refresh_list():
            for i in tree.get_children():
                tree.delete(i)
            s = v_search.get().strip().lower()
            for cid, name, ctype in db_get_categories(
                None if v_filter.get() == "All" else v_filter.get()
            ):
                if s and s not in name.lower():
                    continue
                used = db_count_txns_for_category(name, ctype)
                tag = "inc" if ctype == "Income" else "exp"
                tree.insert("", "end", values=(cid, name, ctype, used), tags=(tag,))
            tree.tag_configure("inc", foreground="#1a7f37")
            tree.tag_configure("exp", foreground="#cf222e")
            self.refresh_all()  # keep main window (tabs, dropdowns, graphs) in sync

        def clear_form():
            v_id.set(0)
            v_name.set("")
            v_type.set("Expense")
            v_retag.set(True)
            lbl_hint.config(text="Mode: adding new  •  select a row + Edit to modify")

        def do_save():
            name = v_name.get().strip()
            if not name:
                messagebox.showinfo("Category", "Enter a category name.", parent=mgr)
                return
            if v_id.get() == 0:  # CREATE
                if db_add_category(name, v_type.get()):
                    clear_form()
                    refresh_list()
                else:
                    messagebox.showwarning(
                        "Category", f"'{name}' already exists under {v_type.get()}.", parent=mgr
                    )
            else:  # UPDATE
                ok, info = db_update_category(v_id.get(), name, v_type.get(), v_retag.get())
                if not ok:
                    messagebox.showerror("Category", info, parent=mgr)
                    return
                msg = f"Saved '{name}'."
                if info:
                    msg += f"\n{info} transaction(s) retagged."
                clear_form()
                refresh_list()
                messagebox.showinfo("Category", msg, parent=mgr)

        def do_edit():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("Category", "Select a row to edit.", parent=mgr)
                return
            cid, name, ctype, used = tree.item(sel[0], "values")
            v_id.set(int(cid))
            v_name.set(name)
            v_type.set(ctype)
            lbl_hint.config(
                text=f"Mode: editing #{cid} '{name}' ({used} transaction(s)) — Save to apply"
            )
            name_entry.focus()
            name_entry.select_range(0, "end")

        def do_delete():
            sel = tree.selection()
            if not sel:
                messagebox.showinfo("Category", "Select a row to delete.", parent=mgr)
                return
            cid, name, ctype, used = tree.item(sel[0], "values")
            if int(used) > 0:
                ok = messagebox.askyesno(
                    "Delete",
                    f"Delete {ctype} category '{name}'?\n\n"
                    f"⚠ It is used by {used} transaction(s) — those rows keep the old "
                    f"name as plain text (history is not deleted).",
                    parent=mgr,
                )
            else:
                ok = messagebox.askyesno("Delete", f"Delete {ctype} category '{name}'?", parent=mgr)
            if ok:
                db_delete_category(int(cid))
                if v_id.get() == int(cid):
                    clear_form()
                refresh_list()

        tree.bind("<Double-1>", lambda e: do_edit())
        v_search.trace_add("write", lambda *_: refresh_list())
        v_filter.trace_add("write", lambda *_: refresh_list())

        # -- buttons --
        btns = ttk.Frame(mgr, padding=(12, 0, 12, 12))
        btns.pack(fill="x")
        ttk.Button(btns, text="💾 Save", style="Accent.TButton", command=do_save).pack(side="left")
        ttk.Button(btns, text="✏ Edit Selected", command=do_edit).pack(side="left", padx=6)
        ttk.Button(btns, text="🗑 Delete Selected", command=do_delete).pack(side="left")
        ttk.Button(btns, text="Clear", command=clear_form).pack(side="left", padx=6)
        ttk.Button(btns, text="Close", command=mgr.destroy).pack(side="right")
        mgr.bind("<Return>", lambda e: do_save())
        refresh_list()

    # ================= REPORTS =================
    def _build_reports(self):
        # --- daily ---
        daily = ttk.Frame(self.tab_rep, style="Card.TFrame", padding=(12, 10, 12, 10))
        daily.pack(fill="x", pady=(0, 10))
        ttk.Label(
            daily,
            text="📅  Daily",
            font=("Segoe UI", 9, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).pack(side="left")
        self.rep_day = tk.StringVar(value=date.today().isoformat())
        ttk.Entry(daily, textvariable=self.rep_day, width=13).pack(side="left", padx=(8, 4))
        ttk.Button(
            daily, text="◀", style="Secondary.TButton", width=3, command=lambda: self._shift_day(-1)
        ).pack(side="left", padx=1)
        ttk.Button(
            daily, text="▶", style="Secondary.TButton", width=3, command=lambda: self._shift_day(1)
        ).pack(side="left", padx=1)
        ttk.Button(daily, text="Today", style="Ghost.TButton", command=self._today_day).pack(
            side="left", padx=6
        )
        ttk.Button(daily, text="Show", style="Accent.TButton", command=self.refresh_reports).pack(
            side="left", padx=4
        )
        self.lbl_daily = ttk.Label(
            daily, text="", font=("Segoe UI", 8, "bold"), foreground="#334155", background="#FFFFFF"
        )
        self.lbl_daily.pack(side="left", padx=12)

        # --- monthly ---
        monthly = ttk.Frame(self.tab_rep, style="Card.TFrame", padding=(12, 10, 12, 10))
        monthly.pack(fill="x", pady=(0, 10))
        ttk.Label(
            monthly,
            text="🗓  Monthly",
            font=("Segoe UI", 9, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).pack(side="left")
        t = date.today()
        self.rep_year = tk.IntVar(value=t.year)
        self.rep_month = tk.IntVar(value=t.month)
        ttk.Label(
            monthly,
            text="Year",
            font=("Segoe UI", 7, "bold"),
            foreground="#475569",
            background="#FFFFFF",
        ).pack(side="left", padx=(10, 4))
        ttk.Spinbox(
            monthly,
            from_=2000,
            to=2100,
            width=6,
            textvariable=self.rep_year,
            command=self.refresh_reports,
        ).pack(side="left", padx=2)
        ttk.Label(
            monthly,
            text="Month",
            font=("Segoe UI", 7, "bold"),
            foreground="#475569",
            background="#FFFFFF",
        ).pack(side="left", padx=(6, 4))
        ttk.Spinbox(
            monthly,
            from_=1,
            to=12,
            width=4,
            textvariable=self.rep_month,
            command=self.refresh_reports,
        ).pack(side="left", padx=2)
        self.rep_year.trace_add("write", lambda *_: self.after(400, self._safe_reports_refresh))
        self.rep_month.trace_add("write", lambda *_: self.after(400, self._safe_reports_refresh))
        ttk.Button(
            monthly, text="Show", style="Secondary.TButton", command=self.refresh_reports
        ).pack(side="left", padx=8)
        self.lbl_monthly = ttk.Label(
            monthly,
            text="",
            font=("Segoe UI", 8, "bold"),
            foreground="#334155",
            background="#FFFFFF",
        )
        self.lbl_monthly.pack(side="left", padx=12)
        ttk.Button(
            monthly, text="⬇  Export CSV", style="Secondary.TButton", command=self.export_month_csv
        ).pack(side="right")

        # --- results ---
        res = ttk.Frame(self.tab_rep)
        res.pack(fill="both", expand=True)
        left = ttk.Frame(res, style="Card.TFrame", padding=0)
        left.pack(side="left", fill="both", expand=True, padx=(0, 6))
        hdr_l = ttk.Frame(left, style="Card.TFrame", padding=(12, 10, 12, 8))
        hdr_l.pack(fill="x")
        ttk.Label(
            hdr_l,
            text="Day-wise totals",
            font=("Segoe UI", 9, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).pack(side="left")
        ttk.Label(
            hdr_l,
            text="• daily balance",
            font=("Segoe UI", 7),
            foreground="#94A3B8",
            background="#FFFFFF",
        ).pack(side="left", padx=(6, 0))
        ttk.Separator(left, orient="horizontal").pack(fill="x")
        tree_wrap_l = ttk.Frame(left, style="Card.TFrame", padding=(1, 0, 1, 1))
        tree_wrap_l.pack(fill="both", expand=True)
        self.rep_day_tree = ttk.Treeview(
            tree_wrap_l, columns=("day", "income", "expense", "balance"), show="headings", height=12
        )
        for c, w, txt in [
            ("day", 92, "Day"),
            ("income", 102, "Income"),
            ("expense", 102, "Expense"),
            ("balance", 102, "Balance"),
        ]:
            self.rep_day_tree.heading(c, text=txt)
            self.rep_day_tree.column(c, width=w, anchor="center")
        self.rep_day_tree.pack(fill="both", expand=True, padx=1, pady=1)

        right = ttk.Frame(res, style="Card.TFrame", padding=0)
        right.pack(side="right", fill="both", expand=True, padx=(6, 0))
        hdr_r = ttk.Frame(right, style="Card.TFrame", padding=(12, 10, 12, 8))
        hdr_r.pack(fill="x")
        ttk.Label(
            hdr_r,
            text="Breakdown",
            font=("Segoe UI", 9, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).pack(side="left")
        self.rep_type = tk.StringVar(value="Expense")
        ttk.Combobox(
            hdr_r,
            textvariable=self.rep_type,
            values=["Expense", "Income"],
            width=9,
            state="readonly",
        ).pack(side="right")
        ttk.Label(
            hdr_r, text="Show", font=("Segoe UI", 7), foreground="#64748B", background="#FFFFFF"
        ).pack(side="right", padx=(0, 6))
        ttk.Separator(right, orient="horizontal").pack(fill="x")
        self.rep_chart = tk.Canvas(right, height=160, bg="#FFFFFF", highlightthickness=0)
        self.rep_chart.pack(fill="both", expand=True, padx=8, pady=6)
        sep2 = ttk.Separator(right, orient="horizontal")
        sep2.pack(fill="x", padx=8)
        self.rep_cat_tree = ttk.Treeview(right, columns=("cat", "total"), show="headings", height=6)
        self.rep_cat_tree.heading("cat", text="Category")
        self.rep_cat_tree.heading("total", text="Total (₹)")
        self.rep_cat_tree.column("cat", width=160, anchor="w")
        self.rep_cat_tree.column("total", width=110, anchor="e")
        self.rep_cat_tree.pack(fill="x", padx=1, pady=(4, 1))

    def _shift_day(self, delta):
        try:
            d = datetime.strptime(self.rep_day.get(), "%Y-%m-%d").date() + timedelta(days=delta)
            self.rep_day.set(d.isoformat())
            self.refresh_reports()
        except ValueError:
            messagebox.showerror("Invalid", "Date must be YYYY-MM-DD.")

    def _today_day(self):
        self.rep_day.set(date.today().isoformat())
        self.refresh_reports()

    def refresh_reports(self):
        # daily
        d = self.rep_day.get().strip()
        try:
            datetime.strptime(d, "%Y-%m-%d")
            inc, exp, bal = db_daily_summary(d)
            n = len(db_query_txns(d, d))
            self.lbl_daily.config(
                text=f"{d}: {n} txn(s) • Income ₹{inc:,.2f} • "
                f"Expense ₹{exp:,.2f} • Balance ₹{bal:,.2f}"
            )
        except ValueError:
            self.lbl_daily.config(text="Invalid date (use YYYY-MM-DD)")
        # monthly
        try:
            y, m = int(self.rep_year.get()), int(self.rep_month.get())
            d1, d2 = db_month_bounds(y, m)
        except Exception:
            self.lbl_monthly.config(text="Invalid year/month")
            return
        inc, exp, bal = db_totals(d1, d2)
        self.lbl_monthly.config(
            text=f"{y}-{m:02d}: Income ₹{inc:,.2f} • " f"Expense ₹{exp:,.2f} • Balance ₹{bal:,.2f}"
        )
        # day-wise table
        for i in self.rep_day_tree.get_children():
            self.rep_day_tree.delete(i)
        with contextlib.closing(get_conn()) as conn:
            per_day = conn.execute(
                """SELECT date,
                          SUM(CASE WHEN type='Income' THEN amount ELSE 0 END),
                          SUM(CASE WHEN type='Expense' THEN amount ELSE 0 END)
                   FROM transactions WHERE date BETWEEN ? AND ?
                   GROUP BY date ORDER BY date""",
                (d1, d2),
            ).fetchall()
        have = {r[0]: r for r in per_day}
        last_day = calendar.monthrange(y, m)[1]
        for day in range(1, last_day + 1):
            ds = f"{y:04d}-{m:02d}-{day:02d}"
            if ds in have:
                _, i_, e_ = have[ds]
                i_, e_ = i_ or 0, e_ or 0
                self.rep_day_tree.insert(
                    "", "end", values=(ds, f"{i_:,.2f}", f"{e_:,.2f}", f"{i_ - e_:,.2f}")
                )
        # category breakdown + chart — pie (converted from bar)
        for i in self.rep_cat_tree.get_children():
            self.rep_cat_tree.delete(i)
        cats = db_category_summary(d1, d2, self.rep_type.get())
        for idx, (c, amt) in enumerate(cats):
            stripe = "even" if idx % 2 == 0 else "odd"
            self.rep_cat_tree.insert("", "end", values=(c, f"{amt:,.2f}"), tags=(stripe,))
        self._draw_pie(self.rep_chart, cats)

    def _safe_reports_refresh(self):
        try:
            self.refresh_reports()
        except tk.TclError, ValueError:
            pass

    def export_month_csv(self):
        try:
            y, m = int(self.rep_year.get()), int(self.rep_month.get())
            d1, d2 = db_month_bounds(y, m)
        except Exception:
            messagebox.showerror("Invalid", "Invalid year/month.")
            return
        rows = db_query_txns(d1, d2)
        if not rows:
            messagebox.showinfo("Export", "No transactions in this month.")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"report_{y}-{m:02d}.csv",
        )
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["ID", "Date", "Type", "Category", "Amount", "Note"])
            w.writerows(rows)
            inc, exp, bal = db_totals(d1, d2)
            w.writerow([])
            w.writerow(["Monthly Total Income", f"{inc:.2f}"])
            w.writerow(["Monthly Total Expense", f"{exp:.2f}"])
            w.writerow(["Monthly Balance", f"{bal:.2f}"])
        messagebox.showinfo("Export", f"Monthly report saved:\n{path}")

    # ================= GRAPHS =================
    PIE_COLORS = [
        "#2563EB",  # blue
        "#059669",  # emerald
        "#DC2626",  # red
        "#7C3AED",  # violet
        "#D97706",  # amber
        "#0891B2",  # cyan
        "#DB2777",  # pink
        "#475569",  # slate
        "#16A34A",  # green
        "#EAB308",  # yellow
        "#4F46E5",  # indigo
        "#BE123C",  # rose
    ]

    def _build_graphs(self):
        bar = ttk.Frame(self.tab_graph, style="Card.TFrame", padding=(12, 10, 12, 10))
        bar.pack(fill="x", pady=(0, 10))
        ttk.Label(
            bar,
            text="📈  Visual Insights",
            font=("Segoe UI", 9, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).pack(side="left")
        t = date.today()
        self.gr_year = tk.IntVar(value=t.year)
        self.gr_month = tk.IntVar(value=t.month)
        self.gr_type = tk.StringVar(value="Expense")
        ttk.Label(
            bar,
            text="Year",
            font=("Segoe UI", 7, "bold"),
            foreground="#475569",
            background="#FFFFFF",
        ).pack(side="left", padx=(16, 4))
        ttk.Spinbox(
            bar,
            from_=2000,
            to=2100,
            width=6,
            textvariable=self.gr_year,
            command=self.refresh_graphs,
        ).pack(side="left", padx=2)
        ttk.Label(
            bar,
            text="Month",
            font=("Segoe UI", 7, "bold"),
            foreground="#475569",
            background="#FFFFFF",
        ).pack(side="left", padx=(8, 4))
        ttk.Spinbox(
            bar, from_=1, to=12, width=4, textvariable=self.gr_month, command=self.refresh_graphs
        ).pack(side="left", padx=2)
        self.gr_year.trace_add("write", lambda *_: self.after(400, self._safe_graphs_refresh))
        self.gr_month.trace_add("write", lambda *_: self.after(400, self._safe_graphs_refresh))
        ttk.Label(
            bar,
            text="Pie",
            font=("Segoe UI", 7, "bold"),
            foreground="#475569",
            background="#FFFFFF",
        ).pack(side="left", padx=(10, 4))
        ttk.Combobox(
            bar, textvariable=self.gr_type, values=["Expense", "Income"], width=9, state="readonly"
        ).pack(side="left", padx=2)
        self.gr_type.trace_add("write", lambda *_: self.refresh_graphs())
        ttk.Button(bar, text="↻  Refresh", style="Ghost.TButton", command=self.refresh_graphs).pack(
            side="right"
        )
        self.lbl_graph_sum = ttk.Label(
            bar, text="", font=("Segoe UI", 8, "bold"), foreground="#334155", background="#FFFFFF"
        )
        self.lbl_graph_sum.pack(side="left", padx=12)

        top = ttk.Frame(self.tab_graph)
        top.pack(fill="both", expand=True)
        pie_box = ttk.Frame(top, style="Card.TFrame", padding=0)
        pie_box.pack(side="left", fill="both", expand=True, padx=(0, 6))
        hdr_pie = ttk.Frame(pie_box, style="Card.TFrame", padding=(12, 10, 12, 8))
        hdr_pie.pack(fill="x")
        ttk.Label(
            hdr_pie,
            text="Category share",
            font=("Segoe UI", 9, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).pack(side="left")
        ttk.Label(
            hdr_pie,
            text="•  pie % + legend",
            font=("Segoe UI", 7),
            foreground="#94A3B8",
            background="#FFFFFF",
        ).pack(side="left", padx=(6, 0))
        ttk.Separator(pie_box, orient="horizontal").pack(fill="x")
        self.pie_canvas = tk.Canvas(pie_box, bg="#FFFFFF", highlightthickness=0, bd=0, height=240)
        self.pie_canvas.pack(fill="both", expand=True, padx=1, pady=1)
        # legend area with soft bg
        leg_card = tk.Canvas(
            pie_box, bg="#F8FAFC", highlightthickness=1, highlightbackground="#E2E8F0", height=86
        )
        leg_card.pack(fill="x", padx=8, pady=(4, 8))
        self.pie_legend = tk.Text(
            leg_card,
            height=5,
            font=("Segoe UI", 8),
            bg="#F8FAFC",
            relief="flat",
            bd=0,
            highlightthickness=0,
            fg="#475569",
            padx=8,
            pady=6,
            wrap="word",
        )
        self.pie_legend.pack(fill="both", expand=True, padx=1, pady=1)

        trend_box = ttk.Frame(top, style="Card.TFrame", padding=0)
        trend_box.pack(side="right", fill="both", expand=True, padx=(6, 0))
        hdr_trend = ttk.Frame(trend_box, style="Card.TFrame", padding=(12, 10, 12, 8))
        hdr_trend.pack(fill="x")
        ttk.Label(
            hdr_trend,
            text="Daily trend",
            font=("Segoe UI", 9, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).pack(side="left")
        ttk.Label(
            hdr_trend,
            text="•  income vs expense",
            font=("Segoe UI", 7),
            foreground="#94A3B8",
            background="#FFFFFF",
        ).pack(side="left", padx=(6, 0))
        ttk.Separator(trend_box, orient="horizontal").pack(fill="x")
        self.trend_canvas = tk.Canvas(trend_box, bg="#FFFFFF", highlightthickness=0, bd=0)
        self.trend_canvas.pack(fill="both", expand=True, padx=8, pady=8)

        year_box = ttk.Frame(self.tab_graph, style="Card.TFrame", padding=0)
        year_box.pack(fill="both", expand=True, pady=(10, 0))
        hdr_year = ttk.Frame(year_box, style="Card.TFrame", padding=(12, 10, 12, 8))
        hdr_year.pack(fill="x")
        ttk.Label(
            hdr_year,
            text="Yearly overview",
            font=("Segoe UI", 9, "bold"),
            foreground="#0F172A",
            background="#FFFFFF",
        ).pack(side="left")
        ttk.Label(
            hdr_year,
            text="•  12 months • income vs expense",
            font=("Segoe UI", 7),
            foreground="#94A3B8",
            background="#FFFFFF",
        ).pack(side="left", padx=(6, 0))
        ttk.Separator(year_box, orient="horizontal").pack(fill="x")
        self.year_canvas = tk.Canvas(year_box, height=170, bg="#FFFFFF", highlightthickness=0, bd=0)
        self.year_canvas.pack(fill="both", expand=True, padx=8, pady=8)
        # redraw on window resize (debounced via <Configure> on each canvas)
        for cv in (self.pie_canvas, self.trend_canvas, self.year_canvas):
            cv.bind("<Configure>", lambda e: self.after(150, self._redraw_graphs_safe))

    def _redraw_graphs_safe(self):
        try:
            if self.gr_year.get():
                self.refresh_graphs()
        except Exception:
            pass

    def _safe_graphs_refresh(self):
        try:
            self.refresh_graphs()
        except tk.TclError, ValueError:
            pass

    def _draw_pie(self, canvas, data):
        """Modern donut pie with soft shadows."""
        canvas.delete("all")
        canvas.update_idletasks()
        W, H = canvas.winfo_width(), canvas.winfo_height()
        if W < 60:
            W, H = 380, 220
        canvas.configure(bg="#FFFFFF")
        total = sum(v for _, v in data)
        if not data or total <= 0:
            canvas.create_text(W // 2, H // 2 - 8, text="◌", fill="#CBD5E1", font=("Segoe UI", 20))
            canvas.create_text(
                W // 2,
                H // 2 + 14,
                text="No data for this selection",
                fill="#94A3B8",
                font=("Segoe UI", 9),
            )
            return
        # subtle outer shadow
        data = data[: len(self.PIE_COLORS)]
        cx, cy = W * 0.38, H / 2
        r = min(W * 0.28, H / 2 - 20)
        # shadow
        canvas.create_oval(
            cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2, fill="#F1F5F9", outline=""
        )
        start = 90.0
        for i, (label, val) in enumerate(data):
            extent = 360.0 * val / total
            canvas.create_arc(
                cx - r,
                cy - r,
                cx + r,
                cy + r,
                start=start,
                extent=extent,
                fill=self.PIE_COLORS[i % len(self.PIE_COLORS)],
                outline="white",
                width=2,
            )
            mid = start + extent / 2
            import math

            lx = cx + (r + 18) * math.cos(math.radians(-mid))
            ly = cy + (r + 18) * math.sin(math.radians(-mid))
            pct = 100.0 * val / total
            if extent > 14:  # skip tiny-slice labels to avoid overlap
                canvas.create_text(
                    lx, ly, text=f"{pct:.0f}%", font=("Segoe UI", 8, "bold"), fill="#0F172A"
                )
            start += extent
        # inner donut hole
        canvas.create_oval(
            cx - r * 0.45,
            cy - r * 0.45,
            cx + r * 0.45,
            cy + r * 0.45,
            fill="white",
            outline="#F1F5F9",
            width=1,
        )
        canvas.create_text(
            cx, cy, text=f"{len(data)}", font=("Segoe UI", 14, "bold"), fill="#0F172A"
        )
        canvas.create_text(cx, cy + 16, text="categories", font=("Segoe UI", 7), fill="#94A3B8")

    def _draw_trend(self, canvas, inc, exp):
        """Modern line trend — soft grid, rounded lines."""
        canvas.delete("all")
        canvas.update_idletasks()
        W, H = canvas.winfo_width(), canvas.winfo_height()
        if W < 60:
            W, H = 380, 260
        canvas.configure(bg="#FFFFFF")
        n = len(inc)
        mx = max((max(inc) if inc else 0), (max(exp) if exp else 0), 1)
        L, R, T, B = 48, 12, 18, 30
        pw, ph = W - L - R, H - T - B
        # soft grid
        for frac, tag in [(0, "0"), (0.5, f"{mx / 2:,.0f}"), (1.0, f"{mx:,.0f}")]:
            y = T + ph * (1 - frac)
            canvas.create_line(L, y, W - R, y, fill="#F1F5F9", width=1, dash=(3, 3))
            canvas.create_text(L - 8, y, text=tag, anchor="e", font=("Segoe UI", 7), fill="#94A3B8")
        canvas.create_rectangle(L, T, W - R, H - B, outline="#E2E8F0", width=1)
        # x labels
        for d in sorted({1, 8, 15, 22, n} & set(range(1, n + 1))):
            x = L + pw * (d - 1) / max(n - 1, 1)
            canvas.create_text(x, H - B + 10, text=str(d), font=("Segoe UI", 7), fill="#94A3B8")
        if mx <= 0 or all(v == 0 for v in inc + exp):
            canvas.create_text(W // 2, H // 2 - 8, text="◌", fill="#CBD5E1", font=("Segoe UI", 20))
            canvas.create_text(
                W // 2,
                H // 2 + 14,
                text="No transactions this month",
                fill="#94A3B8",
                font=("Segoe UI", 9),
            )
            return

        def xy(day_idx, val):
            x = L + pw * day_idx / max(n - 1, 1)
            y = T + ph * (1 - val / mx)
            return x, y

        for series, color, bg in [(inc, "#059669", "#ECFDF5"), (exp, "#DC2626", "#FEF2F2")]:
            pts = [xy(i, v) for i, v in enumerate(series)]
            # soft area under line
            if len(pts) > 1:
                area = pts + [(pts[-1][0], H - B), (pts[0][0], H - B)]
                flat_area = [c for p in area for c in p]
                canvas.create_polygon(flat_area, fill=bg, outline="", stipple="")
            flat = [c for p in pts for c in p]
            canvas.create_line(
                *flat, fill=color, width=2.2, smooth=True, capstyle="round", joinstyle="round"
            )
            for x, y in pts[:: max(n // 10, 1)]:
                canvas.create_oval(
                    x - 3, y - 3, x + 3, y + 3, fill="white", outline=color, width=1.5
                )
        # legend pill
        lx = W - R - 152
        ly = T + 8
        canvas.create_rectangle(
            lx, ly, lx + 68, ly + 16, fill="#ECFDF5", outline="#A7F3D0", width=1
        )
        canvas.create_oval(lx + 8, ly + 5, lx + 16, ly + 13, fill="#059669", outline="")
        canvas.create_text(
            lx + 20, ly + 8, text="Income", anchor="w", font=("Segoe UI", 7, "bold"), fill="#065F46"
        )
        canvas.create_rectangle(
            lx + 76, ly, lx + 144, ly + 16, fill="#FEF2F2", outline="#FECACA", width=1
        )
        canvas.create_oval(lx + 84, ly + 5, lx + 92, ly + 13, fill="#DC2626", outline="")
        canvas.create_text(
            lx + 96,
            ly + 8,
            text="Expense",
            anchor="w",
            font=("Segoe UI", 7, "bold"),
            fill="#991B1B",
        )

    def _draw_yearly(self, canvas, rows):
        """Modern grouped bars — soft palette, rounded look."""
        canvas.delete("all")
        canvas.update_idletasks()
        W, H = canvas.winfo_width(), canvas.winfo_height()
        if W < 60:
            W, H = 760, 190
        canvas.configure(bg="#FFFFFF")
        mx = max([max(i, e) for _, i, e in rows] + [1])
        L, R, T, B = 48, 12, 18, 26
        pw, ph = W - L - R, H - T - B
        for frac, tag in [(0, "0"), (0.5, f"{mx / 2:,.0f}"), (1.0, f"{mx:,.0f}")]:
            y = T + ph * (1 - frac)
            canvas.create_line(L, y, W - R, y, fill="#F1F5F9", width=1, dash=(3, 3))
            canvas.create_text(L - 8, y, text=tag, anchor="e", font=("Segoe UI", 7), fill="#94A3B8")
        canvas.create_rectangle(L, T, W - R, H - B, outline="#E2E8F0", width=1)
        slot = pw / 12
        bw = min(slot * 0.30, 20)
        for i, (m, iv, ev) in enumerate(rows):
            x0 = L + slot * i + slot / 2
            ih = ph * iv / mx
            eh = ph * ev / mx
            # track
            canvas.create_rectangle(
                x0 - bw - 1, H - B - ph, x0 + bw + 1, H - B, fill="#F8FAFC", outline="#F1F5F9"
            )
            canvas.create_rectangle(
                x0 - bw - 1, H - B - ih, x0 - 1, H - B, fill="#059669", outline="", width=0
            )
            canvas.create_rectangle(
                x0 + 1, H - B - eh, x0 + bw + 1, H - B, fill="#DC2626", outline="", width=0
            )
            # month label
            col = "#0F172A" if (iv + ev) > 0 else "#94A3B8"
            canvas.create_text(
                x0,
                H - B + 10,
                text=calendar.month_abbr[m],
                font=("Segoe UI", 7, "bold" if (iv + ev) > 0 else "normal"),
                fill=col,
            )
        if all(i == 0 and e == 0 for _, i, e in rows):
            canvas.create_text(W // 2, H // 2 - 8, text="◌", fill="#CBD5E1", font=("Segoe UI", 20))
            canvas.create_text(
                W // 2,
                H // 2 + 14,
                text="No transactions this year",
                fill="#94A3B8",
                font=("Segoe UI", 9),
            )
            return
        # legend pills
        lx = W - R - 152
        ly = T + 6
        canvas.create_rectangle(
            lx, ly, lx + 68, ly + 16, fill="#ECFDF5", outline="#A7F3D0", width=1
        )
        canvas.create_oval(lx + 8, ly + 5, lx + 16, ly + 11, fill="#059669", outline="")
        canvas.create_text(
            lx + 20, ly + 8, text="Income", anchor="w", font=("Segoe UI", 7, "bold"), fill="#065F46"
        )
        canvas.create_rectangle(
            lx + 76, ly, lx + 144, ly + 16, fill="#FEF2F2", outline="#FECACA", width=1
        )
        canvas.create_oval(lx + 84, ly + 5, lx + 92, ly + 11, fill="#DC2626", outline="")
        canvas.create_text(
            lx + 96,
            ly + 8,
            text="Expense",
            anchor="w",
            font=("Segoe UI", 7, "bold"),
            fill="#991B1B",
        )

    def refresh_graphs(self):
        try:
            y, m = int(self.gr_year.get()), int(self.gr_month.get())
            d1, d2 = db_month_bounds(y, m)
        except Exception:
            return
        inc, exp, bal = db_totals(d1, d2)
        self.lbl_graph_sum.config(
            text=f"{y}-{m:02d}: Income ₹{inc:,.2f} • Expense ₹{exp:,.2f} • Balance ₹{bal:,.2f}"
        )
        # pie
        cats = db_category_summary(d1, d2, self.gr_type.get())
        self._draw_pie(self.pie_canvas, cats)
        self.pie_legend.delete("1.0", "end")
        total = sum(v for _, v in cats) or 1
        if not cats:
            self.pie_legend.insert("end", "No data for this selection.")
        else:
            for i, (c, amt) in enumerate(cats[: len(self.PIE_COLORS)]):
                self.pie_legend.insert("end", f"■ {c}: ₹{amt:,.2f} ({100 * amt / total:.1f}%)\n")
        # trend
        inc_s, exp_s = db_daily_series(y, m)
        self._draw_trend(self.trend_canvas, inc_s, exp_s)
        # yearly
        self._draw_yearly(self.year_canvas, db_yearly_summary(y))

    # -- DB maintenance dialog (WAL / VACUUM / integrity) --
    def open_db_tools(self):
        dlg = tk.Toplevel(self)
        dlg.title("DB Tools — Maintenance & Diagnostics")
        dlg.geometry("420x280")
        dlg.transient(self)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(
            frm,
            text="Database: " + DB_PATH,
            wraplength=380,
            foreground="#555",
            font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(0, 8))
        # stats
        with contextlib.closing(get_conn()) as conn:
            n_txn = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
            n_cat = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
            jmode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            ic = conn.execute("PRAGMA integrity_check").fetchone()[0]
        ttk.Label(
            frm,
            text=f"Transactions: {n_txn}   Categories: {n_cat}   Journal: {jmode}",
            font=("Segoe UI", 9),
        ).pack(anchor="w")
        ttk.Label(
            frm,
            text=f"Integrity: {ic}",
            font=("Segoe UI", 9),
            foreground="#1a7f37" if ic == "ok" else "#cf222e",
        ).pack(anchor="w", pady=(0, 12))

        def do_vacuum():
            try:
                db_vacuum()
                messagebox.showinfo(
                    "VACUUM", "Database compacted (VACUUM) successfully.", parent=dlg
                )
                self.refresh_all()
            except Exception as e:
                messagebox.showerror("VACUUM", str(e), parent=dlg)

        def do_integrity():
            res = db_integrity_check()
            if res == "ok":
                messagebox.showinfo("Integrity", "PRAGMA integrity_check: ok", parent=dlg)
            else:
                messagebox.showwarning("Integrity", f"Issues found:\n{res}", parent=dlg)

        def do_backup():
            path = filedialog.asksaveasfilename(
                defaultextension=".db",
                filetypes=[("SQLite DB", "*.db")],
                initialfile="expenses_backup.db",
            )
            if not path:
                return
            try:
                with contextlib.closing(get_conn()) as src:
                    bak = sqlite3.connect(path)
                    src.backup(bak)
                    bak.close()
                messagebox.showinfo("Backup", f"Backup saved to:\n{path}", parent=dlg)
            except Exception as e:
                messagebox.showerror("Backup", str(e), parent=dlg)

        ttk.Button(frm, text="🧹 VACUUM (Compact DB)", command=do_vacuum).pack(fill="x", pady=3)
        ttk.Button(frm, text="🔍 Integrity Check", command=do_integrity).pack(fill="x", pady=3)
        ttk.Button(frm, text="💾 Backup DB…", command=do_backup).pack(fill="x", pady=3)
        ttk.Button(frm, text="Close", command=dlg.destroy).pack(fill="x", pady=(14, 0))

    # -- master refresh --
    def refresh_all(self):
        self.refresh_dashboard()
        self.refresh_transactions()
        self.refresh_categories()
        self.refresh_reports()
        self.refresh_graphs()


def main():
    init_db()
    app = ExpenseApp()
    app.mainloop()


if __name__ == "__main__":
    main()
