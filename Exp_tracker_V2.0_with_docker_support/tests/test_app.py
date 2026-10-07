"""Smoke tests for Expense Tracker v2. Run: python -m pytest -q"""
import io

import pytest

from app import create_app
from app.db import get_db


@pytest.fixture()
def client(tmp_path):
    """Logged-in test client (fresh temp DB per test)."""
    app = create_app({"TESTING": True, "EXPENSE_DB": str(tmp_path / "test.db")})
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "admin"})
    return c


def test_login_flow(tmp_path):
    app = create_app({"TESTING": True, "EXPENSE_DB": str(tmp_path / "test.db")})
    c = app.test_client()
    # everything requires auth
    r = c.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]
    # healthz stays public (docker healthcheck), api returns 401 JSON
    assert c.get("/healthz").status_code == 200
    r = c.get("/api/summary")
    assert r.status_code == 401 and r.get_json()["error"]
    # wrong credentials
    r = c.post("/login", data={"username": "admin", "password": "wrong"})
    assert r.status_code == 200 and b"Invalid username or password" in r.data
    # right credentials -> dashboard
    r = c.post("/login", data={"username": "admin", "password": "admin"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    assert c.get("/").status_code == 200
    # logout
    assert c.get("/logout").status_code == 302
    r = c.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_default_admin_seeded_in_db(client):
    with client.application.app_context():
        db = get_db()
        row = db.execute("SELECT username FROM users WHERE username='admin'").fetchone()
    assert row is not None


def test_login_uses_db_credentials(client):
    """Changing the hash in the users table changes the login password."""
    from werkzeug.security import generate_password_hash
    with client.application.app_context():
        db = get_db()
        db.execute("UPDATE users SET password_hash=? WHERE username='admin'",
                   (generate_password_hash("s3cret"),))
        db.commit()
    c = client.application.test_client()  # fresh, logged-out client
    r = c.post("/login", data={"username": "admin", "password": "admin"})
    assert b"Invalid username or password" in r.data
    r = c.post("/login", data={"username": "admin", "password": "s3cret"})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")


def seed_txn(client, amount=100, ttype="expense", note="test"):
    with client.application.app_context():
        db = get_db()
        cat = db.execute("SELECT id FROM categories WHERE type=? LIMIT 1", (ttype,)).fetchone()
        cat_id = cat["id"]
    return client.post("/add", data={
        "amount": str(amount), "type": ttype, "category_id": str(cat_id),
        "date": "2026-01-15", "note": note}, follow_redirects=False)


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_add_and_list(client):
    r = seed_txn(client, 250, "expense", "groceries")
    assert r.status_code == 302
    r = client.get("/transactions")
    assert r.status_code == 200
    assert b"groceries" in r.data


def test_validation_rejects_bad_amount(client):
    r = seed_txn(client, -5, "expense")
    assert r.status_code == 302  # redirect with flash
    r = client.get("/transactions")
    assert b"No transactions found" in r.data or b"0 total" in r.data


def test_type_mismatch_rejected(client):
    with client.application.app_context():
        db = get_db()
        cat = db.execute("SELECT id FROM categories WHERE type='income' LIMIT 1").fetchone()
    r = client.post("/add", data={"amount": "10", "type": "expense",
                                  "category_id": str(cat["id"]),
                                  "date": "2026-01-15", "note": "x"})
    assert r.status_code == 302


def test_budgets_set_and_show(client):
    with client.application.app_context():
        db = get_db()
        cat = db.execute("SELECT id FROM categories WHERE type='expense' LIMIT 1").fetchone()
    r = client.post("/budgets", data={"category_id": str(cat["id"]),
                                      "monthly_limit": "5000"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b"5000" in r.data or b"Budget" in r.data


def test_csv_export_import_roundtrip(client):
    seed_txn(client, 123.45, "expense", "roundtrip-note")
    r = client.get("/transactions/export")
    assert r.status_code == 200
    assert "text/csv" in r.content_type
    assert b"roundtrip-note" in r.data
    # import it back as a new row
    data = {"file": (io.BytesIO(b"date,type,category,amount,note\n2026-02-01,expense,Food,99.99,csv-test\n"), "t.csv")}
    r = client.post("/transactions/import", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"csv-test" in client.get("/transactions").data


def test_api(client):
    seed_txn(client, 500, "income", "salary-x")
    r = client.get("/api/summary?month=2026-01")
    assert r.status_code == 200
    assert r.get_json()["income"] >= 500
    r = client.get("/api/transactions?limit=5")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


def test_reports_and_dashboard_render(client):
    seed_txn(client, 50, "expense", "rep")
    assert b"Good day, Admin" in client.get("/").data
    for url in ["/", "/reports", "/reports?view=monthly&year=2026",
                "/categories", "/budgets", "/data"]:
        assert client.get(url).status_code == 200


def test_full_data_import(client):
    data = {
        "categories_file": (io.BytesIO(b"name,type\nGadgets,expense\nRoyalties,income\n"), "categories.csv"),
        "budgets_file": (io.BytesIO(b"category,monthly_limit\nGadgets,2500\n"), "budgets.csv"),
        "transactions_file": (io.BytesIO(
            b"date,type,category,amount,note\n2026-01-10,expense,Gadgets,999,headphones\n"
            b"2026-01-11,income,Royalties,300,book\n"), "transactions.csv"),
    }
    r = client.post("/data/import", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"Categories: imported 2" in r.data
    assert b"Budgets: imported 1" in r.data
    assert b"Transactions: imported 2" in r.data
    assert b"Gadgets" in client.get("/categories").data
    assert b"Gadgets" in client.get("/budgets").data
    assert b"headphones" in client.get("/transactions").data


def test_full_data_import_skips_bad_rows(client):
    data = {
        # invalid type -> skipped; "Pets" is new -> imported
        "categories_file": (io.BytesIO(
            b"name,type\nPets,expense\nBad Row,unknown-type\n"), "c.csv"),
        "budgets_file": (io.BytesIO(
            b"category,monthly_limit\nPets,1500\nGhost,100\noops,not-a-number\n"), "b.csv"),
    }
    r = client.post("/data/import", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"Categories: imported 1 row(s), 1 skipped." in r.data
    assert b"Budgets: imported 1 row(s), 2 skipped." in r.data


def test_full_data_import_requires_file(client):
    r = client.post("/data/import", data={},
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"Choose at least one CSV file to import." in r.data


def test_full_data_import_rejects_non_csv(client):
    data = {"categories_file": (io.BytesIO(b"name,type\nX,expense\n"), "c.txt")}
    r = client.post("/data/import", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"please upload a .csv file" in r.data


def test_healthz_reports_db_engine(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json()["db"] == "sqlite"  # default backend


def test_db_type_resolution():
    import pytest
    from app.db import resolve_engine
    # default: sqlite, even with no keys at all
    assert resolve_engine({}) == "sqlite"
    # explicit sqlite wins (DATABASE_URL ignored)
    assert resolve_engine({"DB_TYPE": "sqlite",
                           "DATABASE_URL": "postgresql://x"}) == "sqlite"
    # backward compat: DATABASE_URL alone auto-selects postgres
    assert resolve_engine({"DATABASE_URL": "postgresql://x"}) == "pg"
    assert resolve_engine({"DB_TYPE": "postgres",
                           "DATABASE_URL": "postgresql://x"}) == "pg"
    assert resolve_engine({"DB_TYPE": "postgresql",
                           "DATABASE_URL": "postgresql://x"}) == "pg"
    # postgres without a DSN, or a bogus value, fails fast with a clear error
    with pytest.raises(RuntimeError):
        resolve_engine({"DB_TYPE": "postgres"})
    with pytest.raises(RuntimeError):
        resolve_engine({"DB_TYPE": "mysql"})


def test_data_page_shows_active_db(client):
    r = client.get("/data")
    assert r.status_code == 200
    assert b"SQLite" in r.data
    assert b"Download backup" in r.data


def _backdate_activity(client, minutes):
    import time
    with client.session_transaction() as sess:
        sess["last_active"] = time.time() - minutes * 60


def test_idle_timeout_logs_out(client):
    # recent activity: still signed in
    _backdate_activity(client, 5)
    assert client.get("/").status_code == 200
    # idle past the 15-minute default: signed out with a message
    _backdate_activity(client, 16)
    r = client.get("/", follow_redirects=True)
    assert r.status_code == 200
    assert b"Signed out due to inactivity" in r.data
    assert b"Welcome back" in r.data
    # and protected pages bounce to login again
    assert client.get("/budgets").status_code == 302


def test_env_timeout_override(tmp_path):
    app = create_app({"TESTING": True, "EXPENSE_DB": str(tmp_path / "t.db"),
                      "SESSION_TIMEOUT_MINUTES": 60})
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "admin"})
    assert c.get("/healthz").get_json()["db"] == "sqlite"
    with c.session_transaction() as sess:
        import time
        sess["last_active"] = time.time() - 30 * 60
    assert c.get("/").status_code == 200  # within the 60-min env limit
    with c.session_transaction() as sess:
        import time
        sess["last_active"] = time.time() - 61 * 60
    r = c.get("/", follow_redirects=True)
    assert b"Signed out due to inactivity" in r.data


def test_profile_timeout_override(client):
    # default shown, no personal override yet
    r = client.get("/profile")
    assert r.status_code == 200
    assert b"admin" in r.data and b"15 min idle" in r.data
    # set a personal override
    r = client.post("/profile", data={"timeout_minutes": "30"},
                    follow_redirects=True)
    assert b"Session timeout updated" in r.data
    assert b"30 min idle" in client.get("/profile").data
    # override wins over the 15-min default for idle enforcement
    _backdate_activity(client, 20)
    assert client.get("/").status_code == 200
    _backdate_activity(client, 31)
    assert b"Signed out due to inactivity" in client.get("/",
                                                         follow_redirects=True).data
    # blank clears back to the default (re-login first: previous step signed out)
    client.post("/login", data={"username": "admin", "password": "admin"})
    client.post("/profile", data={"timeout_minutes": ""}, follow_redirects=True)
    assert b"15 min idle" in client.get("/profile").data
    # invalid values rejected, previous setting kept
    for bad in ("0", "-5", "9999", "abc"):
        r = client.post("/profile", data={"timeout_minutes": bad},
                        follow_redirects=True)
        assert b"Timeout must be" in r.data
    assert b"15 min idle" in client.get("/profile").data


def test_migration_adds_timeout_column(tmp_path):
    """Databases created before the timeout column get it on boot."""
    import sqlite3
    from werkzeug.security import generate_password_hash
    from app.db import init_db
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,"
               " username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)")
    db.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)",
               ("admin", generate_password_hash("admin")))
    db.commit()
    db.close()
    init_db({"DB_TYPE": "sqlite", "DATABASE_URL": None, "EXPENSE_DB": path})
    cols = [r[1] for r in sqlite3.connect(path).execute("PRAGMA table_info(users)")]
    assert "session_timeout_minutes" in cols
    # and the migrated db works end to end
    app = create_app({"TESTING": True, "EXPENSE_DB": path})
    c = app.test_client()
    c.post("/login", data={"username": "admin", "password": "admin"})
    assert c.get("/profile").status_code == 200


def test_user_management(client):
    # page lists admin, add form present
    r = client.get("/users")
    assert r.status_code == 200
    assert b"admin" in r.data and b"Add user" in r.data
    # add a user, then sign in as them
    r = client.post("/users", data={"username": "analyst", "password": "s3cret"},
                    follow_redirects=True)
    assert b"analyst" in r.data
    c2 = client.application.test_client()
    assert c2.post("/login", data={"username": "analyst",
                                   "password": "s3cret"}).status_code == 302
    # duplicates and invalid input rejected
    for data, msg in [({"username": "analyst", "password": "other"}, b"already exists"),
                      ({"username": "ab", "password": "s3cret"}, b"Username must be"),
                      ({"username": "analyst2", "password": "x"}, b"Password must be")]:
        r = client.post("/users", data=data, follow_redirects=True)
        assert msg in r.data
    # password reset works
    with client.application.app_context():
        uid = get_db().execute("SELECT id FROM users WHERE username='analyst'").fetchone()[0]
        me = get_db().execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
    r = client.post(f"/users/password/{uid}", data={"password": "n3wpass"},
                    follow_redirects=True)
    assert b"Password updated" in r.data
    c3 = client.application.test_client()
    assert c3.post("/login", data={"username": "analyst",
                                   "password": "n3wpass"}).status_code == 302
    r = client.post(f"/users/password/{uid}", data={"password": "x"},
                    follow_redirects=True)
    assert b"Password must be" in r.data
    # cannot delete yourself or the last user; deleting others works
    r = client.post(f"/users/delete/{me}", data={}, follow_redirects=True)
    assert b"your own account" in r.data
    assert client.post(f"/users/delete/{uid}", data={},
                       follow_redirects=True).status_code == 200
    assert b"analyst" not in client.get("/users").data
    r = client.post(f"/users/delete/{me}", data={}, follow_redirects=True)
    assert b"last remaining user" in r.data
    with client.application.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def _user_id(client, name):
    with client.application.app_context():
        return get_db().execute("SELECT id FROM users WHERE username=?",
                                (name,)).fetchone()[0]


def test_transaction_ownership(client):
    # a second user to manage expenses for
    client.post("/users", data={"username": "analyst", "password": "s3cret"})
    analyst = _user_id(client, "analyst")
    with client.application.app_context():
        cat = get_db().execute(
            "SELECT id FROM categories WHERE type='expense' LIMIT 1").fetchone()
        admin = get_db().execute(
            "SELECT id FROM users WHERE username='admin'").fetchone()
    # blank owner defaults to yourself
    client.post("/add", data={"amount": "75", "type": "expense",
                              "category_id": str(cat["id"]),
                              "date": "2026-01-15", "note": "mine"},
                follow_redirects=False)
    with client.application.app_context():
        tx = get_db().execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT 1").fetchone()
        assert tx["user_id"] == admin["id"]
    # explicit owner assigns the expense to that user
    r = client.post("/add", data={"amount": "75", "type": "expense",
                                  "category_id": str(cat["id"]),
                                  "date": "2026-01-15", "note": "gift",
                                  "owner": str(analyst)},
                    follow_redirects=False)
    assert r.status_code == 302
    with client.application.app_context():
        tx = get_db().execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT 1").fetchone()
        assert tx["user_id"] == analyst
    # shown in the list and honored by the filter
    assert b"analyst" in client.get("/transactions").data
    assert b"gift" in client.get(f"/transactions?owner={analyst}").data
    assert b"gift" not in client.get("/transactions?owner=none").data
    assert b"mine" in client.get(f"/transactions?owner={admin['id']}").data
    # user expense profile totals include it
    assert b"gift" not in client.get(f"/users/{analyst}").data  # notes not shown
    assert b"75.00" in client.get(f"/users/{analyst}").data
    # edit can reassign; unknown user rejected
    tid = tx["id"]
    r = client.post(f"/edit/{tid}", data={"amount": "75", "type": "expense",
                                           "category_id": str(cat["id"]),
                                           "date": "2026-01-15", "note": "gift",
                                           "owner": "99999"},
                    follow_redirects=True)
    assert b"valid user" in r.data
    client.post(f"/edit/{tid}", data={"amount": "75", "type": "expense",
                                      "category_id": str(cat["id"]),
                                      "date": "2026-01-15", "note": "gift",
                                      "owner": str(admin["id"])},
                follow_redirects=True)
    with client.application.app_context():
        assert get_db().execute(
            "SELECT user_id FROM transactions WHERE id=?",
            (tid,)).fetchone()[0] == admin["id"]
    # duplicate keeps the same owner
    client.post(f"/duplicate/{tid}", data={}, follow_redirects=True)
    with client.application.app_context():
        dup = get_db().execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT 1").fetchone()
        assert dup["user_id"] == admin["id"]


def test_csv_import_with_owner(client):
    client.post("/users", data={"username": "analyst", "password": "s3cret"})
    data = {"file": (io.BytesIO(
        b"date,type,category,amount,note,owner\n"
        b"2026-02-01,expense,Food,42,csv-owned,analyst\n"
        b"2026-02-02,expense,Food,43,csv-ghost,ghost\n"), "t.csv")}
    r = client.post("/transactions/import", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"csv-owned" in client.get("/transactions").data
    with client.application.app_context():
        db = get_db()
        analyst = db.execute(
            "SELECT id FROM users WHERE username='analyst'").fetchone()[0]
        admin = db.execute(
            "SELECT id FROM users WHERE username='admin'").fetchone()[0]
        assert db.execute(
            "SELECT user_id FROM transactions WHERE note='csv-owned'").fetchone()[0] == analyst
        # unknown owner falls back to the importer
        assert db.execute(
            "SELECT user_id FROM transactions WHERE note='csv-ghost'").fetchone()[0] == admin
    # old 5-column CSVs still import fine (attributed to the importer)
    data = {"file": (io.BytesIO(
        b"date,type,category,amount,note\n"
        b"2026-02-03,expense,Food,44,csv-plain\n"), "t.csv")}
    client.post("/transactions/import", data=data,
                content_type="multipart/form-data", follow_redirects=True)
    assert b"csv-plain" in client.get("/transactions").data


def test_profile_recorded_stats(client):
    seed_txn(client, 500, "income", "salary-stat")
    r = client.get("/profile")
    assert b"Expenses you manage" in r.data
    assert b"1 managed" in r.data and b"Salary" in r.data


def test_backup_carries_owners(client):
    import json
    client.post("/users", data={"username": "analyst", "password": "s3cret"})
    analyst = _user_id(client, "analyst")
    with client.application.app_context():
        cat = get_db().execute(
            "SELECT id FROM categories WHERE type='expense' LIMIT 1").fetchone()
    client.post("/add", data={"amount": "11", "type": "expense",
                              "category_id": str(cat["id"]),
                              "date": "2026-01-15", "note": "bk",
                              "owner": str(analyst)})
    payload = json.loads(client.get("/data/backup").data.decode())
    assert "members" not in payload["data"]
    with client.application.app_context():
        get_db().execute("DELETE FROM transactions")
        get_db().commit()
    r = client.post("/data/restore",
                    data={"backup_file": (
                        io.BytesIO(json.dumps(payload).encode()), "b.json"),
                        "confirm": "yes"},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"Restored" in r.data
    assert b"analyst" in client.get("/transactions").data


def test_retired_members_cleaned_up(tmp_path):
    """DBs from the members era lose the table/column on boot, data kept."""
    import sqlite3
    path = str(tmp_path / "members-era.db")
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,"
               " username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL)")
    db.execute("INSERT INTO users (username, password_hash) VALUES ('admin', 'x')")
    db.execute("CREATE TABLE members (id INTEGER PRIMARY KEY AUTOINCREMENT,"
               " name TEXT UNIQUE NOT NULL)")
    db.execute("INSERT INTO members (name) VALUES ('Ghost')")
    db.execute("CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT,"
               " name TEXT UNIQUE NOT NULL, type TEXT NOT NULL)")
    db.execute("INSERT INTO categories (name, type) VALUES ('Food', 'expense')")
    db.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
               " amount REAL NOT NULL, type TEXT NOT NULL, category_id INTEGER NOT NULL,"
               " date TEXT NOT NULL, note TEXT, member_id INTEGER, user_id INTEGER)")
    db.execute("INSERT INTO transactions (amount, type, category_id, date, note)"
               " VALUES (9.5, 'expense', 1, '2026-01-01', 'kept')")
    db.execute("CREATE TABLE budgets (id INTEGER PRIMARY KEY AUTOINCREMENT,"
               " category_id INTEGER UNIQUE NOT NULL, monthly_limit REAL NOT NULL)")
    db.commit()
    db.close()
    from app.db import init_db
    init_db({"DB_TYPE": "sqlite", "DATABASE_URL": None, "EXPENSE_DB": path})
    db = sqlite3.connect(path)
    tables = [r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    assert "members" not in tables
    tx_cols = [r[1] for r in db.execute("PRAGMA table_info(transactions)")]
    assert "member_id" not in tx_cols and "user_id" in tx_cols
    assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    assert db.execute("SELECT note FROM transactions").fetchone()[0] == "kept"


def test_pg_sql_translation():
    from app.db import Row, to_pg
    assert to_pg("SELECT * FROM t WHERE a=? AND b=?") == \
        "SELECT * FROM t WHERE a=%s AND b=%s"
    assert to_pg("INSERT OR IGNORE INTO categories (name, type) VALUES (?, ?)") == \
        "INSERT INTO categories (name, type) VALUES (%s, %s) ON CONFLICT DO NOTHING"
    # upsert passes through with only placeholder translation
    assert to_pg("INSERT INTO budgets (category_id, monthly_limit) VALUES (?,?) "
                 "ON CONFLICT(category_id) DO UPDATE SET monthly_limit=excluded.monthly_limit") == \
        ("INSERT INTO budgets (category_id, monthly_limit) VALUES (%s,%s) "
         "ON CONFLICT(category_id) DO UPDATE SET monthly_limit=excluded.monthly_limit")
    # dict-style row with positional access (sqlite3.Row parity)
    r = Row(zip(["a", "b"], [10, 20]))
    assert r["a"] == 10 and r[0] == 10 and r[1] == 20 and dict(r) == {"a": 10, "b": 20}


def test_backup_restore_roundtrip(client):
    import json
    seed_txn(client, 250, "expense", "backup-note")
    r = client.get("/data/backup")
    assert r.status_code == 200
    assert "application/json" in r.content_type
    assert "attachment" in r.headers.get("Content-Disposition", "")
    payload = json.loads(r.data.decode())
    assert payload["app"] == "exptracker"
    assert {t: len(payload["data"][t]) for t in
            ("categories", "budgets", "transactions", "users")}
    assert len(payload["data"]["transactions"]) >= 1
    # wipe then restore (confirmation checkbox required)
    with client.application.app_context():
        db = get_db()
        db.execute("DELETE FROM transactions")
        db.commit()
        assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    r = client.post("/data/restore",
                    data={"backup_file": (io.BytesIO(r.data), "b.json"), "confirm": "yes"},
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200 and b"Restored" in r.data
    assert b"backup-note" in client.get("/transactions").data


def test_restore_needs_confirm_and_valid_json(client):
    import json
    seed_txn(client, 50, "expense", "keep-me")
    blob = client.get("/data/backup").data
    # missing confirmation checkbox
    r = client.post("/data/restore",
                    data={"backup_file": (io.BytesIO(blob), "b.json")},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"confirmation" in r.data
    # wrong extension
    r = client.post("/data/restore",
                    data={"backup_file": (io.BytesIO(blob), "b.txt"), "confirm": "yes"},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b".json" in r.data
    # unreadable JSON
    r = client.post("/data/restore",
                    data={"backup_file": (io.BytesIO(b"not json"), "b.json"),
                          "confirm": "yes"},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"could not read JSON" in r.data
    # structurally invalid payload -> rejected, existing data intact
    bad = json.dumps({"data": {"categories": [{"id": 1}]}}).encode()
    r = client.post("/data/restore",
                    data={"backup_file": (io.BytesIO(bad), "b.json"), "confirm": "yes"},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"Restore failed" in r.data
    assert b"keep-me" in client.get("/transactions").data


def test_restore_pg_path_resets_sequences():
    """The Postgres restore path must translate placeholders and reset id sequences."""
    import json
    from app.db import Connection
    from app.modules.data import models as data_models

    seen = []

    class FakeCursor:
        def fetchone(self):
            return None

        def fetchall(self):
            return []

    class FakeRaw:
        def execute(self, sql, params=()):
            seen.append((sql, params))
            return FakeCursor()

        def commit(self):
            seen.append(("COMMIT", ()))

        def rollback(self):
            seen.append(("ROLLBACK", ()))

    payload = {
        "app": "exptracker", "version": 1,
        "data": {
            "users": [{"id": 1, "username": "admin", "password_hash": "x",
                       "created_at": "2026-01-01T00:00:00+00:00"}],
            "categories": [{"id": 1, "name": "Food", "type": "expense"}],
            "budgets": [{"id": 1, "category_id": 1, "monthly_limit": 100}],
            "transactions": [{"id": 1, "amount": 10, "type": "expense",
                              "category_id": 1, "date": "2026-01-15",
                              "note": "", "created_at": None}],
        },
    }
    # round-trip through JSON like the real HTTP upload does
    payload = json.loads(json.dumps(payload))
    conn = Connection(FakeRaw(), "pg")
    counts, err = data_models.restore_backup(conn, payload)
    assert err is None, err
    assert counts == {"categories": 1, "budgets": 1, "transactions": 1, "users": 1}
    stmts = [s for s, _ in seen]
    # sqlite-style ? placeholders translated for psycopg, no ? left behind
    assert any("%s" in s and s.startswith("INSERT INTO users") for s in stmts)
    assert not any("?" in s for s in stmts)
    # one sequence reset per table (empty tables restart at 1 via 3-arg setval)
    resets = [s for s in stmts if "pg_get_serial_sequence" in s]
    assert len(resets) == 4
    assert all("setval" in s and ", (SELECT COUNT(*) FROM " in s for s in resets)
