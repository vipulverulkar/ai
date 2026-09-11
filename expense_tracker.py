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
import os
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
import calendar
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# ---------------------------------------------------------------- DB layer
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_DIR, "expenses.db")

DEFAULT_INCOME_CATS = ["Salary", "Business", "Freelance", "Interest", "Gift Received", "Other Income"]
DEFAULT_EXPENSE_CATS = ["Food", "Groceries", "Rent", "Transport", "Utilities",
                        "Shopping", "Health", "Education", "Entertainment", "Savings", "Other Expense"]


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
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
    # seed categories once
    cur.execute("SELECT COUNT(*) FROM categories")
    if cur.fetchone()[0] == 0:
        for c in DEFAULT_INCOME_CATS:
            cur.execute("INSERT INTO categories(name,type) VALUES(?, 'Income')", (c,))
        for c in DEFAULT_EXPENSE_CATS:
            cur.execute("INSERT INTO categories(name,type) VALUES(?, 'Expense')", (c,))
    conn.commit()
    conn.close()


# ---- CRUD helpers ---------------------------------------------------------
def db_add_txn(txn_date, txn_type, category, amount, note=""):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO transactions(date,type,category,amount,note) VALUES(?,?,?,?,?)",
                (txn_date, txn_type, category, amount, note))
    conn.commit()
    conn.close()


def db_update_txn(txn_id, txn_date, txn_type, category, amount, note=""):
    conn = get_conn()
    conn.execute("UPDATE transactions SET date=?,type=?,category=?,amount=?,note=? WHERE id=?",
                 (txn_date, txn_type, category, amount, note, txn_id))
    conn.commit()
    conn.close()


def db_delete_txn(txn_id):
    conn = get_conn()
    conn.execute("DELETE FROM transactions WHERE id=?", (txn_id,))
    conn.commit()
    conn.close()


def db_query_txns(date_from=None, date_to=None, txn_type="All", category="All", search=""):
    conn = get_conn()
    q = "SELECT id,date,type,category,amount,note FROM transactions WHERE 1=1"
    params = []
    if date_from:
        q += " AND date >= ?"; params.append(date_from)
    if date_to:
        q += " AND date <= ?"; params.append(date_to)
    if txn_type in ("Income", "Expense"):
        q += " AND type = ?"; params.append(txn_type)
    if category != "All":
        q += " AND category = ?"; params.append(category)
    if search.strip():
        q += " AND (category LIKE ? OR note LIKE ? OR CAST(amount AS TEXT) LIKE ?)"
        s = f"%{search.strip()}%"
        params += [s, s, s]
    q += " ORDER BY date DESC, id DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
    return rows


def db_totals(date_from=None, date_to=None):
    rows = db_query_txns(date_from, date_to)
    inc = sum(r[4] for r in rows if r[2] == "Income")
    exp = sum(r[4] for r in rows if r[2] == "Expense")
    return inc, exp, inc - exp


def db_category_summary(date_from=None, date_to=None, txn_type="Expense"):
    conn = get_conn()
    q = "SELECT category, SUM(amount) FROM transactions WHERE type=? "
    params = [txn_type]
    if date_from:
        q += " AND date >= ?"; params.append(date_from)
    if date_to:
        q += " AND date <= ?"; params.append(date_to)
    q += " GROUP BY category ORDER BY SUM(amount) DESC"
    rows = conn.execute(q, params).fetchall()
    conn.close()
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
    conn = get_conn()
    per_day = conn.execute(
        """SELECT date,
                  SUM(CASE WHEN type='Income' THEN amount ELSE 0 END),
                  SUM(CASE WHEN type='Expense' THEN amount ELSE 0 END)
           FROM transactions WHERE date BETWEEN ? AND ?
           GROUP BY date""", (d1, d2)).fetchall()
    conn.close()
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
    conn = get_conn()
    rows = conn.execute(
        """SELECT CAST(substr(date, 6, 2) AS INTEGER),
                  SUM(CASE WHEN type='Income' THEN amount ELSE 0 END),
                  SUM(CASE WHEN type='Expense' THEN amount ELSE 0 END)
           FROM transactions WHERE substr(date, 1, 4) = ?
           GROUP BY substr(date, 6, 2)""", (f"{year:04d}",)).fetchall()
    conn.close()
    have = {r[0]: (r[1] or 0, r[2] or 0) for r in rows}
    return [(m, *have.get(m, (0, 0))) for m in range(1, 13)]


def db_get_categories(txn_type=None):
    conn = get_conn()
    if txn_type:
        rows = conn.execute("SELECT id,name,type FROM categories WHERE type=? ORDER BY name",
                            (txn_type,)).fetchall()
    else:
        rows = conn.execute("SELECT id,name,type FROM categories ORDER BY type,name").fetchall()
    conn.close()
    return rows


def db_add_category(name, txn_type):
    conn = get_conn()
    try:
        conn.execute("INSERT INTO categories(name,type) VALUES(?,?)", (name.strip(), txn_type))
        conn.commit()
        ok = True
    except sqlite3.IntegrityError:
        ok = False
    conn.close()
    return ok


def db_delete_category(cat_id):
    conn = get_conn()
    conn.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    conn.commit()
    conn.close()


def db_count_txns_for_category(name, txn_type):
    conn = get_conn()
    n = conn.execute("SELECT COUNT(*) FROM transactions WHERE category=? AND type=?",
                     (name, txn_type)).fetchone()[0]
    conn.close()
    return n


