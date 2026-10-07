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
    role TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin','viewer')),
    totp_secret TEXT,
    totp_enabled INTEGER NOT NULL DEFAULT 0 CHECK (totp_enabled IN (0,1)),
    session_timeout_minutes INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount INTEGER NOT NULL CHECK (amount > 0),
    type TEXT NOT NULL CHECK (type IN ('income','expense')),
    category_id INTEGER NOT NULL,
    date TEXT NOT NULL CHECK (date = strftime('%Y-%m-%d', date)),
    note TEXT DEFAULT '',
    currency TEXT DEFAULT 'INR',
    orig_amount INTEGER,
    split_group TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    deleted_at TEXT,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id INTEGER UNIQUE NOT NULL,
    monthly_limit INTEGER NOT NULL CHECK (monthly_limit > 0),
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS recurrences (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    amount INTEGER NOT NULL CHECK (amount > 0),
    type TEXT NOT NULL CHECK (type IN ('income','expense')),
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    note TEXT DEFAULT '',
    currency TEXT DEFAULT 'INR',
    orig_amount INTEGER,
    frequency TEXT NOT NULL CHECK (frequency IN ('daily','weekly','monthly','yearly')),
    next_run_date TEXT NOT NULL CHECK (next_run_date = strftime('%Y-%m-%d', next_run_date)),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    last_run_at TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_table TEXT,
    target_id INTEGER,
    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
    details TEXT
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
    role TEXT NOT NULL DEFAULT 'admin' CHECK (role IN ('admin','viewer')),
    totp_secret TEXT,
    totp_enabled INTEGER NOT NULL DEFAULT 0 CHECK (totp_enabled IN (0,1)),
    session_timeout_minutes INTEGER,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS transactions (
    id SERIAL PRIMARY KEY,
    amount INTEGER NOT NULL CHECK (amount > 0),
    type TEXT NOT NULL CHECK (type IN ('income','expense')),
    category_id INTEGER NOT NULL REFERENCES categories(id) ON DELETE RESTRICT,
    date TEXT NOT NULL CHECK (date ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'),
    note TEXT DEFAULT '',
    currency TEXT DEFAULT 'INR',
    orig_amount INTEGER,
    split_group TEXT,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT now(),
    deleted_at TEXT,
    search_tsv TSVECTOR GENERATED ALWAYS AS (to_tsvector('simple', coalesce(note, ''))) STORED
);
CREATE TABLE IF NOT EXISTS budgets (
    id SERIAL PRIMARY KEY,
    category_id INTEGER UNIQUE NOT NULL REFERENCES categories(id) ON DELETE CASCADE,
    monthly_limit INTEGER NOT NULL CHECK (monthly_limit > 0)
);
CREATE TABLE IF NOT EXISTS recurrences (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    amount INTEGER NOT NULL CHECK (amount > 0),
    type TEXT NOT NULL CHECK (type IN ('income','expense')),
    category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
    note TEXT DEFAULT '',
    currency TEXT DEFAULT 'INR',
    orig_amount INTEGER,
    frequency TEXT NOT NULL CHECK (frequency IN ('daily','weekly','monthly','yearly')),
    next_run_date TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
    last_run_at TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    action TEXT NOT NULL,
    target_table TEXT,
    target_id INTEGER,
    timestamp TIMESTAMPTZ DEFAULT now(),
    details TEXT
);
CREATE INDEX IF NOT EXISTS idx_tx_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_tx_cat ON transactions(category_id);
CREATE INDEX IF NOT EXISTS idx_tx_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_tx_tsv ON transactions USING GIN (search_tsv);
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


def _sqlite_row_factory(cursor, values):
    """Dict row for sqlite3 — mutable rows with positional access (Row parity)."""
    fields = [d[0] for d in cursor.description] if cursor.description else []
    return Row(zip(fields, values))


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
    raw.row_factory = _sqlite_row_factory
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


REAL_TYPES = ("REAL", "DOUBLE", "DOUBLE PRECISION", "FLOAT", "NUMERIC", "DECIMAL")


def _migrate_money(conn):
    """Migrate REAL (rupee) amounts to INTEGER cents (idempotent).

    Detection is by declared column type: REAL/DOUBLE -> rupees, INTEGER
    -> already cents. Empty tables are migrated too so fresh inserts land
    in the right format.
    """
    try:
        if conn.engine == "sqlite":
            info = conn.execute("PRAGMA table_info(transactions)").fetchall()
            cols = {r["name"]: (r["type"] or "").upper() for r in info}
            if not cols or cols.get("amount", "INTEGER") not in REAL_TYPES:
                return
            # Old schemas may be missing columns added later (e.g. created_at).
            created = "created_at" if "created_at" in cols else "NULL"
            conn.execute("PRAGMA foreign_keys = OFF")
            conn.execute("ALTER TABLE transactions RENAME TO _old_tx")
            conn.execute(
                "CREATE TABLE transactions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " amount INTEGER NOT NULL CHECK (amount > 0),"
                " type TEXT NOT NULL CHECK (type IN ('income','expense')),"
                " category_id INTEGER NOT NULL, date TEXT NOT NULL,"
                " note TEXT DEFAULT '',"
                " user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,"
                " created_at TEXT DEFAULT CURRENT_TIMESTAMP,"
                " FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT)")
            conn.execute(
                "INSERT INTO transactions (id, amount, type, category_id, date,"
                " note, user_id, created_at) SELECT id,"
                " CAST(round(amount * 100) AS INTEGER), type, category_id, date,"
                " COALESCE(note, ''), user_id, " + created + " FROM _old_tx")
            conn.execute("DROP TABLE _old_tx")
            conn.execute("ALTER TABLE budgets RENAME TO _old_budgets")
            conn.execute(
                "CREATE TABLE budgets ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT,"
                " category_id INTEGER UNIQUE NOT NULL,"
                " monthly_limit INTEGER NOT NULL CHECK (monthly_limit > 0),"
                " FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE)")
            conn.execute(
                "INSERT INTO budgets (id, category_id, monthly_limit) SELECT id,"
                " category_id, CAST(round(monthly_limit * 100) AS INTEGER) FROM _old_budgets")
            conn.execute("DROP TABLE _old_budgets")
            conn.execute("PRAGMA foreign_keys = ON")
        else:  # pg
            rows = conn.execute(
                "SELECT data_type FROM information_schema.columns"
                " WHERE table_name='transactions' AND column_name='amount'").fetchall()
            dtype = (rows[0][0] or "").lower() if rows else ""
            if not rows or dtype.startswith(("integer", "smallint", "bigint")):
                return
            conn.execute("ALTER TABLE transactions ALTER COLUMN amount TYPE INTEGER"
                         " USING (round(amount * 100))")
            conn.execute("ALTER TABLE budgets ALTER COLUMN monthly_limit TYPE INTEGER"
                         " USING (round(monthly_limit * 100))")
        conn.commit()
    except DB_ERRORS:
        conn.rollback()
        _recover_money_swap(conn)


def _recover_money_swap(conn):
    """Best-effort undo of a half-completed REAL->INTEGER table swap.

    SQLite DDL autocommits, so a failed copy can leave an empty new table
    plus the original rows stranded in _old_tx/_old_budgets. Restore them.
    """
    if conn.engine != "sqlite":
        return
    for new_t, old_t in (("transactions", "_old_tx"), ("budgets", "_old_budgets")):
        try:
            has_old = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (old_t,)).fetchone()
            if not has_old:
                continue
            n = conn.execute(f"SELECT COUNT(*) FROM {new_t}").fetchone()[0] \
                if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table'"
                                " AND name=?", (new_t,)).fetchone() else 0
            if n == 0:
                conn.execute(f"DROP TABLE {new_t}")
                conn.execute(f"ALTER TABLE {old_t} RENAME TO {new_t}")
            else:
                conn.execute(f"DROP TABLE {old_t}")
            conn.commit()
        except DB_ERRORS:
            try:
                conn.rollback()
            except DB_ERRORS:
                pass


