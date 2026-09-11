# 💰 Daily Expense Tracker — Desktop App

Standalone desktop app with a **single-file database** (`expenses.db` via SQLite —
same idea as an MS Access `.accdb`: no server, just copy the file to back up / move PCs).

**No `pip install` needed** — uses only Python standard library (`tkinter` + `sqlite3`).

## Run

```bat
run.bat
```

or

```bash
python expense_tracker.py
```

On first run it creates `expenses.db` next to the script and seeds default categories.

## Features

| Area | Details |
|---|---|
| ➕➖ **CRUD transactions** | Add / Edit (double-click) / Delete Income & Expense with date, category, amount, note |
| 🗂 **Categories** | Separate Income & Expense lists, quick add/delete/rename in the tab, plus a dedicated **Category Manager window** (search, filter, usage counts, full CRUD with retag option) |
| 🔍 **Transactions tab** | Filter by date range, type, category, text search; live totals; Export CSV |
| 📊 **Dashboard** | Monthly Income / Expense / Balance / Savings % cards, recent 10, bar chart by category |
| 📅 **Daily report** | Pick date (Prev/Next/Today), shows count + totals |
| 🗓 **Monthly report** | Year/month picker, day-wise Income/Expense/Balance table, category breakdown + chart, Export Month CSV |
| 📈 **Graphs** | Category **pie chart** with % + legend (Income/Expense toggle), daily **trend line** (income vs expense), **yearly bar chart** (12 months grouped bars) |
| 💾 **Standalone DB** | `expenses.db` — back it up by copying the file, like MS Access |

## Default categories

- **Income:** Salary, Business, Freelance, Interest, Gift Received, Other Income
- **Expense:** Food, Groceries, Rent, Transport, Utilities, Shopping, Health, Education, Entertainment, Savings, Other Expense

You can add your own in the **Categories** tab.

## Make a real `.exe`

```bat
build_exe.bat
```

Produces `dist\ExpenseTracker.exe` — double-click to run on any Windows PC
(even without Python). `expenses.db` is created beside the EXE.

## Files

- `expense_tracker.py` — the whole app (DB layer + UI)
- `seed_dummy.py` — generates demo data (`python seed_dummy.py [months]`, default 6)
- `expenses.db` — your data (auto-created, portable single file)
- `run.bat` — one-click launch on Windows
- `build_exe.bat` — build standalone EXE with PyInstaller
