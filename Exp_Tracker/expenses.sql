-- Expense Tracker database schema (SQLite)
-- Creates the same tables as app.py init_db().
-- Usage: sqlite3 expenses.db < expenses.sql
--    or: python3 -c "import sqlite3; db=sqlite3.connect('expenses.db'); db.executescript(open('expenses.sql').read()); db.commit()"

PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT UNIQUE NOT NULL,
    type TEXT NOT NULL CHECK (type IN ('income','expense'))
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    amount REAL NOT NULL CHECK (amount > 0),
    type TEXT NOT NULL CHECK (type IN ('income','expense')),
    category_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    note TEXT DEFAULT '',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT
);

-- Default categories (same as app.py DEFAULT_CATEGORIES)
INSERT OR IGNORE INTO categories (name, type) VALUES
    ('Salary', 'income'),
    ('Freelance', 'income'),
    ('Investment', 'income'),
    ('Food', 'expense'),
    ('Transport', 'expense'),
    ('Shopping', 'expense'),
    ('Bills', 'expense'),
    ('Entertainment', 'expense'),
    ('Health', 'expense'),
    ('Other', 'expense');
