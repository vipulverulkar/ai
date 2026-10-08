# Expense Tracker 💰

Track income, expenses, budgets and reports — a Flask + SQLite/PostgreSQL web
app with dark mode, charts, multi-currency, recurring transactions and roles.

![Dashboard](screenshots/dashboard.png)

## Features

**Money management**
- **Dashboard** — balance, monthly stats, savings rate, 6-month trend, top spending, recent activity, budget alerts
- **Savings buckets** — flag any expense category as 🏦 savings (a `Savings` bucket is seeded); parked money is excluded from spending totals and the savings rate, and shown as Saved instead — across the dashboard, reports, API and CSV totals. Savings buckets can't carry budgets
- **Transactions** — filter (type / category / user / month dropdown / full-text note search), sort, paginate, edit, duplicate; guided bulk actions (delete to Trash with confirm, or re-categorize) via row checkboxes; every entry records who it is managed for
- **Recurring** — daily / weekly / monthly / yearly schedules with a start date and optional end date (rent, salary, subscriptions); due items are generated automatically on dashboard load, finished schedules show as ended
- **Multi-currency** — log amounts in USD, EUR, GBP and more; stored converted to the base currency with the original amount kept; optional daily FX refresh
- **Split transactions** — one expense spread over up to 3 extra categories, linked as a group so reports stay accurate
- **Budgets** — monthly limits per category with progress bars and over-budget alerts
- **Reports** — daily and monthly charts, budget-vs-actual variance, 3-month cash-flow forecast, PDF export
- **Trash** — deleted transactions are kept (soft delete) with restore / permanent purge

**Data**
- **Import & export** — CSV export (respects filters, includes currency) and import (additive — never deletes)
- **Backup & restore** — SQL-dump backup of the whole database; restore from `.sql`, legacy `.json`, or CSV files (validated first — invalid files change nothing); optional automatic startup backups with rotation

**Accounts & security**
- **Roles** — admin (full access) and viewer (read-only); every write route is server-enforced
- **Two-factor auth** — TOTP via any authenticator app, enforced as a second login step
- **User management** — add accounts, reset passwords, change roles (passwords: min 8 chars, letters + digits)
- **Audit log** — deletes, password resets, imports and role changes are recorded; retention purging
- **Sessions** — idle auto-logout after 5 min (per-user override, `SESSION_TIMEOUT_MINUTES` for the default) with a live nav countdown that resets on activity, warns at 1 min and signs out automatically; server-side sessions (CacheLib filesystem backend), login rate limiting, CSRF protection on all forms
- **Ops** — health check (`/healthz`), Prometheus metrics (`/metrics`), JSON API (`/api/v1/*`, legacy `/api/*`), optional Sentry

## Quickstart

```bash
pip install -r requirements.txt
python seed_demo.py  # optional demo data (~130 transactions + budgets)
python run.py        # open http://127.0.0.1:5000
```

Sign in with the default credentials **admin / admin** (seeded on first boot —
change it before deploying). Copy `.env.example` to `.env` to set `SECRET_KEY`
(required in production) and other options.

```bash
# change the admin password (SQLite) — passwords need 8+ chars, letters + digits:
python3 -c "
from werkzeug.security import generate_password_hash; import sqlite3
db = sqlite3.connect('expenses.db')
db.execute('UPDATE users SET password_hash=? WHERE username=?',
           (generate_password_hash('new-passw0rd'), 'admin')); db.commit()"
```

Amounts are stored as **integer cents** in the database — no floating-point
rounding errors — and converted for display (Indian-style number formatting,
configurable symbol).

## Screenshots

Captured with `seed_demo.py` demo data — login, day-to-day pages, users and the numbered backup/restore flow:

| Login | Transactions | Reports |
|---|---|---|
| ![Login](screenshots/login.png) | ![Transactions](screenshots/transactions.png) | ![Reports](screenshots/reports.png) |

| Budgets | Data & backup | Restore |
|---|---|---|
| ![Budgets](screenshots/budgets.png) | ![Data](screenshots/data.png) | ![Restore](screenshots/restore.png) |

| Users | User profile |
|---|---|
| ![Users](screenshots/users.png) | ![User profile](screenshots/user-profile.png) |

| Categories | Recurring | Trash |
|---|---|---|
| ![Categories](screenshots/categories.png) | ![Recurring](screenshots/recurring.png) | ![Trash](screenshots/trash.png) |

| Profile | Audit |
|---|---|
| ![Profile](screenshots/profile.png) | ![Audit](screenshots/audit.png) |

## Docker

```bash
docker compose up --build -d   # http://127.0.0.1:5000
```

