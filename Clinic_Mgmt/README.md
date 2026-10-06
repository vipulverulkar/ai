# Multi-Speciality Clinic Management System

A full-stack clinic management application with:
- **Frontend**: Node.js/Express with EJS templates
- **Backend**: Flask (Python) REST API
- **Database**: SQLite

## Features

- **Patient Management**: Add, edit, delete, and view patients with medical history
- **Doctor Management**: Manage doctors with specializations, experience, and consultation fees
- **Treatment Management**: Define treatments with categories, duration, and cost
- **Appointment Booking**: Schedule appointments linking patients, doctors, and treatments
- **Dashboard**: Overview with statistics and recent activity

## Project Structure

```
Clinic_Mgmt/
├── backend/                 # Flask REST API (MVC)
│   ├── app.py              # Thin entry point (create_app + run)
│   ├── app/
│   │   ├── __init__.py     # App factory, blueprint registration
│   │   ├── config.py       # DB path, admin seed config
│   │   ├── seed.py         # Default lookups, roles, admin user
│   │   ├── models/         # Model layer (patient, doctor,
│   │   │                   # treatment, appointment, user, lookup)
│   │   └── routes/         # Controller layer (one blueprint
│   │                       # per resource: patients, doctors,
│   │                       # treatments, appointments, auth,
│   │                       # users, lookups, system)
│   ├── requirements.txt    # Python dependencies
│   ├── venv/               # Virtual environment (created on setup)
│   └── clinic.db           # SQLite database (created on first run)
├── frontend/               # Node.js/Express Frontend
│   ├── server.js           # Express server
│   ├── package.json        # Node.js dependencies
│   ├── public/             # Static assets
│   │   ├── css/style.css
│   │   └── js/main.js
│   └── views/              # EJS templates
│       ├── layout.ejs
│       ├── dashboard.ejs
│       ├── patients.ejs
│       ├── patient_form.ejs
│       ├── doctors.ejs
│       ├── doctor_form.ejs
│       ├── treatments.ejs
│       ├── treatment_form.ejs
│       ├── appointments.ejs
│       └── appointment_form.ejs
└── start.sh                # Startup script
```

## Prerequisites

- Python 3.8+
- Node.js 18+ (for frontend)

No Docker needed. The launchers below install these automatically when
they are missing (Windows via `winget`, Linux via `apt`/`dnf`/`pacman`
with `sudo`) - internet access is required on first run only.

## Standalone Quick Start (Windows / Linux, no Docker)

**Windows:** double-click `start-windows.bat`. It checks for Python 3.8+
and Node.js 18+ (installing them via `winget` if absent), creates
`backend\venv`, installs all dependencies, starts the backend
(`http://localhost:5001`) and frontend (`http://localhost:3000`) in
their own windows, and opens the app in your browser. Stop everything
with `stop-windows.bat` (or just close the two windows).

**Linux:** run `./start.sh` (same flow as Windows, in one terminal;
stop with `Ctrl+C`).

On first run the backend database is created and seeded automatically.
Default login is `admin` / `admin123` (override the seeded admin with
the `ADMIN_USERNAME` / `ADMIN_PASSWORD` env vars before the first run).

## Installation & Running

Development: `./start.sh` (Flask reloader + dev sessions).

### Production

```bash
API_KEY="$(openssl rand -hex 32)" \
SESSION_SECRET="$(openssl rand -hex 32)" \
ADMIN_USERNAME=admin ADMIN_PASSWORD='<strong-secret>' \
./start-prod.sh
```

Production uses gunicorn (2 workers, no debugger), `NODE_ENV=production`,
env-driven `CORS_ORIGINS`, persistent SQLite sessions, `httpOnly` /
`SameSite=Lax` cookies (`secure` when `NODE_ENV=production`), per-session
CSRF tokens on all forms, 8-character minimum passwords, DB-backed login
rate limiting, and referential guards on master-data deletion.

### Option 1: Run Backend Only (API)

```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
PORT=5001 python app.py
```

The API will be available at `http://localhost:5001/api`

### Option 2: Run Both Frontend & Backend

```bash
# Terminal 1 - Backend
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
PORT=5001 python app.py

# Terminal 2 - Frontend
cd frontend
npm install
npm start
```

The frontend will be available at `http://localhost:3000`

### Option 3: Using Start Script (Linux/Mac)

```bash
chmod +x start.sh
./start.sh
```

## Login

The frontend requires login. A default admin user is seeded on first run
(override with `ADMIN_USERNAME` / `ADMIN_PASSWORD` env vars):

- Username: `admin`
- Password: `admin123`

