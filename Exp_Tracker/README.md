# Expense Tracker (Python + Flask + SQLite)

Web-based expense tracker with income/expense categories, transaction management, and daily/monthly summary reports.

## Features
- Add / edit / delete transactions (amount, type, category, date, note)
- Category management with type `income` or `expense`
- Dashboard: today's totals, this month's totals, total balance, quick-add form
- Transactions page: filterable list (type, category, month, search) with edit/delete, paginated (10/25/50/100 per page)
- Reports:
  - **Daily**: per-day income/expense/savings for a selected month + category breakdown
  - **Monthly**: per-month income/expense/savings for a selected year + category breakdown
- SQLite database (`expenses.db`, auto-created), no external DB needed

## Setup
```bash
pip install -r requirements.txt
python seed_demo.py   # optional: load ~130 sample transactions (last 6 months)
python app.py
```
Then open http://127.0.0.1:5000

## Docker
```bash
docker compose up --build -d   # app at http://127.0.0.1:5000, data in exptracker-data volume
docker compose down
```
Or with plain docker:
```bash
docker build -t exptracker .
docker run -d -p 5000:5000 -e EXPENSE_DB=/data/expenses.db -v exptracker-data:/data exptracker
```
Set `EXPENSE_DB` to choose where SQLite stores data (defaults to `expenses.db` next to `app.py`).

## Project structure
```
app.py               # Flask app + SQLite logic
expenses.sql         # database schema + default categories (same as app init_db)
templates/           # base, index (dashboard), transactions, edit, categories, reports
static/style.css
requirements.txt
expenses.db          # auto-created on first run (git-ignored)
```

## Database schema
- `categories(id, name UNIQUE, type IN income/expense)`
- `transactions(id, amount, type, category_id FK, date YYYY-MM-DD, note)`
