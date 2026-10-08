"""Credential verification, roles, 2FA against the users table (Model layer)."""
from werkzeug.security import check_password_hash, generate_password_hash

from ...config import DEFAULT_PASSWORD, DEFAULT_USERNAME
from ...db import DB_ERRORS, INTEGRITY_ERRORS
from ...helpers import from_cents

# Bounds for the per-user idle-timeout override (minutes).
MIN_TIMEOUT_MINUTES = 1
MAX_TIMEOUT_MINUTES = 1440

# New-user validation.
MIN_USERNAME_LEN = 3
MAX_USERNAME_LEN = 32
MIN_PASSWORD_LEN = 8
ROLES = ("admin", "viewer")

try:
    import pyotp
except ImportError:  # optional — 2FA degrades gracefully without it
    pyotp = None


def password_error(password):
    """Return an error message unless the password meets the strength policy."""
    password = password or ""
    if len(password) < MIN_PASSWORD_LEN:
        return (f"Password must be at least {MIN_PASSWORD_LEN} characters "
                "(letters and numbers).")
    if not any(ch.isalpha() for ch in password) or not any(ch.isdigit() for ch in password):
        return "Password must contain both letters and numbers."
    return None


def verify(db, username, password):
    """Check username/password against the hashed credentials in the DB."""
    row = db.execute("SELECT * FROM users WHERE username=?", (username or "",)).fetchone()
    if not row:
        return False
    return check_password_hash(row["password_hash"], password or "")


def using_default_credentials(db):
    """True if the seeded admin account still has the default password."""
    row = db.execute("SELECT password_hash FROM users WHERE username=?",
                     (DEFAULT_USERNAME,)).fetchone()
    return bool(row) and check_password_hash(row["password_hash"], DEFAULT_PASSWORD)


def get_user(db, username):
    """Return the user row for username, or None."""
    return db.execute("SELECT * FROM users WHERE username=?", (username or "",)).fetchone()


def is_admin(db, username):
    """True when username exists and has the admin role."""
    row = get_user(db, username)
    if not row:
        return False
    try:
        return (row["role"] or "admin") == "admin"
    except (KeyError, IndexError):
        return True  # pre-roles database rows are treated as admins


def role_of(db, username):
    row = get_user(db, username)
    if not row:
        return None
    try:
        return row["role"] or "admin"
    except (KeyError, IndexError):
        return "admin"


# ---------- TOTP two-factor auth ----------
def totp_available():
    return pyotp is not None


def totp_enabled(db, username):
    row = get_user(db, username)
    if not row:
        return False
    try:
        return bool(row["totp_enabled"])
    except (KeyError, IndexError):
        return False


def totp_start(db, username):
    """Generate + store a pending TOTP secret. Returns the secret or an error."""
    if pyotp is None:
        return None, "2FA requires the pyotp package (pip install pyotp)."
    secret = pyotp.random_base32()
    db.execute("UPDATE users SET totp_secret=?, totp_enabled=0 WHERE username=?",
               (secret, username))
    db.commit()
    return secret, None


def totp_confirm(db, username, code):
    """Verify a code against the pending secret and activate 2FA."""
    if pyotp is None:
        return "2FA requires the pyotp package."
    row = get_user(db, username)
    if not row or not row["totp_secret"]:
        return "Start 2FA setup first."
    try:
        if not pyotp.TOTP(row["totp_secret"]).verify((code or "").strip(), valid_window=1):
            return "Invalid code — check your authenticator app."
    except (ValueError, TypeError):
        return "Invalid code format."
    db.execute("UPDATE users SET totp_enabled=1 WHERE username=?", (username,))
    db.commit()
    return None


def totp_verify(db, username, code):
    """Verify a login code against the active secret."""
    if pyotp is None:
        return False
    row = get_user(db, username)
    if not row or not row["totp_enabled"] or not row["totp_secret"]:
        return False
    try:
        return pyotp.TOTP(row["totp_secret"]).verify((code or "").strip(), valid_window=1)
    except (ValueError, TypeError):
        return False


def totp_disable(db, username, code):
    """Verify a code, then turn 2FA off. Returns an error message or None."""
    if not totp_verify(db, username, code):
        return "Invalid code — 2FA stays on."
    db.execute("UPDATE users SET totp_enabled=0, totp_secret=NULL WHERE username=?",
               (username,))
    db.commit()
    return None


def effective_timeout(db, username, default_minutes):
    """Idle-timeout minutes for username: personal override or the global default."""
    row = get_user(db, username)
    if row:
        try:
            override = row["session_timeout_minutes"]
        except (KeyError, IndexError, TypeError):
            override = None
        if override:
            try:
                override = int(override)
            except (ValueError, TypeError):
                override = None
            if override and MIN_TIMEOUT_MINUTES <= override <= MAX_TIMEOUT_MINUTES:
                return override
    try:
        default_minutes = int(default_minutes)
    except (ValueError, TypeError):
        return 5
    return default_minutes if default_minutes > 0 else 5


