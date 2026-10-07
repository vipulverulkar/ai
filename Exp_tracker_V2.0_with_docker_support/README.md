# Expense Tracker 💰

Track income, expenses, budgets and reports — a lightweight Flask + SQLite/PostgreSQL web app with dark mode and charts.

![Dashboard](screenshots/dashboard.png)

## Features

- **Dashboard** — balance, monthly stats, savings rate, 6-month trend, top spending, recent activity, budget alerts
- **Transactions** — filter by type / category / user / month / search, sort, paginate, edit, duplicate, delete; every entry records who it is managed for
- **Import & export** — transactions CSV export (respects filters) and import; bulk-restore categories, budgets and transactions from CSVs in one go (`/data`)
- **Backup & restore** — download a JSON snapshot of the whole database and restore it later (`/data` → Download backup / Restore from backup; works on SQLite and PostgreSQL)
- **Budgets** — monthly limits per category with progress bars and over-budget alerts
- **User profiles** — every user gets an expense profile: totals, spending by category and recent entries; your Profile page shows the expenses managed for you
- **Reports** — daily and monthly income / expense / savings charts
- **Extras** — login screen with idle auto-logout (15 min default, per-user override on the Profile page), user management (add / password-reset / delete accounts), dark mode, category management, JSON API (`/api/summary`, `/api/transactions`), health check (`/healthz`)

## Quickstart

```bash
pip install -r requirements.txt
python seed_demo.py  # optional demo data (~130 transactions + budgets)
python run.py        # open http://127.0.0.1:5000
```

Sign in with the default credentials **admin / admin** (created in the `users`
table on first boot — change the password there before deploying). Copy
`.env.example` to `.env` to set `SECRET_KEY` (required in production) and
`CURRENCY_SYMBOL`.

```bash
# change the admin password (SQLite):
python3 -c "
from werkzeug.security import generate_password_hash; import sqlite3
db = sqlite3.connect('expenses.db')
db.execute('UPDATE users SET password_hash=? WHERE username=?',
           (generate_password_hash('new-password'), 'admin')); db.commit()"
```

## Screenshots

| Login | Transactions | Reports |
|---|---|---|
| ![Login](screenshots/login.png) | ![Transactions](screenshots/transactions.png) | ![Reports](screenshots/reports.png) |

| Budgets | Data & backup | Restore |
|---|---|---|
| ![Budgets](screenshots/budgets.png) | ![Data](screenshots/data.png) | ![Restore](screenshots/restore.png) |

| Users | User profile |
|---|---|
| ![Users](screenshots/users.png) | ![User profile](screenshots/user-profile.png) |

## Docker

```bash
docker compose up --build -d   # http://127.0.0.1:5000
```

Data persists in the `exptracker-data` named volume across restarts, rebuilds and
`docker compose down` — only `docker compose down -v` deletes it.

```bash
# plain docker run with the same persistence:
docker build -t exptracker .
docker run -d -p 5000:5000 -v exptracker-data:/data --env-file .env exptracker
# backup / restore the volume:
docker run --rm -v exptracker-data:/data -v "$PWD":/backup busybox tar czf /backup/exptracker-backup.tgz /data
docker run --rm -v exptracker-data:/data -v "$PWD":/backup busybox tar xzf /backup/exptracker-backup.tgz -C /
```

## Config

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | dev default | Flask sessions — **always set in production** |
| `SESSION_TIMEOUT_MINUTES` | `15` | Idle minutes before auto-logout — each user can override it on their Profile page |
| `DB_TYPE` | `sqlite` | Database backend: `sqlite` or `postgres` (when unset, auto-detects `postgres` if `DATABASE_URL` is set, else `sqlite`) |
| `DATABASE_URL` | *(unset)* | PostgreSQL DSN, e.g. `postgresql://user:pass@host:5432/exptracker` — required when `DB_TYPE=postgres`, ignored for `sqlite` |
| `EXPENSE_DB` | `expenses.db` | SQLite file path (only used when `DB_TYPE=sqlite`) |
| `CURRENCY_SYMBOL` | `₹` | Currency symbol in UI and CSV |
| `PORT` | `5000` | Dev server port (`python run.py`) |

### Database (SQLite / PostgreSQL)

SQLite is the default — zero setup, data lives in the file at `EXPENSE_DB`.
To use PostgreSQL instead, set both variables (requires `psycopg`, already in
`requirements.txt`):

```bash
DB_TYPE=postgres
DATABASE_URL=postgresql://user:password@localhost:5432/exptracker
```

The schema is created automatically on startup for either backend, and
`seed_demo.py` works with both. The active database is shown on the
**Data** page and in the `/healthz` response (`{"status": "ok", "db": ...}`).
`docker-compose.yml` has a commented-out `db` service you can enable for a
ready-made Postgres container (together with `DB_TYPE=postgres`).

### Backup & restore

The **Data** page offers a JSON backup covering categories, budgets,
transactions and users — it works identically on SQLite and PostgreSQL, and a
backup taken on one backend restores cleanly on the other. Restoring replaces
all current data (a confirmation checkbox guards against accidents), resets id
sequences, and leaves existing data untouched if the file is invalid. For raw
engine-level copies you can additionally back up the SQLite file itself or use
`pg_dump` for Postgres, but the in-app JSON backup is the portable option.

## Tests

```bash
python3 -m pytest -q
```

## Structure

Flask MVC with an app factory (`create_app`) — each module under `app/modules/`
is a self-contained blueprint with its own **models** (`models.py` — data access),
**controllers** (`controllers.py` — routes) and **views** (`templates/`):

```
run.py            entry point (dev server + gunicorn `run:app`)
app/
  __init__.py     app factory, template filters, error handlers, /healthz
   config.py       env-driven config (SECRET_KEY, DB_TYPE, EXPENSE_DB, CURRENCY…)
  db.py           SQLite/PostgreSQL adapter + schema bootstrap
  helpers.py      INR formatting, month/date utilities
  templates/      shared views: base.html, error.html
  static/         style.css (light/dark), app.js (theme toggle, forms)
  modules/
    auth/         login screen + session guard + profile + user admin (credentials in users table)
    dashboard/    home: summaries, 6-month trend, top spending, budget alerts
    transactions/ list/filter/sort/paginate, CRUD, CSV import/export
    categories/   category management
    budgets/      monthly limits + status
    reports/      daily/monthly summaries
    data/         full CSV import (categories + budgets + transactions) + JSON backup/restore
    api/          JSON endpoints (no views)
expenses.sql      schema reference
seed_demo.py      demo data generator
tests/            pytest suite
screenshots/      README screenshots
```

Schema: `categories(id, name, type)` · `transactions(id, amount, type, category_id, date, note, user_id)` · `budgets(id, category_id, monthly_limit)` · `users(id, username, password_hash)`