Data persists in the `exptracker-data` named volume across restarts, rebuilds
and `docker compose down` — only `docker compose down -v` deletes it. The
image is a multi-stage build running as a non-root user.

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
| `DB_TYPE` | `sqlite` | `sqlite` or `postgres` (unset: auto-detects postgres if `DATABASE_URL` is set) |
| `DATABASE_URL` | *(unset)* | PostgreSQL DSN — required when `DB_TYPE=postgres` |
| `EXPENSE_DB` | `expenses.db` | SQLite file path |
| `SESSION_TIMEOUT_MINUTES` | `5` | Idle minutes before auto-logout (per-user override on Profile) |
| `SESSION_TYPE` | `filesystem` | Server-side sessions; `cookie` reverts to client-side cookies |
| `CURRENCY_SYMBOL` | `₹` | Display symbol in UI and CSV |
| `BASE_CURRENCY` | `INR` | Base currency code; amounts are stored converted to it |
| `CURRENCY_RATES` | built-in | Static FX rates as JSON, e.g. `{"USD": 83.5, "EUR": 90.1}` |
| `FETCH_FX_RATES` | off | `1` = refresh FX rates daily from open.er-api.com |
| `FX_CACHE_FILE` | `fx_rates.json` | Cache file for fetched FX rates |
| `AUTO_BACKUP` | off | `1` = write a SQL-dump backup to `BACKUP_DIR` on every startup |
| `BACKUP_DIR` / `BACKUP_KEEP` | `backups/` / `10` | Auto-backup location and rotation count |
| `AUDIT_RETENTION_DAYS` | `0` (keep all) | Purge audit entries older than N days on startup |
| `RATELIMIT_STORAGE_URI` | `memory://` | Rate-limit store; use `redis://…` for multi-worker deployments |
| `SENTRY_DSN` | *(unset)* | Enables Sentry error tracking when set |
| `PORT` | `5000` | Dev server port (`python run.py`) |

### Database (SQLite / PostgreSQL)

SQLite is the default — zero setup, data lives in the file at `EXPENSE_DB`.
For PostgreSQL, set both variables (`psycopg` is already in
`requirements.txt`):

```bash
DB_TYPE=postgres
DATABASE_URL=postgresql://user:password@localhost:5432/exptracker
```

The schema is created (and older databases migrated) automatically on startup
for either backend; `seed_demo.py` works with both. The active database is
shown on the **Data** page and in `/healthz`. `docker-compose.yml` ships a
commented-out `db` service you can enable for a ready-made Postgres container.

Full-text note search uses SQLite FTS5 (trigger-maintained index) or, on
PostgreSQL, a generated `tsvector` column with a GIN index — with a plain
`LIKE` fallback if neither is available.

### Backup & restore

The **Data** page is split into numbered sections so backup and restore can't
be mixed up:

1. **Backup (download, safe)** — SQL dump covering categories, budgets,
   transactions, users and recurring transactions. It works identically on both backends,
   and a backup taken on one restores cleanly on the other. A legacy `.json`
   download is also available.
2. **Restore from backup file (destructive)** — upload a `.sql` dump (or a
   legacy `.json` snapshot) to replace all current data. Guarded by a
   confirmation checkbox, validated before anything is wiped, id sequences
   reset — and existing data is left untouched if the file is invalid.
3. **CSV files — one picker, two modes** — upload the same three CSVs and
   choose **Add** (appends rows, never deletes) or **Replace** (wipes and
   re-imports the data tables behind a confirmation checkbox). Users are
   always preserved (CSV has no user format); recurring schedules are
   removed. Use a `.sql` backup for a full-fidelity restore.

No upload size limit is enforced. For raw engine-level copies you can
additionally copy the SQLite file or use `pg_dump`.

## Tests

```bash
python3 -m pytest -q
```

## Structure

Flask MVC with an app factory (`create_app`) — each module under `app/modules/`
is a self-contained blueprint with its own **models** (`models.py` — data
access), **controllers** (`controllers.py` — routes) and **views**
(`templates/`):

```
run.py            entry point (dev server + gunicorn `run:app`)
app/
  __init__.py     app factory, CSRF/rate limiting, security headers, /healthz, /metrics
  config.py       env-driven configuration
  db.py           SQLite/PostgreSQL adapter, schema bootstrap + migrations, FTS setup
  helpers.py      INR formatting, cents conversion, month/date utilities
  fx.py           optional live FX-rate refresh (cached)
  jobs.py         automatic backup + rotation
  templates/      shared views: base.html, error.html
  static/         style.css (light/dark), app.js (theme, validation, bulk select)
  modules/
    auth/         login (+ TOTP step), roles, profile, user admin, audit log
    dashboard/    home: summaries, 6-month trend, top spending, budget alerts
    transactions/ list/filter/sort/paginate, CRUD, splits, bulk ops, trash, CSV import/export
    recurring/    scheduled transactions (daily/weekly/monthly/yearly)
    categories/   category management
    budgets/      monthly limits + status
    reports/      daily/monthly charts, budget variance, forecast, PDF export
    data/         bulk CSV import, CSV restore, SQL-dump (+ legacy JSON) backup/restore
    api/          JSON endpoints (/api + /api/v1, no views)
expenses.sql      schema reference
seed_demo.py      demo data generator
tests/            pytest suite
screenshots/      README screenshots
```

Schema: `categories(id, name, type)` · `transactions(id, amount*, type,
category_id, date, note, currency, orig_amount, split_group, user_id,
deleted_at)` · `budgets(id, category_id, monthly_limit*)` ·
`recurring_transactions(id, amount*, frequency, next_run_date, active, …)` ·
`users(id, username, password_hash, role, totp_*, session_timeout_minutes)` ·
`audit_logs(id, user_id, action, target_*, details)` — `*` = integer cents in
the base currency.
