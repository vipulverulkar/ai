"""Credential verification against the users table (Model layer)."""
from werkzeug.security import check_password_hash, generate_password_hash

from ...config import DEFAULT_PASSWORD, DEFAULT_USERNAME
from ...db import INTEGRITY_ERRORS

# Bounds for the per-user idle-timeout override (minutes).
MIN_TIMEOUT_MINUTES = 1
MAX_TIMEOUT_MINUTES = 1440

# New-user validation.
MIN_USERNAME_LEN = 3
MAX_USERNAME_LEN = 32
MIN_PASSWORD_LEN = 4


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
        return 15
    return default_minutes if default_minutes > 0 else 15


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
    if len(password or "") < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    return None


def all_users(db):
    """All users, oldest first."""
    return db.execute("SELECT * FROM users ORDER BY id").fetchall()


def count_users(db):
    """Number of user accounts."""
    return db.execute("SELECT COUNT(*) FROM users").fetchone()[0]


def create_user(db, username, password):
    """Insert a user with a hashed password. Returns an error message or None."""
    err = validate_new_user(username, password)
    if err:
        return err
    try:
        db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                   (username.strip(), generate_password_hash(password)))
        db.commit()
    except INTEGRITY_ERRORS:
        db.rollback()
        return f"Username '{username.strip()}' already exists."
    return None


def set_password(db, user_id, password):
    """Reset a user's password. Returns an error message or None."""
    if len(password or "") < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    db.execute("UPDATE users SET password_hash=? WHERE id=?",
               (generate_password_hash(password), user_id))
    db.commit()
    return None


def delete_user(db, user_id):
    """Delete a user by id (no commit wrapper needed beyond the delete)."""
    db.execute("DELETE FROM users WHERE id=?", (user_id,))
    db.commit()


def managed_stats(db, user_id):
    """Income/expense/count of transactions managed for one user."""
    row = db.execute(
        """SELECT SUM(CASE WHEN type='income' THEN amount ELSE 0 END) AS income,
                  SUM(CASE WHEN type='expense' THEN amount ELSE 0 END) AS expense,
                  COUNT(*) AS cnt FROM transactions WHERE user_id=?""",
        (user_id,)).fetchone()
    return {"income": row["income"] or 0, "expense": row["expense"] or 0,
            "count": row["cnt"] or 0}


def managed_recent(db, user_id, limit=5):
    """Most recent transactions managed for one user."""
    return db.execute(
        """SELECT t.*, c.name AS category_name
           FROM transactions t JOIN categories c ON t.category_id=c.id
           WHERE t.user_id=? ORDER BY t.date DESC, t.id DESC LIMIT ?""",
        (user_id, limit)).fetchall()


def managed_categories(db, user_id):
    """Per-category expense totals for one user."""
    return db.execute(
        """SELECT c.name, SUM(t.amount) AS total
           FROM transactions t JOIN categories c ON t.category_id=c.id
           WHERE t.user_id=? AND t.type='expense'
           GROUP BY c.id ORDER BY total DESC""",
        (user_id,)).fetchall()