## Commercial Features

- **Billing & invoices**: generate bills from appointments (prices snapshotted,
  tax from Settings), record part/full payments, printable invoice page
- **API security**: all `/api` routes require the `X-API-Key` header
  (`API_KEY` env var, `dev-key` by default); login rate-limited to
  5 failed attempts per IP per 5 minutes
- **Audit trail**: every create/update/delete plus logins are recorded with
  the acting user (`/audit` page, admin only)
- **Reports**: revenue and appointment analytics with date filters and CSV
  export (`/reports` page, admin only)
- **Clinic settings**: DB-driven profile, tax percent and invoice prefix
  used across the app (`/settings` page, admin only)

Additional users can be created via `POST /api/auth/register`.

## Access Control

- **Admin**: full access, including master data (Treatments, Masters lookups) and User management
- **Staff**: Patients, Doctors, Appointments (including booking, which uses the treatment catalog read-only)

## API Endpoints

### Auth
- `POST /api/auth/register` - Create user (username, password, role)
- `POST /api/auth/login` - Login, returns user on success (401 on failure)

### Users
- `GET /api/users` - List users (no password hashes)
- `GET /api/users/:id` - Get user
- `PUT /api/users/:id` - Update username, role, password (last-admin protected)
- `DELETE /api/users/:id` - Delete user (last-admin protected)

### Billing
- `GET /api/bills` - List bills (optional `?status=`)
- `POST /api/bills` - Generate bill from appointment (snapshots prices + tax)
- `GET /api/bills/:id` - Bill with payment history
- `POST /api/bills/:id/payments` - Record payment (rejects overpayment)

### Settings / Audit / Reports
- `GET /api/settings`, `PUT /api/settings` - Clinic profile, tax, invoice prefix
- `GET /api/audit` - Audit trail (optional `?entity=&action=&limit=`)
- `GET /api/reports/revenue`, `/appointments`, `/summary` (+ `.csv` exports)

### Clinical
- `PUT /api/appointments/:id` - Now also saves vitals, diagnosis, follow-up date
- `GET/POST /api/appointments/:id/prescriptions` - Prescription items
- `PUT/DELETE /api/prescriptions/:id` - Edit/remove prescribed medicine

### Operations
- `GET /api/expenses`, `POST /api/expenses`, `DELETE /api/expenses/:id`
- `GET /api/search?q=` - Global search across patients, doctors, treatments, bills
- `GET /api/backup` / `POST /api/restore` - SQLite snapshot download/upload (admin)
- `GET /api/sessions` / `DELETE /api/sessions/:sid` - Active login sessions (admin)
- `PUT /api/users/:id/password` - Change password (self or admin)
- `POST /api/bills/:id/discount`, `/api/bills/:id/void` - Discount and void (admin)

### Patients
- `GET /api/patients` - List all patients
- `GET /api/patients/:id` - Get patient by ID
- `POST /api/patients` - Create patient
- `PUT /api/patients/:id` - Update patient
- `DELETE /api/patients/:id` - Delete patient

### Doctors
- `GET /api/doctors` - List all doctors
- `GET /api/doctors/:id` - Get doctor by ID
- `POST /api/doctors` - Create doctor
- `PUT /api/doctors/:id` - Update doctor
- `DELETE /api/doctors/:id` - Delete doctor

### Treatments
- `GET /api/treatments` - List all treatments
- `GET /api/treatments/:id` - Get treatment by ID
- `POST /api/treatments` - Create treatment
- `PUT /api/treatments/:id` - Update treatment
- `DELETE /api/treatments/:id` - Delete treatment

### Appointments
- `GET /api/appointments` - List all appointments
- `GET /api/appointments/:id` - Get appointment by ID
- `POST /api/appointments` - Create appointment
- `PUT /api/appointments/:id` - Update appointment
- `DELETE /api/appointments/:id` - Delete appointment

## Database Schema

### Patients
- id (PK), name, phone, email, address, dob, gender, blood_group, medical_history, created_at

### Doctors
- id (PK), name, specialization, phone, email, experience_years, consultation_fee, qualification, bio, created_at

### Treatments
- id (PK), name, category, description, duration_minutes, cost, created_at

### Appointments
- id (PK), patient_id (FK), doctor_id (FK), treatment_id (FK), appointment_date, status, notes, created_at

## Screenshots

The application includes:
- Dashboard with statistics cards
- Patient list with search and CRUD operations
- Doctor management with specialization dropdown
- Treatment catalog with categories
- Appointment scheduling with patient/doctor/treatment selection

## License

MIT