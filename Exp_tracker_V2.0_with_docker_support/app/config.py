"""Application configuration (env-driven)."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_VERSION = "2.0.0"

# First-boot login account (created in the users table when it's empty).
DEFAULT_USERNAME = "admin"
DEFAULT_PASSWORD = "admin"

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


def _session_timeout_minutes():
    """Idle-session timeout in minutes (env SESSION_TIMEOUT_MINUTES, default 15)."""
    try:
        value = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "15"))
    except (ValueError, TypeError):
        return 15
    return value if value > 0 else 15


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me-in-production")
    # Database backend: "sqlite" (default, zero setup) or "postgres".
    # When DB_TYPE is unset, the backend is auto-detected: Postgres if
    # DATABASE_URL is set, SQLite otherwise.
    DB_TYPE = os.environ.get("DB_TYPE", "").strip().lower() or None
    # Postgres DSN, e.g. postgresql://user:pass@host:5432/exptracker.
    # Used when DB_TYPE=postgres (or auto-detected); ignored for SQLite.
    DATABASE_URL = os.environ.get("DATABASE_URL") or None
    EXPENSE_DB = os.environ.get("EXPENSE_DB", os.path.join(BASE_DIR, "expenses.db"))
    CURRENCY = os.environ.get("CURRENCY_SYMBOL", "₹")
    MAX_CONTENT_LENGTH = 2 * 1024 * 1024  # 2 MB (CSV imports)
    # Auto-logout after this many idle minutes (per-user override in profile).
    SESSION_TIMEOUT_MINUTES = _session_timeout_minutes()
    APP_VERSION = APP_VERSION