def db_update_category(cat_id, new_name, new_type, update_txns=True):
    """Rename / re-type a category. Optionally retag matching transactions too.
    Returns (True, n_updated_txns) or (False, error_message)."""
    new_name = new_name.strip()
    if not new_name:
        return False, "Name cannot be empty."
    if new_type not in ("Income", "Expense"):
        return False, "Type must be Income or Expense."
    conn = get_conn()
    old = conn.execute("SELECT name, type FROM categories WHERE id=?", (cat_id,)).fetchone()
    if not old:
        conn.close()
        return False, "Category not found."
    old_name, old_type = old
    if (old_name, old_type) == (new_name, new_type):
        conn.close()
        return True, 0
    dup = conn.execute("SELECT id FROM categories WHERE name=? AND type=? AND id<>?",
                       (new_name, new_type, cat_id)).fetchone()
    if dup:
        conn.close()
        return False, f"'{new_name}' already exists under {new_type}."
    conn.execute("UPDATE categories SET name=?, type=? WHERE id=?",
                 (new_name, new_type, cat_id))
    n = 0
    if update_txns:
        cur = conn.execute("UPDATE transactions SET category=?, type=? "
                           "WHERE category=? AND type=?",
                           (new_name, new_type, old_name, old_type))
        n = cur.rowcount
    conn.commit()
    conn.close()
    return True, n


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
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except Exception:
            pass
        style.configure("TNotebook.Tab", padding=(14, 6), font=("Segoe UI", 10, "bold"))
        style.configure("Card.TFrame", background="#ffffff", relief="raised", borderwidth=1)
        style.configure("CardTitle.TLabel", background="#ffffff", font=("Segoe UI", 9), foreground="#666")
        style.configure("CardValue.TLabel", background="#ffffff", font=("Segoe UI", 16, "bold"))
        style.configure("Header.TLabel", font=("Segoe UI", 14, "bold"))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))

    # -- layout -----------------------------------------------------------
    def _build_layout(self):
        top = ttk.Frame(self, padding=(12, 10, 12, 0))
        top.pack(fill="x")
        ttk.Label(top, text="💰  Daily Expense Tracker", style="Header.TLabel").pack(side="left")
        ttk.Label(top, text=f"  DB: {DB_PATH}", foreground="#888",
                  font=("Segoe UI", 8)).pack(side="left", padx=8)
        ttk.Button(top, text="＋ Add Transaction", style="Accent.TButton",
                   command=self.open_txn_dialog).pack(side="right")

        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=10)

        self.tab_dash = ttk.Frame(self.nb, padding=10)
        self.tab_txn = ttk.Frame(self.nb, padding=10)
        self.tab_cat = ttk.Frame(self.nb, padding=10)
        self.tab_rep = ttk.Frame(self.nb, padding=10)
        self.tab_graph = ttk.Frame(self.nb, padding=10)
        self.nb.add(self.tab_dash, text="  📊 Dashboard  ")
        self.nb.add(self.tab_txn, text="  🧾 Transactions  ")
        self.nb.add(self.tab_cat, text="  🗂 Categories  ")
        self.nb.add(self.tab_rep, text="  📅 Daily / Monthly Reports  ")
        self.nb.add(self.tab_graph, text="  📈 Graphs  ")

        self._build_dashboard()
        self._build_transactions()
        self._build_categories()
        self._build_reports()
        self._build_graphs()

    # ================= DASHBOARD =================
    def _build_dashboard(self):
        # month selector
        bar = ttk.Frame(self.tab_dash)
        bar.pack(fill="x", pady=(0, 10))
        ttk.Label(bar, text="Month:").pack(side="left")
        today = date.today()
        self.dash_year = tk.IntVar(value=today.year)
        self.dash_month = tk.IntVar(value=today.month)
        ttk.Spinbox(bar, from_=2000, to=2100, width=6, textvariable=self.dash_year,
                    command=self.refresh_dashboard).pack(side="left", padx=4)
        ttk.Spinbox(bar, from_=1, to=12, width=4, textvariable=self.dash_month,
                    command=self.refresh_dashboard).pack(side="left", padx=4)
        ttk.Button(bar, text="This Month",
                   command=lambda: (self.dash_year.set(date.today().year),
                                    self.dash_month.set(date.today().month),
                                    self.refresh_dashboard())).pack(side="left", padx=8)
        ttk.Button(bar, text="↻ Refresh", command=self.refresh_all).pack(side="right")

        cards = ttk.Frame(self.tab_dash)
        cards.pack(fill="x")
        self.card_vars = {}
        for key, title, color in [("inc", "Income", "#1a7f37"),
                                 ("exp", "Expense", "#cf222e"),
                                 ("bal", "Balance", "#0969da"),
                                 ("rate", "Savings %", "#8250df")]:
            f = ttk.Frame(cards, style="Card.TFrame", padding=12)
            f.pack(side="left", fill="x", expand=True, padx=5)
            ttk.Label(f, text=title, style="CardTitle.TLabel").pack(anchor="w")
            v = ttk.Label(f, text="₹0", style="CardValue.TLabel", foreground=color)
            v.pack(anchor="w")
            self.card_vars[key] = v

        mid = ttk.Frame(self.tab_dash)
        mid.pack(fill="both", expand=True, pady=10)

        left = ttk.LabelFrame(mid, text="Recent transactions (latest 10)", padding=6)
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.dash_tree = self._make_tree(left, height=10)
        self.dash_tree.pack(fill="both", expand=True)

        right = ttk.LabelFrame(mid, text="Expense by category (this month)", padding=6)
        right.pack(side="right", fill="both", expand=True, padx=(5, 0))
        self.dash_chart = tk.Canvas(right, height=260, bg="white", highlightthickness=1,
                                    highlightbackground="#ddd")
        self.dash_chart.pack(fill="both", expand=True)
        self.dash_cat_text = tk.Text(right, height=8, font=("Segoe UI", 9))
        self.dash_cat_text.pack(fill="x")

    def _make_tree(self, parent, height=12):
        cols = ("id", "date", "type", "category", "amount", "note")
        tree = ttk.Treeview(parent, columns=cols, show="headings", height=height)
        widths = {"id": 50, "date": 100, "type": 80, "category": 140, "amount": 100, "note": 250}
        for c in cols:
            tree.heading(c, text=c.capitalize())
            tree.column(c, width=widths[c], anchor="center" if c != "note" else "w")
        tree.column("id", width=45)
        vsb = ttk.Scrollbar(parent, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
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
        # chart
        cats = db_category_summary(d1, d2, "Expense")
        self._draw_bar(self.dash_chart, cats)
        self.dash_cat_text.delete("1.0", "end")
        if not cats:
            self.dash_cat_text.insert("end", "No expenses this month.")
        else:
            for c, amt in cats:
                self.dash_cat_text.insert("end", f"• {c}: ₹{amt:,.2f}\n")

    def _draw_bar(self, canvas, data, color="#0969da"):
        canvas.delete("all")
        canvas.update_idletasks()
        W, H = canvas.winfo_width(), canvas.winfo_height()
        if W < 50:
            W, H = 380, 220
        if not data:
            canvas.create_text(W // 2, H // 2, text="No data", fill="#999", font=("Segoe UI", 11))
            return
        data = data[:8]
        mx = max(v for _, v in data) or 1
        left, top, bottom = 90, 15, H - 25
        bh = (H - top - bottom) / len(data)
        for i, (cat, val) in enumerate(data):
            y0 = top + i * bh + 3
            y1 = y0 + bh - 6
            w = (W - left - 20) * (val / mx)
            canvas.create_text(left - 6, (y0 + y1) / 2, text=cat[:14], anchor="e",
                               font=("Segoe UI", 8), fill="#333")
            canvas.create_rectangle(left, y0, left + w, y1, fill=color, outline="")
            canvas.create_text(left + w + 4, (y0 + y1) / 2, text=f"{val:,.0f}",
                               anchor="w", font=("Segoe UI", 8), fill="#333")

    # ================= TRANSACTIONS =================
    def _build_transactions(self):
        f = ttk.LabelFrame(self.tab_txn, text="Filters", padding=8)
        f.pack(fill="x", pady=(0, 8))
        today = date.today()
        first = today.replace(day=1).isoformat()
        last = today.isoformat()
        self.f_from = tk.StringVar(value=first)
        self.f_to = tk.StringVar(value=last)
        self.f_type = tk.StringVar(value="All")
        self.f_cat = tk.StringVar(value="All")
        self.f_search = tk.StringVar()

        ttk.Label(f, text="From (YYYY-MM-DD):").grid(row=0, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.f_from, width=13).grid(row=0, column=1, padx=4)
        ttk.Label(f, text="To:").grid(row=0, column=2)
        ttk.Entry(f, textvariable=self.f_to, width=13).grid(row=0, column=3, padx=4)
        ttk.Label(f, text="Type:").grid(row=0, column=4, padx=(10, 0))
        ttk.Combobox(f, textvariable=self.f_type, values=["All", "Income", "Expense"],
                     width=10, state="readonly").grid(row=0, column=5, padx=4)
        ttk.Label(f, text="Category:").grid(row=0, column=6, padx=(10, 0))
        self.f_cat_box = ttk.Combobox(f, textvariable=self.f_cat, width=14)
        self.f_cat_box.grid(row=0, column=7, padx=4)
        ttk.Label(f, text="Search:").grid(row=1, column=0, sticky="w", pady=6)
        ttk.Entry(f, textvariable=self.f_search, width=30).grid(row=1, column=1, columnspan=3,
                                                                sticky="w", pady=6, padx=4)
        ttk.Button(f, text="Apply", command=self.refresh_transactions).grid(row=1, column=4, padx=4)
        ttk.Button(f, text="Clear", command=self._clear_filters).grid(row=1, column=5)
        self.lbl_txn_sum = ttk.Label(f, text="", font=("Segoe UI", 9, "bold"), foreground="#333")
        self.lbl_txn_sum.grid(row=1, column=6, columnspan=2, sticky="e")

        for var in (self.f_from, self.f_to, self.f_type, self.f_search):
            pass  # apply on button to avoid date-parse spam

        list_frame = ttk.Frame(self.tab_txn)
        list_frame.pack(fill="both", expand=True)
        self.txn_tree = self._make_tree(list_frame, height=16)
        self.txn_tree.pack(fill="both", expand=True)
        self.txn_tree.bind("<Double-1>", lambda e: self.open_txn_dialog(edit=True))

        btns = ttk.Frame(self.tab_txn)
        btns.pack(fill="x", pady=8)
        ttk.Button(btns, text="＋ Add", command=self.open_txn_dialog).pack(side="left", padx=4)
        ttk.Button(btns, text="✏ Edit Selected",
                   command=lambda: self.open_txn_dialog(edit=True)).pack(side="left", padx=4)
        ttk.Button(btns, text="🗑 Delete Selected", command=self.delete_selected).pack(side="left", padx=4)
        ttk.Button(btns, text="⬇ Export CSV", command=self.export_transactions_csv).pack(side="right", padx=4)

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
            rows = db_query_txns(self.f_from.get().strip() or None,
                                 self.f_to.get().strip() or None,
                                 self.f_type.get(), self.f_cat.get(), self.f_search.get())
        except Exception as ex:
            messagebox.showerror("Filter error", str(ex))
            return
        for i in self.txn_tree.get_children():
            self.txn_tree.delete(i)
        for r in rows:
            tag = "inc" if r[2] == "Income" else "exp"
            self.txn_tree.insert("", "end", values=(r[0], r[1], r[2], r[3], f"{r[4]:.2f}", r[5]),
                                 tags=(tag,))
        self.txn_tree.tag_configure("inc", foreground="#1a7f37")
        self.txn_tree.tag_configure("exp", foreground="#cf222e")
        inc = sum(r[4] for r in rows if r[2] == "Income")
        exp = sum(r[4] for r in rows if r[2] == "Expense")
        self.lbl_txn_sum.config(text=f"Income ₹{inc:,.2f}   •   Expense ₹{exp:,.2f}   •   Balance ₹{inc-exp:,.2f}")

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
        if messagebox.askyesno("Delete", f"Delete transaction #{tid} ({vals[1]} {vals[3]} ₹{vals[4]})?"):
            db_delete_txn(tid)
            self.refresh_all()

    def export_transactions_csv(self):
        rows = db_query_txns(self.f_from.get().strip() or None, self.f_to.get().strip() or None,
                             self.f_type.get(), self.f_cat.get(), self.f_search.get())
        if not rows:
            messagebox.showinfo("Export", "No rows to export.")
            return
        path = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                            initialfile="transactions.csv")
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
            init = {"id": tid, "date": vals[1], "type": vals[2],
                    "category": vals[3], "amount": vals[4], "note": vals[5]}
        else:
            init = {"id": None, "date": date.today().isoformat(), "type": "Expense",
                    "category": "", "amount": "", "note": ""}

        dlg = tk.Toplevel(self)
        dlg.title("Edit Transaction" if edit else "Add Transaction")
        dlg.geometry("380x360")
        dlg.transient(self)
        dlg.grab_set()

        frm = ttk.Frame(dlg, padding=16)
        frm.pack(fill="both", expand=True)

        v_date = tk.StringVar(value=init["date"])
        v_type = tk.StringVar(value=init["type"])
        v_cat = tk.StringVar(value=init["category"])
        v_amt = tk.StringVar(value=str(init["amount"]))
        v_note = tk.StringVar(value=init["note"])

        ttk.Label(frm, text="Date (YYYY-MM-DD):").pack(anchor="w")
        ttk.Entry(frm, textvariable=v_date).pack(fill="x", pady=(0, 8))
        ttk.Label(frm, text="Type:").pack(anchor="w")
        type_box = ttk.Combobox(frm, textvariable=v_type, values=["Income", "Expense"],
                                state="readonly")
        type_box.pack(fill="x", pady=(0, 8))
        ttk.Label(frm, text="Category:").pack(anchor="w")
        cat_box = ttk.Combobox(frm, textvariable=v_cat)
        cat_box.pack(fill="x", pady=(0, 8))

        def load_cats(*_):
            cat_box["values"] = [n for _, n, _ in db_get_categories(v_type.get())]
            if v_cat.get() not in cat_box["values"] and cat_box["values"]:
                v_cat.set(cat_box["values"][0])
        v_type.trace_add("write", load_cats)
        load_cats()
        if init["category"]:
            v_cat.set(init["category"])

        ttk.Label(frm, text="Amount (₹):").pack(anchor="w")
        ttk.Entry(frm, textvariable=v_amt).pack(fill="x", pady=(0, 8))
        ttk.Label(frm, text="Note:").pack(anchor="w")
        ttk.Entry(frm, textvariable=v_note).pack(fill="x", pady=(0, 12))

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
                db_update_txn(init["id"], d, v_type.get(), v_cat.get().strip(), amt, v_note.get().strip())
            else:
                db_add_txn(d, v_type.get(), v_cat.get().strip(), amt, v_note.get().strip())
            dlg.destroy()
            self.refresh_all()
            self.nb.select(self.tab_txn)

        ttk.Button(frm, text="💾 Save", style="Accent.TButton", command=save).pack(fill="x")
        dlg.bind("<Return>", lambda e: save())

    # ================= CATEGORIES =================
    def _build_categories(self):
        topbar = ttk.Frame(self.tab_cat)
        topbar.pack(fill="x", pady=(0, 8))
        ttk.Button(topbar, text="🗂  Open Category Manager  (full CRUD form)",
                   style="Accent.TButton",
                   command=self.open_category_manager).pack(side="left")
        ttk.Button(topbar, text="↻ Refresh",
                   command=self.refresh_all).pack(side="right")
        wrap = ttk.Frame(self.tab_cat)
        wrap.pack(fill="both", expand=True)
        self.cat_trees = {}
        for col, ttype in enumerate(["Income", "Expense"]):
            box = ttk.LabelFrame(wrap, text=f"{ttype} categories", padding=8)
            box.grid(row=0, column=col, sticky="nsew", padx=6)
            tree = ttk.Treeview(box, columns=("id", "name"), show="headings", height=14)
            tree.heading("id", text="ID")
            tree.heading("name", text="Category")
            tree.column("id", width=50, anchor="center")
            tree.column("name", width=200)
            tree.pack(fill="both", expand=True)
            self.cat_trees[ttype] = tree
            tree.bind("<Double-1>", lambda e, t=ttype: self.rename_category(t))
            row = ttk.Frame(box)
            row.pack(fill="x", pady=6)
            var = tk.StringVar()
            ttk.Entry(row, textvariable=var, width=22).pack(side="left", padx=(0, 6))
            ttk.Button(row, text="Add",
                       command=lambda t=ttype, v=var: self.add_category(t, v)).pack(side="left")
            ttk.Button(row, text="✏ Rename",
                       command=lambda t=ttype: self.rename_category(t)).pack(side="left", padx=4)
            ttk.Button(row, text="Delete",
                       command=lambda t=ttype: self.delete_category(t)).pack(side="right")
            setattr(self, f"cat_var_{ttype}", var)
        wrap.columnconfigure(0, weight=1)
        wrap.columnconfigure(1, weight=1)
        ttk.Label(self.tab_cat, foreground="#666",
                  text="Tip: double-click a category (or ✏ Rename) to edit it. "
                       "Renaming can also retag old transactions. "
                       "Deleting a category does not delete old transactions.").pack(pady=6)

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
        ttk.Combobox(frm, textvariable=v_type, values=["Income", "Expense"],
                     state="readonly").pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(frm, variable=v_update,
                        text=f"Also update {n_txn} existing transaction(s)").pack(anchor="w", pady=(0, 12))

        def save():
            ok, info = db_update_category(cid, v_name.get(), v_type.get(), v_update.get())
            if not ok:
                messagebox.showerror("Invalid", info, parent=dlg)
                return
            dlg.destroy()
            self.refresh_all()
            if info:
                messagebox.showinfo("Category",
                                    f"Renamed '{old_name}' → '{v_name.get().strip()}'.\n"
                                    f"{info} transaction(s) retagged.")

        ttk.Button(frm, text="💾 Save", style="Accent.TButton", command=save).pack(fill="x")
        dlg.bind("<Return>", lambda e: save())

    def refresh_categories(self):
        for ttype, tree in self.cat_trees.items():
            for i in tree.get_children():
                tree.delete(i)
            for cid, name, _ in db_get_categories(ttype):
                tree.insert("", "end", values=(cid, name))

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
        ttk.Combobox(filt, textvariable=v_filter, values=["All", "Income", "Expense"],
                     width=10, state="readonly").pack(side="left", padx=6)

        # -- list (Read) --
        list_box = ttk.LabelFrame(mgr, text="Categories (double-click a row to edit)", padding=8)
        list_box.pack(fill="both", expand=True, padx=12, pady=8)
        tree = ttk.Treeview(list_box, columns=("id", "name", "type", "used"),
                            show="headings", height=12)
        for col, txt, w, anc in [("id", "ID", 50, "center"), ("name", "Name", 200, "w"),
                                 ("type", "Type", 90, "center"), ("used", "Txns", 70, "center")]:
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
        ttk.Combobox(edit_box, textvariable=v_type, values=["Income", "Expense"],
                     width=10, state="readonly").grid(row=0, column=3, padx=6, pady=2)
        retag_chk = ttk.Checkbutton(edit_box, variable=v_retag,
                                    text="Retag existing transactions on rename")
        retag_chk.grid(row=1, column=0, columnspan=4, sticky="w", pady=2)
        lbl_hint = ttk.Label(edit_box, text="Mode: adding new  •  select a row + Edit to modify",
                             foreground="#666", font=("Segoe UI", 8))
        lbl_hint.grid(row=2, column=0, columnspan=4, sticky="w")

        def refresh_list():
            for i in tree.get_children():
                tree.delete(i)
            s = v_search.get().strip().lower()
            for cid, name, ctype in db_get_categories(
                    None if v_filter.get() == "All" else v_filter.get()):
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
                        "Category", f"'{name}' already exists under {v_type.get()}.", parent=mgr)
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
            lbl_hint.config(text=f"Mode: editing #{cid} '{name}' ({used} transaction(s)) — Save to apply")
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
                    f"name as plain text (history is not deleted).", parent=mgr)
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
        daily = ttk.LabelFrame(self.tab_rep, text="Daily Report", padding=8)
        daily.pack(fill="x", pady=(0, 8))
        self.rep_day = tk.StringVar(value=date.today().isoformat())
        ttk.Label(daily, text="Date (YYYY-MM-DD):").pack(side="left")
        ttk.Entry(daily, textvariable=self.rep_day, width=13).pack(side="left", padx=6)
        ttk.Button(daily, text="◀ Prev",
                   command=lambda: self._shift_day(-1)).pack(side="left", padx=2)
        ttk.Button(daily, text="Next ▶",
                   command=lambda: self._shift_day(1)).pack(side="left", padx=2)
        ttk.Button(daily, text="Today", command=self._today_day).pack(side="left", padx=6)
        ttk.Button(daily, text="Show", command=self.refresh_reports).pack(side="left", padx=6)
        self.lbl_daily = ttk.Label(daily, text="", font=("Segoe UI", 10, "bold"))
        self.lbl_daily.pack(side="left", padx=12)

        # --- monthly ---
        monthly = ttk.LabelFrame(self.tab_rep, text="Monthly Report", padding=8)
        monthly.pack(fill="x", pady=(0, 8))
        t = date.today()
        self.rep_year = tk.IntVar(value=t.year)
        self.rep_month = tk.IntVar(value=t.month)
        ttk.Label(monthly, text="Year:").pack(side="left")
        ttk.Spinbox(monthly, from_=2000, to=2100, width=6, textvariable=self.rep_year,
                    command=self.refresh_reports).pack(side="left", padx=4)
        ttk.Label(monthly, text="Month:").pack(side="left")
        ttk.Spinbox(monthly, from_=1, to=12, width=4, textvariable=self.rep_month,
                    command=self.refresh_reports).pack(side="left", padx=4)
        ttk.Button(monthly, text="Show", command=self.refresh_reports).pack(side="left", padx=6)
        self.lbl_monthly = ttk.Label(monthly, text="", font=("Segoe UI", 10, "bold"))
        self.lbl_monthly.pack(side="left", padx=12)
        ttk.Button(monthly, text="⬇ Export Month CSV",
                   command=self.export_month_csv).pack(side="right")

        # --- results ---
        res = ttk.Frame(self.tab_rep)
        res.pack(fill="both", expand=True)
        left = ttk.LabelFrame(res, text="Day-wise totals (selected month)", padding=6)
        left.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.rep_day_tree = ttk.Treeview(left, columns=("day", "income", "expense", "balance"),
                                         show="headings", height=12)
        for c, w in [("day", 90), ("income", 100), ("expense", 100), ("balance", 100)]:
            self.rep_day_tree.heading(c, text=c.capitalize())
            self.rep_day_tree.column(c, width=w, anchor="center")
        self.rep_day_tree.pack(fill="both", expand=True)

        right = ttk.LabelFrame(res, text="Category breakdown (selected month)", padding=6)
        right.pack(side="right", fill="both", expand=True, padx=(5, 0))
        self.rep_type = tk.StringVar(value="Expense")
        ttk.Combobox(right, textvariable=self.rep_type, values=["Expense", "Income"],
                     width=10, state="readonly").pack(anchor="w")
        self.rep_type.trace_add("write", lambda *_: self.refresh_reports())
        self.rep_chart = tk.Canvas(right, height=180, bg="white", highlightthickness=1,
                                   highlightbackground="#ddd")
        self.rep_chart.pack(fill="both", expand=True, pady=4)
        self.rep_cat_tree = ttk.Treeview(right, columns=("cat", "total"), show="headings", height=6)
        self.rep_cat_tree.heading("cat", text="Category")
        self.rep_cat_tree.heading("total", text="Total (₹)")
        self.rep_cat_tree.column("cat", width=160)
        self.rep_cat_tree.column("total", width=110, anchor="e")
        self.rep_cat_tree.pack(fill="x")

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
            self.lbl_daily.config(text=f"{d}: {n} txn(s) • Income ₹{inc:,.2f} • "
                                       f"Expense ₹{exp:,.2f} • Balance ₹{bal:,.2f}")
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
        self.lbl_monthly.config(text=f"{y}-{m:02d}: Income ₹{inc:,.2f} • "
                                     f"Expense ₹{exp:,.2f} • Balance ₹{bal:,.2f}")
        # day-wise table
        for i in self.rep_day_tree.get_children():
            self.rep_day_tree.delete(i)
        conn = get_conn()
        per_day = conn.execute(
            """SELECT date,
                      SUM(CASE WHEN type='Income' THEN amount ELSE 0 END),
                      SUM(CASE WHEN type='Expense' THEN amount ELSE 0 END)
               FROM transactions WHERE date BETWEEN ? AND ?
               GROUP BY date ORDER BY date""", (d1, d2)).fetchall()
        conn.close()
        have = {r[0]: r for r in per_day}
        last_day = calendar.monthrange(y, m)[1]
        for day in range(1, last_day + 1):
            ds = f"{y:04d}-{m:02d}-{day:02d}"
            if ds in have:
                _, i_, e_ = have[ds]
                i_, e_ = i_ or 0, e_ or 0
                self.rep_day_tree.insert("", "end",
                                         values=(ds, f"{i_:,.2f}", f"{e_:,.2f}", f"{i_-e_:,.2f}"))
        # category breakdown + chart
        for i in self.rep_cat_tree.get_children():
            self.rep_cat_tree.delete(i)
        cats = db_category_summary(d1, d2, self.rep_type.get())
        for c, amt in cats:
            self.rep_cat_tree.insert("", "end", values=(c, f"{amt:,.2f}"))
        self._draw_bar(self.rep_chart, cats,
                       color="#1a7f37" if self.rep_type.get() == "Income" else "#cf222e")

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
        path = filedialog.asksaveasfilename(defaultextension=".csv",
                                            filetypes=[("CSV", "*.csv")],
                                            initialfile=f"report_{y}-{m:02d}.csv")
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
    PIE_COLORS = ["#0969da", "#1a7f37", "#cf222e", "#8250df", "#d97706", "#0e9f9f",
                  "#db61a2", "#6e7781", "#3fb950", "#e3b341", "#321283", "#c93c37"]

    def _build_graphs(self):
        bar = ttk.Frame(self.tab_graph)
        bar.pack(fill="x", pady=(0, 8))
        t = date.today()
        self.gr_year = tk.IntVar(value=t.year)
        self.gr_month = tk.IntVar(value=t.month)
        self.gr_type = tk.StringVar(value="Expense")
        ttk.Label(bar, text="Year:").pack(side="left")
        ttk.Spinbox(bar, from_=2000, to=2100, width=6, textvariable=self.gr_year,
                    command=self.refresh_graphs).pack(side="left", padx=4)
        ttk.Label(bar, text="Month (pie + trend):").pack(side="left", padx=(10, 0))
        ttk.Spinbox(bar, from_=1, to=12, width=4, textvariable=self.gr_month,
                    command=self.refresh_graphs).pack(side="left", padx=4)
        ttk.Label(bar, text="Pie shows:").pack(side="left", padx=(10, 0))
        ttk.Combobox(bar, textvariable=self.gr_type, values=["Expense", "Income"],
                     width=10, state="readonly").pack(side="left", padx=4)
        self.gr_type.trace_add("write", lambda *_: self.refresh_graphs())
        ttk.Button(bar, text="↻ Refresh", command=self.refresh_graphs).pack(side="right")
        self.lbl_graph_sum = ttk.Label(bar, text="", font=("Segoe UI", 9, "bold"))
        self.lbl_graph_sum.pack(side="left", padx=12)

        top = ttk.Frame(self.tab_graph)
        top.pack(fill="both", expand=True)
        pie_box = ttk.LabelFrame(top, text="Category share (pie)", padding=6)
        pie_box.pack(side="left", fill="both", expand=True, padx=(0, 5))
        self.pie_canvas = tk.Canvas(pie_box, bg="white", highlightthickness=1,
                                    highlightbackground="#ddd")
        self.pie_canvas.pack(fill="both", expand=True)
        self.pie_legend = tk.Text(pie_box, height=6, font=("Segoe UI", 9))
        self.pie_legend.pack(fill="x")

        trend_box = ttk.LabelFrame(top, text="Daily trend — income vs expense (line)", padding=6)
        trend_box.pack(side="right", fill="both", expand=True, padx=(5, 0))
        self.trend_canvas = tk.Canvas(trend_box, bg="white", highlightthickness=1,
                                      highlightbackground="#ddd")
        self.trend_canvas.pack(fill="both", expand=True)

        year_box = ttk.LabelFrame(self.tab_graph, text="Yearly overview — income vs expense per month (bars)",
                                  padding=6)
        year_box.pack(fill="both", expand=True, pady=(8, 0))
        self.year_canvas = tk.Canvas(year_box, height=190, bg="white", highlightthickness=1,
                                     highlightbackground="#ddd")
        self.year_canvas.pack(fill="both", expand=True)
        # redraw on window resize (debounced via <Configure> on each canvas)
        for cv in (self.pie_canvas, self.trend_canvas, self.year_canvas):
            cv.bind("<Configure>", lambda e: self.after(150, self._redraw_graphs_safe))

    def _redraw_graphs_safe(self):
        try:
            if self.gr_year.get():
                self.refresh_graphs()
        except Exception:
            pass

    def _draw_pie(self, canvas, data):
        """data: [(label, value), ...] -> pie slices + % labels."""
        canvas.delete("all")
        canvas.update_idletasks()
        W, H = canvas.winfo_width(), canvas.winfo_height()
        if W < 60:
            W, H = 380, 260
        total = sum(v for _, v in data)
        if not data or total <= 0:
            canvas.create_text(W // 2, H // 2, text="No data for this selection",
                               fill="#999", font=("Segoe UI", 11))
            return
        data = data[:len(self.PIE_COLORS)]
        cx, cy = W * 0.36, H / 2
        r = min(W * 0.30, H / 2 - 18)
        start = 90.0
        for i, (label, val) in enumerate(data):
            extent = 360.0 * val / total
            canvas.create_arc(cx - r, cy - r, cx + r, cy + r, start=start, extent=extent,
                              fill=self.PIE_COLORS[i % len(self.PIE_COLORS)], outline="white", width=2)
            mid = start + extent / 2
            import math
            lx = cx + (r + 16) * math.cos(math.radians(-mid))
            ly = cy + (r + 16) * math.sin(math.radians(-mid))
            pct = 100.0 * val / total
            if extent > 12:  # skip tiny-slice labels to avoid overlap
                canvas.create_text(lx, ly, text=f"{pct:.0f}%", font=("Segoe UI", 8, "bold"))
            start += extent

    def _draw_trend(self, canvas, inc, exp):
        """Two line series (green income, red expense) with axes + max labels."""
        canvas.delete("all")
        canvas.update_idletasks()
        W, H = canvas.winfo_width(), canvas.winfo_height()
        if W < 60:
            W, H = 380, 260
        n = len(inc)
        mx = max((max(inc) if inc else 0), (max(exp) if exp else 0), 1)
        L, R, T, B = 52, 14, 14, 30
        pw, ph = W - L - R, H - T - B
        # gridlines + y labels (0 / half / max)
        for frac, tag in [(0, "0"), (0.5, f"{mx/2:,.0f}"), (1.0, f"{mx:,.0f}")]:
            y = T + ph * (1 - frac)
            canvas.create_line(L, y, W - R, y, fill="#e5e5e5")
            canvas.create_text(L - 5, y, text=tag, anchor="e",
                               font=("Segoe UI", 7), fill="#666")
        canvas.create_rectangle(L, T, W - R, H - B, outline="#999")
        # x labels: 1st, 8th, 15th, 22nd, last
        for d in sorted({1, 8, 15, 22, n} & set(range(1, n + 1))):
            x = L + pw * (d - 1) / max(n - 1, 1)
            canvas.create_text(x, H - B + 8, text=str(d), font=("Segoe UI", 7), fill="#666")
        if mx <= 0 or all(v == 0 for v in inc + exp):
            canvas.create_text(W / 2, H / 2, text="No transactions this month",
                               fill="#999", font=("Segoe UI", 11))
            return

        def xy(day_idx, val):
            x = L + pw * day_idx / max(n - 1, 1)
            y = T + ph * (1 - val / mx)
            return x, y

        for series, color in [(inc, "#1a7f37"), (exp, "#cf222e")]:
            pts = [xy(i, v) for i, v in enumerate(series)]
            flat = [c for p in pts for c in p]
            canvas.create_line(*flat, fill=color, width=2, smooth=True)
            for x, y in pts[:: max(n // 10, 1)]:
                canvas.create_oval(x - 2, y - 2, x + 2, y + 2, fill=color, outline="")
        # legend
        canvas.create_rectangle(W - R - 150, T + 6, W - R - 138, T + 14, fill="#1a7f37", outline="")
        canvas.create_text(W - R - 134, T + 10, text="Income", anchor="w", font=("Segoe UI", 8))
        canvas.create_rectangle(W - R - 80, T + 6, W - R - 68, T + 14, fill="#cf222e", outline="")
        canvas.create_text(W - R - 64, T + 10, text="Expense", anchor="w", font=("Segoe UI", 8))

    def _draw_yearly(self, canvas, rows):
        """Grouped bars per month: green income + red expense, month initials below."""
        canvas.delete("all")
        canvas.update_idletasks()
        W, H = canvas.winfo_width(), canvas.winfo_height()
        if W < 60:
            W, H = 760, 190
        mx = max([max(i, e) for _, i, e in rows] + [1])
        L, R, T, B = 52, 14, 14, 26
        pw, ph = W - L - R, H - T - B
        for frac, tag in [(0, "0"), (0.5, f"{mx/2:,.0f}"), (1.0, f"{mx:,.0f}")]:
            y = T + ph * (1 - frac)
            canvas.create_line(L, y, W - R, y, fill="#e5e5e5")
            canvas.create_text(L - 5, y, text=tag, anchor="e",
                               font=("Segoe UI", 7), fill="#666")
        canvas.create_rectangle(L, T, W - R, H - B, outline="#999")
        slot = pw / 12
        bw = min(slot * 0.28, 22)
        for i, (m, iv, ev) in enumerate(rows):
            x0 = L + slot * i + slot / 2
            ih = ph * iv / mx
            eh = ph * ev / mx
            canvas.create_rectangle(x0 - bw - 1, H - B - ih, x0 - 1, H - B,
                                    fill="#1a7f37", outline="")
            canvas.create_rectangle(x0 + 1, H - B - eh, x0 + bw + 1, H - B,
                                    fill="#cf222e", outline="")
            canvas.create_text(x0, H - B + 9, text=calendar.month_abbr[m][0],
                               font=("Segoe UI", 8, "bold"), fill="#333")
        if all(i == 0 and e == 0 for _, i, e in rows):
            canvas.create_text(W / 2, H / 2, text="No transactions this year",
                               fill="#999", font=("Segoe UI", 11))
            return
        canvas.create_rectangle(W - R - 150, T + 4, W - R - 138, T + 12,
                                fill="#1a7f37", outline="")
        canvas.create_text(W - R - 134, T + 8, text="Income", anchor="w", font=("Segoe UI", 8))
        canvas.create_rectangle(W - R - 80, T + 4, W - R - 68, T + 12,
                                fill="#cf222e", outline="")
        canvas.create_text(W - R - 64, T + 8, text="Expense", anchor="w", font=("Segoe UI", 8))

    def refresh_graphs(self):
        try:
            y, m = int(self.gr_year.get()), int(self.gr_month.get())
            d1, d2 = db_month_bounds(y, m)
        except Exception:
            return
        inc, exp, bal = db_totals(d1, d2)
        self.lbl_graph_sum.config(
            text=f"{y}-{m:02d}: Income ₹{inc:,.2f} • Expense ₹{exp:,.2f} • Balance ₹{bal:,.2f}")
        # pie
        cats = db_category_summary(d1, d2, self.gr_type.get())
        self._draw_pie(self.pie_canvas, cats)
        self.pie_legend.delete("1.0", "end")
        total = sum(v for _, v in cats) or 1
        if not cats:
            self.pie_legend.insert("end", "No data for this selection.")
        else:
            for i, (c, amt) in enumerate(cats[:len(self.PIE_COLORS)]):
                self.pie_legend.insert("end", f"■ {c}: ₹{amt:,.2f} ({100*amt/total:.1f}%)\n")
        # trend
        inc_s, exp_s = db_daily_series(y, m)
        self._draw_trend(self.trend_canvas, inc_s, exp_s)
        # yearly
        self._draw_yearly(self.year_canvas, db_yearly_summary(y))

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
