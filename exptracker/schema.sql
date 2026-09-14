-- ============================================================
-- Expense Tracker database schema (SQLite)
-- Canonical DB script for this project.
--
-- Recreate a fresh database with:
--   sqlite3 expenses.db < schema.sql
-- (The app also auto-creates this schema on launch via init_db().)
-- ============================================================

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categories (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    type TEXT NOT NULL CHECK(type IN ('Income','Expense')),
    UNIQUE(name, type)
);

CREATE TABLE IF NOT EXISTS transactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date        TEXT NOT NULL,          -- YYYY-MM-DD
    type        TEXT NOT NULL CHECK(type IN ('Income','Expense')),
    category    TEXT NOT NULL,          -- denormalized display name (kept for history)
    category_id INTEGER REFERENCES categories(id) ON UPDATE CASCADE ON DELETE SET NULL,
    amount      REAL NOT NULL CHECK(amount > 0),
    note        TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_txn_date ON transactions(date);
CREATE INDEX IF NOT EXISTS idx_txn_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_txn_category_id ON transactions(category_id);

-- WAL mode + foreign keys (set per-connection in app; documented here)
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;

-- ---------------- default seed data ----------------
INSERT OR IGNORE INTO categories(name, type) VALUES
    ('Salary',         'Income'),
    ('Business',       'Income'),
    ('Freelance',      'Income'),
    ('Interest',       'Income'),
    ('Gift Received',  'Income'),
    ('Other Income',   'Income'),
    ('Food',           'Expense'),
    ('Groceries',      'Expense'),
    ('Rent',           'Expense'),
    ('Transport',      'Expense'),
    ('Utilities',      'Expense'),
    ('Shopping',       'Expense'),
    ('Health',         'Expense'),
    ('Education',      'Expense'),
    ('Entertainment',  'Expense'),
    ('Savings',        'Expense'),
    ('Other Expense',  'Expense');