def log_action(db, actor, action, target_table=None, target_id=None, details=None):
    """Log a system action for auditing.

    `actor` may be a username (typical from the session) or None.
    """
    user_id = None
    if actor:
        try:
            row = db.execute("SELECT id FROM users WHERE username=?",
                             (actor,)).fetchone()
            user_id = row["id"] if row else None
        except DB_ERRORS:
            user_id = None
    db.execute(
        "INSERT INTO audit_log (user_id, action, target_table, target_id, details) VALUES (?,?,?,?,?)",
        (user_id, action, target_table, target_id, details)
    )
    db.commit()


def _migrate(conn):
    """Bring existing databases up to the current schema (idempotent)."""
    # 1. Handle money migration (REAL -> INTEGER cents)
    _migrate_money(conn)

    # 2. Add columns that may be missing in older databases.
    #    (table, column, declaration) — decl is valid for both engines.
    for table, column, decl in (
        ("users", "session_timeout_minutes", "INTEGER"),
        ("transactions", "user_id", "INTEGER"),
        ("transactions", "deleted_at", "TEXT"),
        ("transactions", "currency", "TEXT DEFAULT 'INR'"),
        ("transactions", "orig_amount", "INTEGER"),
        ("transactions", "split_group", "TEXT"),
        ("users", "role", "TEXT DEFAULT 'admin'"),
        ("users", "totp_secret", "TEXT"),
        ("users", "totp_enabled", "INTEGER DEFAULT 0"),
        ("recurrences", "currency", "TEXT DEFAULT 'INR'"),
        ("recurrences", "orig_amount", "INTEGER"),
    ):
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
                         f"{column} {decl}")
        else:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")
        conn.commit()
    _add_pg_tsv_column(conn)
    _drop_if_exists(conn, "transactions", "member_id")
    _drop_table_if_exists(conn, "members")


