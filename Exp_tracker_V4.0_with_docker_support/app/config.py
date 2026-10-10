"""Application configuration (env-driven)."""
import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

APP_VERSION = "2.0.0"

# First-boot login account (created in the users table when it's empty).
# Env-overridable; only applies before the first user exists.
DEFAULT_USERNAME = os.environ.get("DEFAULT_USERNAME", "admin") or "admin"
DEFAULT_PASSWORD = os.environ.get("DEFAULT_PASSWORD", "admin") or "admin"

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
    ("Savings", "expense"),
]

# Default categories flagged as savings buckets (excluded from spending
# totals, shown as Saved instead). Matched by exact name.
SAVINGS_CATEGORIES = {"Savings"}


def _session_timeout_minutes():
    """Idle-session timeout in minutes (env SESSION_TIMEOUT_MINUTES, default 5)."""
    try:
        value = int(os.environ.get("SESSION_TIMEOUT_MINUTES", "5"))
    except (ValueError, TypeError):
        return 5
    return value if value > 0 else 5


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

# Site-wide idle-session timeout in minutes (per-user DB overrides win).
SESSION_TIMEOUT_MINUTES = _session_timeout_minutes()


def _env_bool(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _env_int(name, default):
    """Integer env var with a safe fallback (garbage -> default)."""
    try:
        return int(os.environ.get(name, str(default)) or default)
    except (ValueError, TypeError):
        return default


def _env_csv_set(name, default):
    """Comma-separated env var -> tuple of lowercased tokens (empty -> default)."""
    raw = os.environ.get(name)
    if raw in (None, ""):
        return default
    values = tuple(v.strip().lower() for v in raw.split(",") if v.strip())
    return values or default


# --- Operational tunables (single source of truth; every module imports
# these instead of hardcoding literals — override via env, restart to apply).
# Request rate limiting (Flask-Limiter format, e.g. "200 per minute").
RATELIMIT_DEFAULT = os.environ.get("RATELIMIT_DEFAULT", "200 per minute") or "200 per minute"
# Server-side session cache size (entries; file mode 0o600 stays fixed).
SESSION_CACHE_THRESHOLD = _env_int("SESSION_CACHE_THRESHOLD", 500)
# How long the password-validated 2FA half-session lasts (seconds).
TOTP_PENDING_TTL_SECONDS = _env_int("TOTP_PENDING_TTL_SECONDS", 10 * 60)
# User/account validation policy.
MIN_TIMEOUT_MINUTES = _env_int("MIN_TIMEOUT_MINUTES", 1)
MAX_TIMEOUT_MINUTES = _env_int("MAX_TIMEOUT_MINUTES", 1440)
MIN_USERNAME_LEN = _env_int("MIN_USERNAME_LEN", 3)
MAX_USERNAME_LEN = _env_int("MAX_USERNAME_LEN", 32)
MIN_PASSWORD_LEN = _env_int("MIN_PASSWORD_LEN", 8)
# CSV/bank import guards (DoS protection for uploads).
CSV_IMPORT_ROW_LIMIT = _env_int("CSV_IMPORT_ROW_LIMIT", 2000)
BANK_IMPORT_MAX_BYTES = _env_int("BANK_IMPORT_MAX_BYTES", 2 * 1024 * 1024)
BANK_IMPORT_ROW_LIMIT = _env_int("BANK_IMPORT_ROW_LIMIT", 2000)
BANK_IMPORT_PREVIEW_ROWS = _env_int("BANK_IMPORT_PREVIEW_ROWS", 8)
# Receipt attachments.
RECEIPT_MAX_BYTES = _env_int("RECEIPT_MAX_BYTES", 5 * 1024 * 1024)
RECEIPT_ALLOWED_EXTS = _env_csv_set(
    "RECEIPT_ALLOWED_EXTS", ("png", "jpg", "jpeg", "gif", "pdf", "webp"))
# Recurring schedule engine safety cap (iterations per run).
RECURRING_MAX_CATCHUP = _env_int("RECURRING_MAX_CATCHUP", 366)
# Pagination.
PER_PAGE_DEFAULT = _env_int("PER_PAGE_DEFAULT", 25)
try:
    PER_PAGE_CHOICES = tuple(sorted(
        {int(v) for v in _env_csv_set("PER_PAGE_CHOICES", ("10", "25", "50", "100"))}))
except (ValueError, TypeError):
    PER_PAGE_CHOICES = ()
PER_PAGE_CHOICES = PER_PAGE_CHOICES or (10, 25, 50, 100)
if PER_PAGE_DEFAULT not in PER_PAGE_CHOICES:
    PER_PAGE_DEFAULT = sorted(PER_PAGE_CHOICES)[0]
# The transactions list shows fewer rows per page than other lists.
TRANSACTIONS_PER_PAGE_DEFAULT = _env_int("TRANSACTIONS_PER_PAGE_DEFAULT", 10)
# Live FX refresh (open.er-api.com, no API key).
FX_CACHE_TTL_SECONDS = _env_int("FX_CACHE_TTL_SECONDS", 86400)
FX_API_URL = (os.environ.get("FX_API_URL")
              or "https://open.er-api.com/v6/latest/{base}")
FX_FETCH_TIMEOUT_SECONDS = _env_int("FX_FETCH_TIMEOUT_SECONDS", 5)


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
    MAX_CONTENT_LENGTH = None  # no request size cap (self-hosted; backups/CSVs can be large)
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
    # Session cookie hardening: HttpOnly always; SameSite=Lax blocks
    # cross-site GETs (logout/ping links) from riding the session;
    # Secure follows env (enable behind HTTPS).
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = os.environ.get("SESSION_COOKIE_SAMESITE", "Lax")
    SESSION_COOKIE_SECURE = _env_bool("SESSION_COOKIE_SECURE")
    # Rate limiter storage: memory:// (default) or redis://host:6379/0 for
    # multi-worker deployments.
    RATELIMIT_STORAGE_URI = os.environ.get("RATELIMIT_STORAGE_URI", "memory://")
    RATELIMIT_DEFAULT = RATELIMIT_DEFAULT
    SESSION_CACHE_THRESHOLD = SESSION_CACHE_THRESHOLD
    # Two-factor half-session lifetime (seconds).
    TOTP_PENDING_TTL_SECONDS = TOTP_PENDING_TTL_SECONDS
    # User/account validation policy bounds.
    MIN_TIMEOUT_MINUTES = MIN_TIMEOUT_MINUTES
    MAX_TIMEOUT_MINUTES = MAX_TIMEOUT_MINUTES
    MIN_USERNAME_LEN = MIN_USERNAME_LEN
    MAX_USERNAME_LEN = MAX_USERNAME_LEN
    MIN_PASSWORD_LEN = MIN_PASSWORD_LEN
    # Upload/import guards.
    CSV_IMPORT_ROW_LIMIT = CSV_IMPORT_ROW_LIMIT
    BANK_IMPORT_MAX_BYTES = BANK_IMPORT_MAX_BYTES
    BANK_IMPORT_ROW_LIMIT = BANK_IMPORT_ROW_LIMIT
    BANK_IMPORT_PREVIEW_ROWS = BANK_IMPORT_PREVIEW_ROWS
    RECEIPT_MAX_BYTES = RECEIPT_MAX_BYTES
    RECEIPT_ALLOWED_EXTS = RECEIPT_ALLOWED_EXTS
    RECURRING_MAX_CATCHUP = RECURRING_MAX_CATCHUP
    PER_PAGE_DEFAULT = PER_PAGE_DEFAULT
    PER_PAGE_CHOICES = PER_PAGE_CHOICES
    TRANSACTIONS_PER_PAGE_DEFAULT = TRANSACTIONS_PER_PAGE_DEFAULT
    # Live FX refresh tuning.
    FX_CACHE_TTL_SECONDS = FX_CACHE_TTL_SECONDS
    FX_API_URL = FX_API_URL
    FX_FETCH_TIMEOUT_SECONDS = FX_FETCH_TIMEOUT_SECONDS
    # Automatic SQL-dump backups on startup (keep the newest N files).
    AUTO_BACKUP = _env_bool("AUTO_BACKUP")
    BACKUP_DIR = os.environ.get("BACKUP_DIR", os.path.join(BASE_DIR, "backups"))
    BACKUP_KEEP = _env_int("BACKUP_KEEP", 10)
    # Audit log retention: entries older than N days are purged on startup
    # (0 keeps everything).
    AUDIT_RETENTION_DAYS = _env_int("AUDIT_RETENTION_DAYS", 0)
    # Optional monitoring integrations (guarded imports — app works without them).
    SENTRY_DSN = os.environ.get("SENTRY_DSN") or None
    APP_VERSION = APP_VERSION
