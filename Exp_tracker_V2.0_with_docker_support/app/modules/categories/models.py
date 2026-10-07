"""Category data access (Model layer)."""


def all(db):
    return db.execute("SELECT * FROM categories ORDER BY type, name").fetchall()


def by_type(db, ctype):
    return db.execute(
        "SELECT * FROM categories WHERE type=? ORDER BY name", (ctype,)).fetchall()


def get(db, cat_id):
    return db.execute("SELECT * FROM categories WHERE id=?", (cat_id,)).fetchone()


def get_by_name(db, name):
    return db.execute("SELECT * FROM categories WHERE name=?", (name,)).fetchone()


def create(db, name, ctype):
    """Insert a category. Raises an IntegrityError (db.INTEGRITY_ERRORS) on duplicate name."""
    db.execute("INSERT INTO categories (name, type) VALUES (?, ?)", (name, ctype))
    db.commit()


def insert(db, name, ctype):
    """INSERT OR IGNORE a category (no commit). Returns True if a row was added."""
    cur = db.execute("INSERT OR IGNORE INTO categories (name, type) VALUES (?, ?)",
                     (name, ctype))
    return cur.rowcount > 0


def rename(db, cat_id, name):
    """Rename a category. Raises an IntegrityError (db.INTEGRITY_ERRORS) on duplicate name."""
    db.execute("UPDATE categories SET name=? WHERE id=?", (name, cat_id))
    db.commit()


def delete(db, cat_id):
    """Delete a category and its budgets. Caller must check it's unused."""
    db.execute("DELETE FROM budgets WHERE category_id=?", (cat_id,))
    db.execute("DELETE FROM categories WHERE id=?", (cat_id,))
    db.commit()


def usage_counts(db):
    """{category_id: number_of_transactions}."""
    return {r["category_id"]: r["cnt"] for r in db.execute(
        "SELECT category_id, COUNT(*) AS cnt FROM transactions GROUP BY category_id").fetchall()}


def transaction_count(db, cat_id):
    return db.execute(
        "SELECT COUNT(*) FROM transactions WHERE category_id=?", (cat_id,)).fetchone()[0]
