"""Database layer — SQLite (default) or PostgreSQL (DB_TYPE=postgres).

All models use `?` placeholders and dict-like rows; the wrapper below
translates for psycopg so the rest of the app stays engine-agnostic.
"""
import os
import re
import sqlite3

from flask import current_app, g
from werkzeug.security import generate_password_hash

from .config import DEFAULT_CATEGORIES, DEFAULT_PASSWORD, DEFAULT_USERNAME

try:
    import psycopg
except ImportError:  # optional — only needed when DATABASE_URL is set
    psycopg = None

# Unified exception tuples for `except` clauses (engine-agnostic).
DB_ERRORS = (sqlite3.Error,) + ((psycopg.Error,) if psycopg else ())
INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + ((psycopg.IntegrityError,) if psycopg else ())

SQLITE_SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('income','expense'))
);
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    session_timeout_minutes INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL CHECK (amount > 0),
    type TEXT NOT NULL CHECK (type IN ('income','expense')),
    category_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    note TEXT DEFAULT '',
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER UNIQUE NOT NULL,
    monthly_limit REAL NOT NULL CHECK (monthly_limit > 0),
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_cat ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id);
"""

PG_SCHEMA = """
CREATE TABLE IF NOT EXISTS categories (
    id SERIAL PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('income','expense'))
);
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    session_timeout_minutes INTEGER,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    amount DOUBLE PRECISION NOT NULL CHECK (amount > 0),
    type TEXT NOT NULL CHECK (type IN ('income','expense')),
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    date TEXT NOT NULL,
    note TEXT DEFAULT '',
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS budgets (
    id SERIAL PRIMARY KEY,
    category_id INTEGER UNIQUE NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    monthly_limit DOUBLE PRECISION NOT NULL CHECK (monthly_limit > 0)
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_cat ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id);
"""


class Row(dict):
    """Dict row that also supports positional access (like sqlite3.Row).

    Note: SELECTs must alias duplicate column names (e.g. two SUMs),
    since dict keys collapse duplicates — same limitation as psycopg's
    dict_row.
    """

    def __getitem__(self, key):
        if isinstance(key, int):
            return tuple(self.values())[key]
        return super().__getitem__(key)


def _pg_row_factory(cursor):
    fields = [col.name for col in cursor.description] if cursor.description else []

    def make_row(values):
        return Row(zip(fields, values))

    return make_row


def to_pg(sql):
    """Translate app SQL (sqlite-style) for psycopg.

    - `?` placeholders -> `%s`
    - `INSERT OR IGNORE INTO ...` -> `INSERT INTO ... ON CONFLICT DO NOTHING`
    """
    sql = sql.replace("?", "%s")
    if sql.lstrip().upper().startswith("INSERT OR IGNORE"):
        sql = re.sub(r"^\s*INSERT\s+OR\s+IGNORE\s+INTO", "INSERT INTO", sql, flags=re.I)
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


class _Cursor:
    __slots__ = ("_cur",)

    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount


class Connection:
    """Engine-agnostic connection wrapper."""

    def __init__(self, raw, engine):
        self._raw = raw
        self.engine = engine  # "sqlite" | "pg"

    def execute(self, sql, params=()):
        if self.engine == "pg":
            sql = to_pg(sql)
        return _Cursor(self._raw.execute(sql, params))

    def executescript(self, sql):
        if self.engine == "pg":
            # psycopg runs multiple statements in one execute (no params).
            self._raw.execute(sql)
        else:
            self._raw.executescript(sql)

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()


def _ensure_db_dir(db_path):
    parent = os.path.dirname(os.path.abspath(db_path))
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)


def resolve_engine(config):
    """Return "sqlite" or "pg" for the given config.

    DB_TYPE selects the backend explicitly ("sqlite" default, "postgres").
    When DB_TYPE is unset, the backend is auto-detected for backward
    compatibility: Postgres if DATABASE_URL is set, SQLite otherwise.
    """
    raw = (config.get("DB_TYPE") or "").strip().lower()
    if raw in ("", "auto"):
        return "pg" if config.get("DATABASE_URL") else "sqlite"
    if raw in ("sqlite", "sqlite3"):
        return "sqlite"
    if raw in ("postgres", "postgresql", "pg"):
        if not config.get("DATABASE_URL"):
            raise RuntimeError(
                "DB_TYPE=postgres but DATABASE_URL is not set. "
                "Set DATABASE_URL, e.g. "
                "postgresql://user:password@localhost:5432/exptracker")
        return "pg"
    raise RuntimeError(
        f"Invalid DB_TYPE={raw!r}. Use 'sqlite' (default) or 'postgres'.")


def connect(config):
    """Open a wrapped connection for the configured engine.

    SQLite by default (file at config["EXPENSE_DB"]); Postgres when
    DB_TYPE=postgres (or DATABASE_URL is set and DB_TYPE is unset).
    """
    engine = resolve_engine(config)
    if engine == "pg":
        if psycopg is None:
            raise RuntimeError(
                "Postgres selected but psycopg is not installed. "
                "Install it with: pip install 'psycopg[binary]'")
        return Connection(psycopg.connect(config.get("DATABASE_URL"),
                                          row_factory=_pg_row_factory), "pg")
    path = config["EXPENSE_DB"]
    _ensure_db_dir(path)
    raw = sqlite3.connect(path)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    return Connection(raw, "sqlite")


def get_db():
    """Request-scoped connection (stored on flask.g)."""
    if "db" not in g:
        g.db = connect(current_app.config)
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def _migrate(conn):
    """Bring existing databases up to the current schema (idempotent).

    - Adds users.session_timeout_minutes (per-user idle-timeout override)
      and transactions.user_id (who the expense is managed for).
    - Removes the retired members table / transactions.member_id: users and
      members are the same entity, so a single user_id owner is enough.
    - The CREATE TABLE / CREATE INDEX statements in init_db are idempotent
      and cover everything else.
    """
    for table, column in (("users", "session_timeout_minutes"),
                          ("transactions", "user_id")):
        try:
            conn.execute(f"SELECT {column} FROM {table} LIMIT 1").fetchone()
            continue
        except DB_ERRORS:
            pass
        try:
            conn.rollback()
        except DB_ERRORS:
            pass
        if conn.engine == "pg":
            conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS "
                         f"{column} INTEGER")
        else:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} INTEGER")
        conn.commit()
    _drop_if_exists(conn, "transactions", "member_id")
    _drop_table_if_exists(conn, "members")


def _drop_if_exists(conn, table, column):
    """Drop a retired column when present (kept data is preserved)."""
    if conn.engine == "sqlite":
        probe = "SELECT name FROM pragma_table_info('" + table + "')"
        name_idx = 0
    else:
        probe = ("SELECT column_name FROM information_schema.columns "
                 "WHERE table_name='" + table + "'")
        name_idx = 0
    try:
        cols = [r[name_idx] for r in conn.execute(probe).fetchall()]
    except DB_ERRORS:
        try:
            conn.rollback()
        except DB_ERRORS:
            pass
        return
    if column not in cols:
        return
    try:
        if conn.engine == "pg":
            conn.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column}")
        else:
            conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.commit()
    except DB_ERRORS:  # old SQLite without DROP COLUMN support: leave it
        try:
            conn.rollback()
        except DB_ERRORS:
            pass


def _drop_table_if_exists(conn, table):
    try:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
        conn.commit()
    except DB_ERRORS:
        try:
            conn.rollback()
        except DB_ERRORS:
            pass


def init_db(config):
    """Create tables/indexes and seed defaults (categories, admin user).

    Idempotent. On first boot a default admin/admin account is created —
    change its password in the users table.
    """
    conn = connect(config)
    conn.executescript(PG_SCHEMA if conn.engine == "pg" else SQLITE_SCHEMA)
    _migrate(conn)
    for name, ctype in DEFAULT_CATEGORIES:
        conn.execute("INSERT OR IGNORE INTO categories (name, type) VALUES (?, ?)",
                     (name, ctype))
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                     (DEFAULT_USERNAME, generate_password_hash(DEFAULT_PASSWORD)))
    conn.commit()
    conn.close()
