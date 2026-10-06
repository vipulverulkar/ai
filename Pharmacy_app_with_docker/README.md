# Pharmacy Billing App (₹ INR)

Counter-friendly pharmacy billing + inventory app. **React + Vite** frontend, **Python Flask + SQLAlchemy** backend, **SQLite** database (auto-created with sample stock).

![Login](docs/screenshots/login.png)

## Screens

| Billing | Inventory |
|---|---|
| ![Billing](docs/screenshots/billing.png) | ![Inventory](docs/screenshots/inventory.png) |

## Features

- **Billing** — name/salt/batch search (Enter adds first match), quantity steppers capped at stock, per-line rates, bill-level discount %, payment modes (Cash/UPI/Card/Credit/Other), cash-tendered → change calculator, printable GST TAX INVOICE with amount-in-words.
- **Inventory** — add/edit/remove medicines, stock adjustments with audit ledger, low/out-of-stock, expiring/expired and prescription-drug filters, sorting, suppliers + purchase/stock-in entries.
- **Server-side pagination** — `GET /api/medicines` and `GET /api/bills` are paged (`?page=&per_page=&search=`), so catalogs with 100k+ rows stay fast.
- **Masters (admin)** — GST slabs, medicine types, payment modes, store profile (name, address, GSTIN, logo, low-stock threshold).
- **Users & roles** — admin (everything) vs staff (billing + view-only inventory). Token sessions (12 h), hashed passwords.
- **Dashboard & reports** — today's sales, stock value, low/expired alerts, top sellers, sales reports.

## Installation

Requirements: **Python 3.10+**. Node.js 18+ only if you want the Vite dev server (the prebuilt UI in `frontend/dist` is served by Flask, so Node is optional for just running the app).

### Option A — Windows (easiest)

1. Install Python 3.10+ (tick **"Add python.exe to PATH"**) and Node.js LTS (only needed once, to rebuild the UI).
2. Download/clone this folder.
3. Double-click **`start.bat`** — installs deps, builds the page on first run, opens the app in your browser.
4. Log in with `admin` / `admin`.

If port 5000 is busy: run `start.bat 5001` from a terminal instead.

### Option B — Linux / macOS

```bash
# 1. Backend (serves API + prebuilt UI)
cd backend
pip install -r requirements.txt
python app.py
# App → http://127.0.0.1:5000/   API → http://127.0.0.1:5000/api/health
```

If port 5000 is busy: `PORT=5001 python app.py`.

```bash
# 2. Frontend dev server (optional — hot reload while developing UI)
cd frontend
npm install
npm run dev
# UI → http://127.0.0.1:5173 (proxies /api to Flask)
```

Production UI rebuild after frontend changes:

```bash
cd frontend && npm run build   # Flask serves frontend/dist automatically
```

### Option C — Docker (recommended for deployment)

Needs only Docker — the image builds the UI and runs the production server (waitress).

```bash
docker compose up -d --build
# App → http://localhost:5000/   (login: admin / admin)
```

If host port 5000 is busy: `HOST_PORT=5001 docker compose up -d --build`.

- Data persists in named volumes: `pharmacy-data` (SQLite DB) and `pharmacy-uploads` (store logos). The DB is seeded + migrated automatically on first boot.
- Useful commands:
  ```bash
  docker compose ps                  # status (waits for "healthy")
  docker compose logs -f pharmacy    # server logs
  docker compose down                # stop (keeps data)
  docker compose down -v             # stop AND delete all data
  ```
- Back up the database:
  ```bash
  docker run --rm -v pharmacy-data:/data -v "$PWD:/backup" alpine cp /data/pharmacy.db /backup/
  ```
- Custom admin on first run: add `ADMIN_USER` / `ADMIN_PASS` under `environment:` in `docker-compose.yml`.
- Plain `docker run` equivalent is documented at the top of the `Dockerfile`.

### Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `5000` | Backend port |
| `ADMIN_USER` / `ADMIN_PASS` | `admin` / `admin` | Seeded admin login (first run) |
| `SESSION_HOURS` | `12` | Login token lifetime |
| `DATABASE_URL` | `backend/pharmacy.db` | SQLite file, or e.g. `postgresql+psycopg2://user:pass@localhost/pharmacy` |

Change the admin password after first login via the **Users/Account** tab.

## Data & backups

- All data lives in **`backend/pharmacy.db`** — copy that file to back up. Versioned migrations in `backend/migrations.py` upgrade old DB files automatically on startup.
- Bulk catalogue import: place a CSV at `backend/uploads/medicine_data.csv` (`product_name, salt_composition, product_price, product_manufactured, medicine_desc, side_effects, …`) and import it into `medicines` with sensible defaults (quantity, GST slab, unit inference).
- Uploaded store logos live in `backend/uploads/`.

## API

All `/api/medicines` and `/api/bills` endpoints require login (`Authorization: Bearer <token>`); writes require admin unless noted.

**Medicines**

- `GET /api/medicines?search=&unit=&stock=&sort=&page=1&per_page=20` → `{medicines, total, page, per_page, total_pages}` (omit `page` for legacy plain array). `stock`: `all|low|out|expiring|expired|rx`. `sort`: `name|stock|expiry|value`.
- `POST /api/medicines` — `{name, composition, unit, batch_no, expiry_date, quantity, price, gst_percent, description, usage, mrp, supplier, rack, schedule, rx_required, min_stock}` (admin)
- `PUT /api/medicines/:id`, `DELETE /api/medicines/:id` (admin)
- `POST /api/medicines/:id/adjust` — `{delta, reason}` stock correction (admin)

**Billing**

- `POST /api/bills` — `{customer_name, customer_phone, doctor_name, prescription_no, discount_percent, payment_mode, items:[{medicine_id, qty}]}` (stock decremented, GST applied)
- `GET /api/bills?page=1&per_page=10&search=&status=&from=&to=` → `{bills, total, page, per_page, total_pages}`
- `GET /api/bills/:id`, `POST /api/bills/:id/return`

**Masters, users, misc**

- `GET/POST/PUT/DELETE /api/gst-rates`, `/api/unit-types`, `/api/payment-modes` (admin writes)
- `GET /api/settings` (public), `PUT /api/settings`, `POST/DELETE /api/settings/logo` (admin)
- `GET/POST/DELETE /api/users` (admin), `POST /api/change-password`
- `GET /api/dashboard`, `GET /api/reports/sales?days=14`, `GET /api/suppliers`, `POST /api/purchases`, `GET /api/stock-movements`, `GET /api/customers`

Billing model: `quantity` = tablets/units in stock, `price` = per-tablet price in ₹, `unit` = tablet/capsule/sachet/strip/bottle/syrup/injection/tube.

## Project structure

```
backend/
  app.py            # Flask REST API + serves frontend/dist
  models.py         # SQLAlchemy models (medicines, bills, users, masters…)
  migrations.py     # versioned, idempotent schema migrations
  requirements.txt
  pharmacy.db       # SQLite data (auto-created)
  uploads/          # logos + import CSVs
frontend/
  src/              # React UI (App.jsx, api.js)
  dist/             # production build served by Flask
Dockerfile          # multi-stage image (Node build → Python + waitress)
docker-compose.yml  # one-command run with persistent volumes
start.bat           # Windows launcher
```