def _ensure_fts(conn):
    """Create the SQLite FTS5 index (note search) when supported.

    Kept in sync by triggers; silently skipped when FTS5 is unavailable
    or the backend is Postgres (which keeps using LIKE).
    """
    if conn.engine != "sqlite":
        return
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS transactions_fts"
            " USING fts5(note, content='transactions', content_rowid='id')")
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS transactions_fts_insert"
            " AFTER INSERT ON transactions BEGIN"
            " INSERT INTO transactions_fts(rowid, note) VALUES (new.id, new.note);"
            " END")
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS transactions_fts_delete"
            " AFTER DELETE ON transactions BEGIN"
            " INSERT INTO transactions_fts(transactions_fts, rowid, note)"
            " VALUES('delete', old.id, old.note);"
            " END")
        conn.execute(
            "CREATE TRIGGER IF NOT EXISTS transactions_fts_update"
            " AFTER UPDATE OF note ON transactions BEGIN"
            " INSERT INTO transactions_fts(transactions_fts, rowid, note)"
            " VALUES('delete', old.id, old.note);"
            " INSERT INTO transactions_fts(rowid, note) VALUES (new.id, new.note);"
            " END")
        conn.commit()
    except DB_ERRORS:
        try:
            conn.rollback()
        except DB_ERRORS:
            pass


def _add_pg_tsv_column(conn):
    """Add the Postgres full-text column (PG 12+ generated column + GIN index).

    Silently skipped for SQLite or older Postgres versions — those keep
    using LIKE search.
    """
    if conn.engine != "pg":
        return
    try:
        rows = conn.execute(
            "SELECT column_name FROM information_schema.columns"
            " WHERE table_name='transactions' AND column_name='search_tsv'").fetchall()
        if rows:
            return
        conn.execute(
            "ALTER TABLE transactions ADD COLUMN search_tsv TSVECTOR"
            " GENERATED ALWAYS AS (to_tsvector('simple', coalesce(note, ''))) STORED")
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_tx_tsv ON transactions USING GIN (search_tsv)")
        conn.commit()
    except DB_ERRORS:
        try:
            conn.rollback()
        except DB_ERRORS:
            pass


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
    _ensure_fts(conn)
    for name, ctype in DEFAULT_CATEGORIES:
        conn.execute("INSERT OR IGNORE INTO categories (name, type) VALUES (?, ?)",
                     (name, ctype))
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
                     (DEFAULT_USERNAME, generate_password_hash(DEFAULT_PASSWORD)))
    conn.commit()
    conn.close()
