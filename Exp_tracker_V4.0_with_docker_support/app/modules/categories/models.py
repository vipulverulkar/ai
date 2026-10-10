"""Category data access (Model layer)."""


def all(db):
    return db.execute("SELECT * FROM categories ORDER BY type, name").fetchall()


def count(db):
    return db.execute("SELECT COUNT(*) FROM categories").fetchone()[0]


def page(db, per_page, offset):
    return page_filtered(db, "", [], per_page, offset)


def filter_query(f_type="all", f_savings="all", f_usage="all", f_search=""):
    """Build WHERE/args for the categories list from filter params.

    f_type: all/income/expense; f_savings: all/savings/regular;
    f_usage: all/used/unused; f_search: substring matched against name.
    Invalid values fall back to 'all'/''. Returns (f_type, f_savings,
    f_usage, f_search, where, args) with sanitized filters.
    """
    if f_type not in ("income", "expense"):
        f_type = "all"
    if f_savings not in ("savings", "regular"):
        f_savings = "all"
    if f_usage not in ("used", "unused"):
        f_usage = "all"
    f_search = (f_search or "").strip()
    where = "WHERE 1=1"
    args = []
    if f_type != "all":
        where += " AND c.type = ?"
        args.append(f_type)
    if f_savings == "savings":
        where += " AND c.is_savings = 1"
    elif f_savings == "regular":
        where += " AND (c.is_savings IS NULL OR c.is_savings = 0)"
    if f_search:
        where += " AND c.name LIKE ?"
        args.append(f"%{f_search}%")
    if f_usage == "used":
        where += (" AND EXISTS (SELECT 1 FROM transactions t"
                  " WHERE t.category_id = c.id)")
    elif f_usage == "unused":
        where += (" AND NOT EXISTS (SELECT 1 FROM transactions t"
                  " WHERE t.category_id = c.id)")
    return f_type, f_savings, f_usage, f_search, where, args


def count_filtered(db, where, args):
    return db.execute(
        f"SELECT COUNT(*) FROM categories c {where}", args).fetchone()[0]


def page_filtered(db, where, args, per_page, offset):
    return db.execute(
        f"SELECT * FROM categories c {where} ORDER BY c.type, c.name"
        " LIMIT ? OFFSET ?",
        (*args, per_page, offset)).fetchall()


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


def set_savings(db, cat_id, flag):
    """Flag/unflag an expense category as a savings bucket (commits)."""
    db.execute("UPDATE categories SET is_savings=? WHERE id=? AND type='expense'",
               (1 if flag else 0, cat_id))
    db.commit()


def seed_defaults(db):
    """Insert DEFAULT_CATEGORIES if missing (no commit); returns reseeded count.

    Newly seeded savings buckets are flagged; existing rows are untouched.
    """
    from ...config import DEFAULT_CATEGORIES, SAVINGS_CATEGORIES
    n = 0
    for name, ctype in DEFAULT_CATEGORIES:
        if insert(db, name, ctype):
            n += 1
            if name in SAVINGS_CATEGORIES:
                db.execute("UPDATE categories SET is_savings=1 WHERE name=? AND type='expense'",
                           (name,))
    return n


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
    """{category_id: number of live (non-trashed) transactions}."""
    return {r["category_id"]: r["cnt"] for r in db.execute(
        "SELECT category_id, COUNT(*) AS cnt FROM transactions"
        " WHERE deleted_at IS NULL GROUP BY category_id").fetchall()}


def transaction_count(db, cat_id):
    """Live (non-trashed) transactions in a category — trashed rows must not
    block deleting a category (purge first only if live rows use it)."""
    return db.execute(
        "SELECT COUNT(*) FROM transactions WHERE category_id=? AND deleted_at IS NULL",
        (cat_id,)).fetchone()[0]
