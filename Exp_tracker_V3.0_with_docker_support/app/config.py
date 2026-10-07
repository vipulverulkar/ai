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


def _currency_rates():
    """Static FX rates to the base currency (1 unit of code -> N units of base).

    Override/extend with CURRENCY_RATES env var (JSON object), e.g.
    CURRENCY_RATES='{"USD": 83.5, "EUR": 90.1}'. The base currency always
    maps to 1.0. Rates are intentionally static (offline-friendly); update
    them via env when needed.
    """
    base = os.environ.get("BASE_CURRENCY", "INR").strip().upper() or "INR"
    rates = {"INR": 1.0, "USD": 83.0, "EUR": 90.0, "GBP": 105.0,
             "AED": 22.6, "SGD": 62.0, "JPY": 0.55}
    raw = os.environ.get("CURRENCY_RATES")
    if raw:
        try:
            import json
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                for k, v in parsed.items():
                    try:
                        rates[str(k).strip().upper()] = float(v)
                    except (ValueError, TypeError):
                        continue
        except ValueError:
            pass
    rates[base] = 1.0
    return base, rates


BASE_CURRENCY, CURRENCY_RATES = _currency_rates()
CURRENCY_CODES = sorted(CURRENCY_RATES)


def _env_bool(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


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
    # Multi-currency: base currency plus static conversion rates.
    BASE_CURRENCY = BASE_CURRENCY
    CURRENCY_RATES = CURRENCY_RATES
    CURRENCY_CODES = CURRENCY_CODES
    # Live FX rates: when enabled, rates refresh daily from open.er-api.com
    # (no API key) with a local cache; offline falls back to static rates.
    FX_AUTO_FETCH = _env_bool("FETCH_FX_RATES")
    FX_CACHE_FILE = os.environ.get(
        "FX_CACHE_FILE", os.path.join(BASE_DIR, "fx_rates.json"))
    # Server-side sessions (filesystem). Disable with SESSION_TYPE=cookie.
    SESSION_TYPE = os.environ.get("SESSION_TYPE", "filesystem")
    SESSION_FILE_DIR = os.environ.get(
        "SESSION_FILE_DIR", os.path.join(BASE_DIR, "flask_sessions"))
    # Rate limiter storage: memory:// (default) or redis://host:6379/0 for
    # multi-worker deployments.
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    # Automatic JSON backups on startup (keep the newest N files).
    AUTO_BACKUP = _env_bool("AUTO_BACKUP")
    BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(BASE_DIR, "backups"))
    BACKUP_KEEP = int(os.environ.get("BACKUP_KEEP", "10") or 10)
    # Audit log retention: entries older than N days are purged on startup
    # (0 keeps everything).
    AUDIT_RETENTION_DAYS = int(os.environ.get("AUDIT_RETENTION_DAYS", "0") or 0)
    # Optional monitoring integrations (guarded imports — app works without them).
    SENTRY_DSN = os.environ.get("SENTRY_DSN") or None
    APP_VERSION = APP_VERSION