def set_timeout(db, username, raw_value):
    """Set/clear the personal idle-timeout override. Returns an error message or None.

    Blank clears the override (falls back to the global default).
    """
    text = (raw_value or "").strip()
    if not text:
        db.execute("UPDATE users SET session_timeout_minutes=NULL WHERE username=?",
                   (username,))
        db.commit()
        return None
    try:
        minutes = int(text, 10)
    except (ValueError, TypeError):
        return f"Timeout must be a whole number of minutes ({MIN_TIMEOUT_MINUTES}–{MAX_TIMEOUT_MINUTES})."
    if not MIN_TIMEOUT_MINUTES <= minutes <= MAX_TIMEOUT_MINUTES:
        return f"Timeout must be between {MIN_TIMEOUT_MINUTES} and {MAX_TIMEOUT_MINUTES} minutes."
    db.execute("UPDATE users SET session_timeout_minutes=? WHERE username=?",
               (minutes, username))
    db.commit()
    return None


def validate_new_user(username, password):
    """Return an error message for a new username/password, or None if valid."""
    name = (username or "").strip()
    if not MIN_USERNAME_LEN <= len(name) <= MAX_USERNAME_LEN:
        return (f"Username must be {MIN_USERNAME_LEN}–{MAX_USERNAME_LEN} characters.")
    if not all(ch.isalnum() or ch in ("_", "-", ".") for ch in name):
        return "Username may only contain letters, numbers, _ , - and ."
    return password_error(password)


def all_users(db):
    """All users, oldest first."""
    return db.execute("SELECT * FROM users ORDER BY id").fetchall()


def count_users(db):
    """Number of user accounts."""
    return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def count_admins(db):
    """Number of admin accounts (pre-roles rows count as admins)."""
    try:
        return db.execute(
            "SELECT COUNT(*) FROM users WHERE role='admin' OR role IS NULL"
            " OR role=''").fetchone()[0]
    except DB_ERRORS:
        return count_users(db)


def create_user(db, username, password, role="admin"):
    """Insert a user with a hashed password. Returns an error message or None."""
    err = validate_new_user(username, password)
    if err:
        return err
    if role not in ROLES:
        return "Role must be admin or viewer."
    try:
        db.execute("INSERT INTO users (username, password_hash, role) VALUES (?,?,?)",
                   (username.strip(), generate_password_hash(password), role))
        db.commit()
    except INTEGRITY_ERRORS:
        db.rollback()
        return f"Username '{username.strip()}' already exists."
    return None


def set_password(db, user_id, password):
    """Reset a user's password. Returns an error message or None."""
    err = password_error(password)
    if err:
        return err
    db.execute("UPDATE users SET password_hash=? WHERE id=?",
               (generate_password_hash(password), user_id))
    db.commit()
    return None


def set_role(db, user_id, role):
    """Change a user's role. Returns an error message or None."""
    if role not in ROLES:
        return "Role must be admin or viewer."
    row = db.execute("SELECT role FROM users WHERE id=?", (user_id,)).fetchone()
    if row and (row["role"] or "admin") == "admin" and role != "admin" \
            and count_admins(db) <= 1:
        return "Cannot demote the last remaining admin."
    db.execute("UPDATE users SET role=? WHERE id=?", (role, user_id))
    db.commit()
    return None


def delete_user(db, user_id):
    """Delete a user by id. Returns an error message or None (last-admin guard)."""
    row = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if row and (row["role"] or "admin") == "admin" and count_admins(db) <= 1:
        return "Cannot delete the last remaining admin."
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()
    return None


def managed_stats(db, user_id):
    """Income/spending/saved/count of transactions managed for one user (rupees)."""
    row = db.execute(
        """SELECT SUM(CASE WHEN t.type='income' THEN t.amount ELSE 0 END) AS income,
                  SUM(CASE WHEN t.type='expense' AND c.is_savings=0 THEN t.amount ELSE 0 END) AS expense,
                  SUM(CASE WHEN t.type='expense' AND c.is_savings=1 THEN t.amount ELSE 0 END) AS saved,
                  COUNT(*) AS cnt FROM transactions t
           JOIN categories c ON t.category_id=c.id
           WHERE t.user_id=? AND t.deleted_at IS NULL""",
        (user_id,)).fetchone()
    return {"income": from_cents(row["income"]), "expense": from_cents(row["expense"]),
            "saved": from_cents(row["saved"]), "count": row["cnt"] or 0}


def managed_recent(db, user_id, limit=5):
    """Most recent transactions managed for one user (amounts in rupees)."""
    rows = db.execute(
        """SELECT t.*, c.name AS category_name
           FROM transactions t JOIN categories c ON t.category_id=c.id
           WHERE t.user_id=? AND t.deleted_at IS NULL
           ORDER BY t.date DESC, t.id DESC LIMIT ?""",
        (user_id, limit)).fetchall()
    for r in rows:
        r["amount"] = from_cents(r["amount"])
    return rows


def managed_categories(db, user_id):
    """Per-category spending totals for one user (savings buckets excluded)."""
    rows = db.execute(
        """SELECT c.name, SUM(t.amount) AS total
           FROM transactions t JOIN categories c ON t.category_id=c.id
           WHERE t.user_id=? AND t.deleted_at IS NULL AND t.type='expense'
                 AND c.is_savings=0
           GROUP BY c.id ORDER BY total DESC""",
        (user_id,)).fetchall()
    for r in rows:
        r["total"] = from_cents(r["total"])
    return rows
