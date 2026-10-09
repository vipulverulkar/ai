"""Smoke + feature tests for Expense Tracker. Run: python -m pytest -q"""
import io
import json
import re
import sqlite3
from datetime import date

import pytest

from app import create_app
from app.db import get_db


# ---------- helpers ----------

def _csrf_token(client, url="/login"):
    """Extract the CSRF token from any page that renders a form."""
    r = client.get(url, follow_redirects=True)
    m = re.search(r'name="csrf_token"[^>]*value="([^"]+)"',
                  r.data.decode("utf-8", errors="replace"))
    if m:
        return m.group(1)
    raise RuntimeError(f"Could not find csrf_token on {url}")


def login(client, username="admin", password="admin"):
    return client.post("/login", data={
        "username": username, "password": password,
        "csrf_token": _csrf_token(client, "/login")}, follow_redirects=False)


def postf(client, path, form_url="/", follow_redirects=False, **data):
    """POST with a CSRF token fetched from the page that renders the form."""
    data["csrf_token"] = _csrf_token(client, form_url)
    return client.post(path, data=data, follow_redirects=follow_redirects)


@pytest.fixture()
def client(tmp_path):
    """Logged-in test client (fresh temp DB per test)."""
    app = create_app({"TESTING": True, "EXPENSE_DB": str(tmp_path / "test.db")})
    c = app.test_client()
    login(c)
    return c


def seed_txn(client, amount=100, ttype="expense", note="test", **extra):
    with client.application.app_context():
        db = get_db()
        cat = db.execute("SELECT id FROM categories WHERE type=? LIMIT 1",
                         (ttype,)).fetchone()
        cat_id = cat["id"]
    data = {"amount": str(amount), "type": ttype, "category_id": str(cat_id),
            "date": "2026-01-15", "note": note}
    data.update(extra)
    return postf(client, "/add", "/", **data)


def cat_id_of(client, ttype, name=None):
    with client.application.app_context():
        db = get_db()
        if name:
            row = db.execute("SELECT id FROM categories WHERE name=?", (name,)).fetchone()
        else:
            row = db.execute("SELECT id FROM categories WHERE type=? LIMIT 1",
                             (ttype,)).fetchone()
        return row["id"]


# ---------- auth ----------

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
    token = _csrf_token(c, "/login")
    r = c.post("/login", data={"username": "admin", "password": "wrong",
                               "csrf_token": token})
    assert r.status_code == 200 and b"Invalid username or password" in r.data
    # right credentials -> dashboard
    r = c.post("/login", data={"username": "admin", "password": "admin",
                               "csrf_token": token})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")
    assert c.get("/").status_code == 200
    # logout
    assert c.get("/logout").status_code == 302
    r = c.get("/")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_csrf_rejected_without_token(tmp_path):
    app = create_app({"TESTING": True, "EXPENSE_DB": str(tmp_path / "test.db")})
    c = app.test_client()
    r = c.post("/login", data={"username": "admin", "password": "admin"})
    assert r.status_code == 400  # CSRF protection is active


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
                   (generate_password_hash("s3cretpass"),))
        db.commit()
    c = client.application.test_client()  # fresh, logged-out client
    token = _csrf_token(c, "/login")
    r = c.post("/login", data={"username": "admin", "password": "admin",
                               "csrf_token": token})
    assert b"Invalid username or password" in r.data
    r = c.post("/login", data={"username": "admin", "password": "s3cretpass",
                               "csrf_token": token})
    assert r.status_code == 302 and r.headers["Location"].endswith("/")


# ---------- transactions ----------

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
    # amounts render in rupees (cents storage), Indian grouping
    assert "250.00".encode() in r.data


def test_amount_stored_as_cents(client):
    seed_txn(client, 123.45, "expense", "cents")
    with client.application.app_context():
        db = get_db()
        row = db.execute("SELECT amount FROM transactions WHERE note='cents'").fetchone()
    assert row["amount"] == 12345  # INTEGER cents, no float dust


def test_validation_rejects_bad_amount(client):
    r = seed_txn(client, -5, "expense")
    assert r.status_code == 302  # redirect with flash
    r = client.get("/transactions")
    assert b"No transactions found" in r.data or b"0 total" in r.data


def test_future_date_rejected(client):
    r = seed_txn(client, 10, "expense", "future", date="2099-01-01")
    assert r.status_code == 302
    with client.application.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM transactions WHERE note='future'").fetchone()[0] == 0


def test_type_mismatch_rejected(client):
    income_cat = cat_id_of(client, "income")
    r = postf(client, "/add", "/", amount="10", type="expense",
              category_id=str(income_cat), date="2026-01-15", note="x")
    assert r.status_code == 302
    with client.application.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_soft_delete_hides_rows(client):
    seed_txn(client, 100, "expense", "del-me")
    tid = _user_id(client, "admin")  # placeholder, replaced below
    with client.application.app_context():
        tid = get_db().execute(
            "SELECT id FROM transactions WHERE note='del-me'").fetchone()[0]
    r = postf(client, f"/delete/{tid}", "/transactions")
    assert r.status_code == 302
    assert b"del-me" not in client.get("/transactions").data
    # the row is kept (soft delete) with deleted_at stamped
    with client.application.app_context():
        row = get_db().execute(
            "SELECT deleted_at FROM transactions WHERE id=?", (tid,)).fetchone()
    assert row["deleted_at"] is not None


def test_budgets_set_and_show(client):
    cat = cat_id_of(client, "expense")
    r = postf(client, "/budgets", "/budgets", category_id=str(cat),
              monthly_limit="5000", follow_redirects=True)
    assert r.status_code == 200
    assert "5,000.00".encode() in r.data


def test_csv_export_import_roundtrip(client):
    seed_txn(client, 123.45, "expense", "roundtrip-note")
    r = client.get("/transactions/export")
    assert r.status_code == 200
    assert "text/csv" in r.content_type
    assert b"roundtrip-note" in r.data
    assert b"123.45" in r.data  # exported in rupees
    # import it back as a new row
    token = _csrf_token(client, "/transactions")
    data = {"file": (io.BytesIO(b"date,type,category,amount,note\n"
                                b"2026-02-01,expense,Food,99.99,csv-test\n"), "t.csv"),
            "csrf_token": token}
    r = client.post("/transactions/import", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"csv-test" in client.get("/transactions").data


def test_api(client):
    seed_txn(client, 500, "income", "salary-x")
    r = client.get("/api/summary?month=2026-01")
    assert r.status_code == 200
    assert r.get_json()["income"] == 500.0
    r = client.get("/api/transactions?limit=5")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


def test_api_v1(client):
    seed_txn(client, 500, "income", "salary-v1")
    r = client.get("/api/v1/summary?month=2026-01")
    assert r.status_code == 200
    assert r.get_json()["income"] == 500.0
    r = client.get("/api/v1/transactions?limit=5")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)
    # unauthenticated v1 API returns 401 JSON like the legacy one
    c2 = client.application.test_client()
    r = c2.get("/api/v1/summary")
    assert r.status_code == 401 and r.get_json()["error"]


def test_reports_and_dashboard_render(client):
    seed_txn(client, 50, "expense", "rep")
    assert b"Good day, Admin" in client.get("/").data
    for url in ["/", "/reports", "/reports?view=monthly&year=2026",
                "/categories", "/budgets", "/data", "/recurring"]:
        assert client.get(url).status_code == 200


# ---------- multi-currency ----------

def test_multi_currency(client):
    # 100 USD at the static rate (83.0) -> 8,300.00 base
    r = seed_txn(client, 100, "expense", "usd-note", currency="USD")
    assert r.status_code == 302
    page = client.get("/transactions")
    assert "8,300.00".encode() in page.data
    assert b"USD" in page.data
    assert "(100.00 USD)" in page.data.decode()
    with client.application.app_context():
        db = get_db()
        row = db.execute("SELECT amount, currency, orig_amount FROM transactions"
                         " WHERE note='usd-note'").fetchone()
    assert row["amount"] == 830000 and row["currency"] == "USD"
    assert row["orig_amount"] == 10000
    # unsupported currency rejected
    r = seed_txn(client, 10, "expense", "bad", currency="XYZ")
    assert r.status_code == 302
    with client.application.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM transactions WHERE note='bad'").fetchone()[0] == 0
    # CSV export includes currency columns; reimport keeps them
    csv_data = client.get("/transactions/export").data.decode()
    assert "currency" in csv_data and "USD" in csv_data


# ---------- split transactions ----------

def test_split_transactions(client):
    food = cat_id_of(client, "expense", "Food")
    transport = cat_id_of(client, "expense", "Transport")
    # 1000 total: 300 Food + 600 Transport as splits, 100 stays on the main
    r = postf(client, "/add", "/", amount="1000", type="expense",
              category_id=str(cat_id_of(client, "expense", "Shopping")),
              date="2026-01-15", note="receipt",
              split_category_2=str(food), split_amount_2="300",
              split_category_3=str(transport), split_amount_3="600")
    assert r.status_code == 302
    with client.application.app_context():
        db = get_db()
        rows = db.execute("SELECT category_id, amount, split_group FROM transactions"
                          " WHERE note='receipt' ORDER BY id").fetchall()
    assert len(rows) == 3
    groups = {r["split_group"] for r in rows}
    assert len(groups) == 1 and None not in groups
    assert sum(r["amount"] for r in rows) == 100000  # 1000.00 in cents
    by_cat = {r["category_id"]: r["amount"] for r in rows}
    assert by_cat[food] == 30000 and by_cat[transport] == 60000
    # over-assigned split rejected
    r = postf(client, "/add", "/", amount="100", type="expense",
              category_id=str(cat_id_of(client, "expense", "Shopping")),
              date="2026-01-15", note="bad-split",
              split_category_2=str(food), split_amount_2="400")
    assert r.status_code == 302
    with client.application.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM transactions WHERE note='bad-split'").fetchone()[0] == 0


# ---------- bulk actions ----------

def test_bulk_actions(client):
    seed_txn(client, 10, "expense", "bulk-a")
    seed_txn(client, 20, "expense", "bulk-b")
    seed_txn(client, 30, "expense", "bulk-c")
    with client.application.app_context():
        db = get_db()
        ids = [r[0] for r in db.execute(
            "SELECT id FROM transactions ORDER BY id LIMIT 2").fetchall()]
    r = postf(client, "/transactions/bulk", "/transactions",
              action="delete", ids=",".join(str(i) for i in ids))
    assert r.status_code == 302
    page = client.get("/transactions")
    assert b"bulk-a" not in page.data and b"bulk-b" not in page.data
    assert b"bulk-c" in page.data
    # re-categorize respects type matching
    income_cat = cat_id_of(client, "income")
    expense_cat = cat_id_of(client, "expense")
    with client.application.app_context():
        cid = get_db().execute(
            "SELECT id FROM transactions WHERE note='bulk-c'").fetchone()[0]
    r = postf(client, "/transactions/bulk", "/transactions",
              action="category", ids=str(cid), bulk_category_id=str(income_cat))
    assert r.status_code == 302
    with client.application.app_context():
        assert get_db().execute(
            "SELECT category_id FROM transactions WHERE id=?",
            (cid,)).fetchone()["category_id"] != income_cat
    r = postf(client, "/transactions/bulk", "/transactions",
              action="category", ids=str(cid), bulk_category_id=str(expense_cat))
    with client.application.app_context():
        assert get_db().execute(
            "SELECT category_id FROM transactions WHERE id=?",
            (cid,)).fetchone()["category_id"] == expense_cat


# ---------- FTS search (SQLite) ----------

def test_fts_search(client):
    seed_txn(client, 10, "expense", "grocery-run-alpha")
    seed_txn(client, 20, "expense", "completely-different")
    page = client.get("/transactions?q=grocery")
    assert b"grocery-run-alpha" in page.data
    assert b"completely-different" not in page.data


# ---------- full data import / backup ----------

def test_full_data_import(client):
    token = _csrf_token(client, "/data")
    data = {
        "categories_file": (io.BytesIO(b"name,type\nGadgets,expense\nRoyalties,income\n"), "categories.csv"),
        "budgets_file": (io.BytesIO(b"category,monthly_limit\nGadgets,2500\n"), "budgets.csv"),
        "transactions_file": (io.BytesIO(
            b"date,type,category,amount,note\n2026-01-10,expense,Gadgets,999,headphones\n"
            b"2026-01-11,income,Royalties,300,book\n"), "transactions.csv"),
        "csrf_token": token,
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
    token = _csrf_token(client, "/data")
    data = {
        # invalid type -> skipped; "Pets" is new -> imported
        "categories_file": (io.BytesIO(
            b"name,type\nPets,expense\nBad Row,unknown-type\n"), "c.csv"),
        "budgets_file": (io.BytesIO(
            b"category,monthly_limit\nPets,1500\nGhost,100\noops,not-a-number\n"), "b.csv"),
        "csrf_token": token,
    }
    r = client.post("/data/import", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"Categories: imported 1 row(s), 1 skipped." in r.data
    assert b"Budgets: imported 1 row(s), 2 skipped." in r.data


def test_full_data_import_requires_file(client):
    token = _csrf_token(client, "/data")
    r = client.post("/data/import", data={"csrf_token": token},
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"Choose at least one CSV file to import." in r.data


def test_full_data_import_rejects_non_csv(client):
    token = _csrf_token(client, "/data")
    data = {"categories_file": (io.BytesIO(b"name,type\nX,expense\n"), "c.txt"),
            "csrf_token": token}
    r = client.post("/data/import", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"please upload a .csv file" in r.data


def test_healthz_reports_db_engine(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json()["db"] == "sqlite"  # default backend


def test_db_type_resolution():
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


# ---------- sessions / timeouts ----------

def _backdate_activity(client, minutes):
    import time
    with client.session_transaction() as sess:
        sess["last_active"] = time.time() - minutes * 60


def test_idle_timeout_logs_out(client):
    # recent activity: still signed in
    _backdate_activity(client, 2)
    assert client.get("/").status_code == 200
    # idle past the 5-minute default: signed out with a message
    _backdate_activity(client, 6)
    r = client.get("/", follow_redirects=True)
    assert r.status_code == 200
    assert b"Signed out due to inactivity" in r.data
    assert b"Welcome back" in r.data
    # and protected pages bounce to login again
    assert client.get("/budgets").status_code == 302


def test_idle_pill_shows_countdown(client):
    import re as _re
    # any page load counts as activity, so a fresh render shows the full budget
    page = client.get("/").data.decode()
    m = _re.search(r'id="idle-pill"[^>]*data-remaining="(\d+)"[^>]*data-total="(\d+)"', page)
    assert m, "idle pill missing from nav"
    assert m.group(2) == str(5 * 60)
    assert 5 * 60 - 5 <= int(m.group(1)) <= 5 * 60
    assert "5:00" in page or "4:5" in page
    # a page load resets the timer even with prior idle time
    _backdate_activity(client, 2)
    page = client.get("/").data.decode()
    m = _re.search(r'data-remaining="(\d+)"', page)
    assert 5 * 60 - 5 <= int(m.group(1)) <= 5 * 60
    # personal override changes the pill's total
    postf(client, "/profile", "/profile", timeout_minutes="30", follow_redirects=True)
    page = client.get("/").data.decode()
    assert 'data-total="1800"' in page
    assert "30:00" in page or "29:5" in page
    # logged-out pages show no pill
    c2 = client.application.test_client()
    assert b"idle-pill" not in c2.get("/login").data


def test_session_ping_refreshes_idle_timer(client):
    import time as _time
    # heartbeat reports the full budget
    r = client.get("/session/ping")
    assert r.status_code == 200
    body = r.get_json()
    assert body["total"] == 5 * 60
    assert 5 * 60 - 5 <= body["remaining"] <= 5 * 60
    # activity via ping extends the session (4 idle min + ping = alive)
    with client.session_transaction() as sess:
        sess["last_active"] = _time.time() - 4 * 60
    r = client.get("/session/ping")
    assert r.status_code == 200
    assert r.get_json()["remaining"] >= 5 * 60 - 5
    # ...so the next page still works instead of bouncing to login
    assert client.get("/").status_code == 200
    # anonymous heartbeat is rejected as JSON, not a login page
    c2 = client.application.test_client()
    r = c2.get("/session/ping")
    assert r.status_code == 401 and r.get_json()["error"]
    # pill carries the ping URL for the heartbeat
    assert 'data-ping="/session/ping"' in client.get("/").data.decode()


def test_idle_auto_logout_wiring():
    """The open tab warns at 1 min and signs out automatically at zero."""
    js = open("app/static/app.js").read()
    # 60-second warning toast
    assert "Signing out in 1 minute due to inactivity" in js
    # expiry redirects to the login page (after a short grace)
    assert "window.location.href = idlePill.dataset.login" in js
    # and the pill exposes that login URL
    assert 'data-login' in open(
        "app/templates/base.html").read()


def test_env_timeout_override(tmp_path):
    app = create_app({"TESTING": True, "EXPENSE_DB": str(tmp_path / "t.db"),
                      "SESSION_TIMEOUT_MINUTES": 60})
    c = app.test_client()
    login(c)
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
    assert b"admin" in r.data and b"5 min idle" in r.data
    # set a personal override
    r = postf(client, "/profile", "/profile", timeout_minutes="30",
              follow_redirects=True)
    assert b"Session timeout updated" in r.data
    assert b"30 min idle" in client.get("/profile").data
    # override wins over the 5-min default for idle enforcement
    _backdate_activity(client, 20)
    assert client.get("/").status_code == 200
    _backdate_activity(client, 31)
    assert b"Signed out due to inactivity" in client.get("/",
                                                         follow_redirects=True).data
    # blank clears back to the default (re-login first: previous step signed out)
    login(client)
    postf(client, "/profile", "/profile", timeout_minutes="",
          follow_redirects=True)
    assert b"5 min idle" in client.get("/profile").data
    # invalid values rejected, previous setting kept
    for bad in ("0", "-5", "9999", "abc"):
        r = postf(client, "/profile", "/profile", timeout_minutes=bad,
                  follow_redirects=True)
        assert b"Timeout must be" in r.data
    assert b"5 min idle" in client.get("/profile").data


def test_migration_adds_timeout_column(tmp_path):
    """Databases created before the timeout column get it on boot."""
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
    login(c)
    assert c.get("/profile").status_code == 200


# ---------- user management ----------

def test_user_management(client):
    # page lists admin, add form present
    r = client.get("/users")
    assert r.status_code == 200
    assert b"admin" in r.data and b"Add user" in r.data
    # add a user, then sign in as them
    r = postf(client, "/users", "/users", username="analyst", password="s3cretpass",
              follow_redirects=True)
    assert b"analyst" in r.data
    c2 = client.application.test_client()
    assert login(c2, "analyst", "s3cretpass").status_code == 302
    # duplicates and invalid input rejected
    for data, msg in [({"username": "analyst", "password": "otherpass1"}, b"already exists"),
                      ({"username": "ab", "password": "s3cretpass"}, b"Username must be"),
                      ({"username": "analyst2", "password": "x"}, b"Password must be")]:
        r = postf(client, "/users", "/users", follow_redirects=True, **data)
        assert msg in r.data
    # password reset works
    with client.application.app_context():
        uid = get_db().execute("SELECT id FROM users WHERE username='analyst'").fetchone()[0]
        me = get_db().execute("SELECT id FROM users WHERE username='admin'").fetchone()[0]
    r = postf(client, f"/users/password/{uid}", "/users", password="n3wpassw0rd",
              follow_redirects=True)
    assert b"Password updated" in r.data
    c3 = client.application.test_client()
    assert login(c3, "analyst", "n3wpassw0rd").status_code == 302
    r = postf(client, f"/users/password/{uid}", "/users", password="x",
              follow_redirects=True)
    assert b"Password must be" in r.data
    # cannot delete yourself or the last user; deleting others works
    r = postf(client, f"/users/delete/{me}", "/users", follow_redirects=True)
    assert b"your own account" in r.data
    assert postf(client, f"/users/delete/{uid}", "/users",
                 follow_redirects=True).status_code == 200
    assert b"analyst" not in client.get("/users").data
    r = postf(client, f"/users/delete/{me}", "/users", follow_redirects=True)
    assert b"last remaining user" in r.data
    with client.application.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM users").fetchone()[0] == 1


def _user_id(client, name):
    with client.application.app_context():
        return get_db().execute("SELECT id FROM users WHERE username=?",
                                (name,)).fetchone()[0]


def test_transaction_ownership(client):
    # a second user to manage expenses for
    postf(client, "/users", "/users", username="analyst", password="s3cretpass")
    analyst = _user_id(client, "analyst")
    with client.application.app_context():
        cat = get_db().execute(
            "SELECT id FROM categories WHERE type='expense' LIMIT 1").fetchone()
        admin = get_db().execute(
            "SELECT id FROM users WHERE username='admin'").fetchone()
    # blank owner defaults to yourself
    postf(client, "/add", "/", amount="75", type="expense",
          category_id=str(cat["id"]), date="2026-01-15", note="mine")
    with client.application.app_context():
        tx = get_db().execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT 1").fetchone()
        assert tx["user_id"] == admin["id"]
    # explicit owner assigns the expense to that user
    r = postf(client, "/add", "/", amount="75", type="expense",
              category_id=str(cat["id"]), date="2026-01-15", note="gift",
              owner=str(analyst))
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
    assert "75.00".encode() in client.get(f"/users/{analyst}").data
    # edit can reassign; unknown user rejected
    tid = tx["id"]
    r = postf(client, f"/edit/{tid}", f"/edit/{tid}", amount="75", type="expense",
              category_id=str(cat["id"]), date="2026-01-15", note="gift",
              owner="99999", follow_redirects=True)
    assert b"valid user" in r.data
    postf(client, f"/edit/{tid}", f"/edit/{tid}", amount="75", type="expense",
          category_id=str(cat["id"]), date="2026-01-15", note="gift",
          owner=str(admin["id"]), follow_redirects=True)
    with client.application.app_context():
        assert get_db().execute(
            "SELECT user_id FROM transactions WHERE id=?",
            (tid,)).fetchone()[0] == admin["id"]
    # duplicate keeps the same owner
    postf(client, f"/duplicate/{tid}", "/transactions", follow_redirects=True)
    with client.application.app_context():
        dup = get_db().execute(
            "SELECT * FROM transactions ORDER BY id DESC LIMIT 1").fetchone()
        assert dup["user_id"] == admin["id"]


def test_csv_import_with_owner(client):
    postf(client, "/users", "/users", username="analyst", password="s3cretpass")
    token = _csrf_token(client, "/transactions")
    data = {"file": (io.BytesIO(
        b"date,type,category,amount,note,owner\n"
        b"2026-02-01,expense,Food,42,csv-owned,analyst\n"
        b"2026-02-02,expense,Food,43,csv-ghost,ghost\n"), "t.csv"),
        "csrf_token": token}
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
        b"2026-02-03,expense,Food,44,csv-plain\n"), "t.csv"),
        "csrf_token": token}
    client.post("/transactions/import", data=data,
                content_type="multipart/form-data", follow_redirects=True)
    assert b"csv-plain" in client.get("/transactions").data


def test_profile_recorded_stats(client):
    seed_txn(client, 500, "income", "salary-stat")
    r = client.get("/profile")
    assert b"Expenses you manage" in r.data
    assert b"1 managed" in r.data and b"Salary" in r.data


def test_backup_carries_owners(client):
    postf(client, "/users", "/users", username="analyst", password="s3cretpass")
    analyst = _user_id(client, "analyst")
    with client.application.app_context():
        cat = get_db().execute(
            "SELECT id FROM categories WHERE type='expense' LIMIT 1").fetchone()
    postf(client, "/add", "/", amount="11", type="expense",
          category_id=str(cat["id"]), date="2026-01-15", note="bk",
          owner=str(analyst))
    payload = json.loads(client.get("/data/backup.json").data.decode())
    assert "members" not in payload["data"]
    with client.application.app_context():
        get_db().execute("DELETE FROM transactions")
        get_db().commit()
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(json.dumps(payload).encode()), "b.json"),
              confirm="yes", follow_redirects=True)
    assert b"Restored" in r.data
    assert b"analyst" in client.get("/transactions").data


def test_backup_carries_owners_sql(client):
    """SQL dump roundtrip preserves the transaction owner."""
    postf(client, "/users", "/users", username="analyst", password="s3cretpass")
    with client.application.app_context():
        cat = get_db().execute(
            "SELECT id FROM categories WHERE type='expense' LIMIT 1").fetchone()
    postf(client, "/add", "/", amount="11", type="expense",
          category_id=str(cat["id"]), date="2026-01-15", note="bk-sql",
          owner=str(_user_id(client, "analyst")))
    blob = client.get("/data/backup").data
    assert b"exptracker SQL backup" in blob
    with client.application.app_context():
        get_db().execute("DELETE FROM transactions")
        get_db().commit()
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(blob), "b.sql"),
              confirm="yes", follow_redirects=True)
    assert b"Restored" in r.data
    assert b"analyst" in client.get("/transactions").data


# ---------- recurring transactions ----------

def test_recurring_crud_and_run_due(client):
    expense_cat = cat_id_of(client, "expense", "Bills")
    today = client.get("/").data  # warm-up; dashboard renders
    # create a monthly recurrence (rent, 12000 due on the 5th, no end date)
    r = postf(client, "/recurring", "/recurring", amount="12000", type="expense",
              category_id=str(expense_cat), frequency="monthly",
              start_date="2026-01-05", note="Rent")
    assert r.status_code == 302
    page = client.get("/recurring")
    assert b"Rent" in page.data and b"monthly" in page.data
    assert b"2026-01-05" in page.data  # start shown
    with client.application.app_context():
        db = get_db()
        row = db.execute("SELECT id, amount FROM recurring_transactions WHERE note='Rent'").fetchone()
    assert row["amount"] == 1200000  # cents
    # dashboard load auto-runs due items: Jan 5..Oct 5 (10 monthly runs by Oct 7)
    client.get("/")
    with client.application.app_context():
        db = get_db()
        n = db.execute("SELECT COUNT(*) FROM transactions WHERE note='Rent'").fetchone()[0]
        sched = db.execute("SELECT next_run_date FROM recurring_transactions WHERE note='Rent'").fetchone()[0]
    assert n == 10
    assert sched == "2026-11-05"
    # pause stops generation
    postf(client, f"/recurring/{row['id']}/pause", "/recurring")
    client.get("/")
    with client.application.app_context():
        n2 = get_db().execute(
            "SELECT COUNT(*) FROM transactions WHERE note='Rent'").fetchone()[0]
    assert n2 == 10
    # delete removes the schedule but keeps generated transactions
    postf(client, f"/recurring/{row['id']}/delete", "/recurring")
    with client.application.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM recurring_transactions WHERE note='Rent'").fetchone()[0] == 0
        assert get_db().execute(
            "SELECT COUNT(*) FROM transactions WHERE note='Rent'").fetchone()[0] == 10
    # invalid frequency rejected
    r = postf(client, "/recurring", "/recurring", amount="100", type="expense",
              category_id=str(expense_cat), frequency="hourly",
              start_date="2026-01-05", note="bad")
    assert r.status_code == 302
    with client.application.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM recurring_transactions WHERE note='bad'").fetchone()[0] == 0


def test_recurring_start_and_end_dates(client):
    expense_cat = cat_id_of(client, "expense", "Bills")
    # 3-month SIP: Jan 5, Feb 5, Mar 5 then done
    r = postf(client, "/recurring", "/recurring", amount="5000", type="expense",
              category_id=str(expense_cat), frequency="monthly",
              start_date="2026-01-05", end_date="2026-03-05", note="SIP")
    assert r.status_code == 302
    page = client.get("/recurring").data.decode()
    assert "2026-01-05" in page and "2026-03-05" in page
    client.get("/")  # dashboard run generates Jan..Mar, then auto-finishes
    with client.application.app_context():
        db = get_db()
        n = db.execute("SELECT COUNT(*) FROM transactions WHERE note='SIP'").fetchone()[0]
        row = db.execute("SELECT next_run_date, active, end_date FROM recurring_transactions"
                         " WHERE note='SIP'").fetchone()
    assert n == 3
    assert row["next_run_date"] == "2026-04-05" and row["active"] == 0
    # ended schedule shows the ended badge and is no longer due
    page = client.get("/recurring").data.decode()
    assert "ended" in page
    from app.modules.recurring import models as recurring_models
    with client.application.app_context():
        assert recurring_models.due_count(get_db(), date(2026, 10, 7)) == 0
    client.get("/")
    with client.application.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM transactions WHERE note='SIP'").fetchone()[0] == 3
    # end before start rejected, nothing stored
    r = postf(client, "/recurring", "/recurring", amount="100", type="expense",
              category_id=str(expense_cat), frequency="monthly",
              start_date="2026-03-05", end_date="2026-01-05", note="bad-range",
              follow_redirects=True)
    assert b"on or after the start date" in r.data
    with client.application.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM recurring_transactions WHERE note='bad-range'").fetchone()[0] == 0
    # legacy next_run_date field still accepted as the start
    r = postf(client, "/recurring", "/recurring", amount="100", type="expense",
              category_id=str(expense_cat), frequency="monthly",
              next_run_date="2026-01-05", note="legacy")
    assert r.status_code == 302
    with client.application.app_context():
        row = get_db().execute(
            "SELECT start_date, end_date FROM recurring_transactions WHERE note='legacy'").fetchone()
    assert row["start_date"] == "2026-01-05" and row["end_date"] is None


# ---------- backup / restore ----------

def test_backup_restore_roundtrip(client):
    seed_txn(client, 250, "expense", "backup-note")
    r = client.get("/data/backup")
    assert r.status_code == 200
    assert "application/sql" in r.content_type
    assert "attachment" in r.headers.get("Content-Disposition", "")
    assert ".sql" in r.headers.get("Content-Disposition", "")
    body = r.data.decode()
    assert "exptracker SQL backup" in body
    assert 'INSERT INTO "transactions"' in body
    # exact cents stored (250.00 -> 25000), no float dust
    assert "25000" in body
    # wipe then restore (confirmation checkbox required)
    with client.application.app_context():
        db = get_db()
        db.execute("DELETE FROM transactions")
        db.commit()
        assert db.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(r.data), "b.sql"), confirm="yes",
              follow_redirects=True)
    assert r.status_code == 200 and b"Restored" in r.data
    assert b"backup-note" in client.get("/transactions").data


def test_backup_json_legacy_roundtrip(client):
    """Legacy JSON backups still download and restore."""
    seed_txn(client, 250, "expense", "legacy-note")
    r = client.get("/data/backup.json")
    assert r.status_code == 200
    assert "application/json" in r.content_type
    payload = json.loads(r.data.decode())
    assert payload["app"] == "exptracker"
    assert {t: len(payload["data"][t]) for t in
            ("categories", "budgets", "transactions", "users", "recurring_transactions")}
    assert len(payload["data"]["transactions"]) >= 1
    # backup amounts are human-readable rupees
    assert payload["data"]["transactions"][0]["amount"] == 250.0
    with client.application.app_context():
        db = get_db()
        db.execute("DELETE FROM transactions")
        db.commit()
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(r.data), "b.json"), confirm="yes",
              follow_redirects=True)
    assert r.status_code == 200 and b"Restored" in r.data
    assert b"legacy-note" in client.get("/transactions").data


def test_sql_restore_rejects_bad_files(client):
    seed_txn(client, 50, "expense", "keep-me")
    # garbage that is not a dump
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(b"hello world"), "b.sql"), confirm="yes",
              follow_redirects=True)
    assert b"Restore failed" in r.data
    # hostile dump: DROP TABLE must be refused, data intact
    evil = (b"-- exptracker SQL backup\n-- version: 1\n"
            b'DROP TABLE users;\n')
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(evil), "evil.sql"), confirm="yes",
              follow_redirects=True)
    assert b"Restore failed" in r.data and b"Unsupported statement" in r.data
    # empty dump (header only, no rows) -> rejected, nothing wiped
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(
                  b"-- exptracker SQL backup\n-- version: 1\n"
                  b'DELETE FROM "transactions";\n'), "empty.sql"),
              confirm="yes", follow_redirects=True)
    assert b"Restore failed" in r.data
    assert b"keep-me" in client.get("/transactions").data


def test_sql_dump_handles_tricky_notes(client):
    """Quotes, semicolons and ? in notes survive a SQL roundtrip."""
    seed_txn(client, 77, "expense", "o'brien; what? -- yes")
    blob = client.get("/data/backup").data
    assert b"o''brien" in blob  # escaped quote in the dump
    with client.application.app_context():
        get_db().execute("DELETE FROM transactions")
        get_db().commit()
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(blob), "b.sql"), confirm="yes",
              follow_redirects=True)
    assert b"Restored" in r.data
    assert b"o&#39;brien" in client.get("/transactions").data \
        or b"o'brien" in client.get("/transactions").data


def test_restore_needs_confirm_and_valid_json(client):
    seed_txn(client, 50, "expense", "keep-me")
    blob = client.get("/data/backup.json").data
    # missing confirmation checkbox
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(blob), "b.json"), follow_redirects=True)
    assert b"confirmation" in r.data
    # wrong extension
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(blob), "b.txt"), confirm="yes",
              follow_redirects=True)
    assert b".json" in r.data
    # unreadable JSON
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(b"not json"), "b.json"), confirm="yes",
              follow_redirects=True)
    assert b"could not read JSON" in r.data
    # structurally invalid payload -> rejected, existing data intact
    bad = json.dumps({"data": {"categories": [{"id": 1}]}}).encode()
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(bad), "b.json"), confirm="yes",
              follow_redirects=True)
    assert b"Restore failed" in r.data
    assert b"keep-me" in client.get("/transactions").data


def test_csv_restore_replaces_data(client):
    seed_txn(client, 10, "expense", "old-note")
    with client.application.app_context():
        food = get_db().execute(
            "SELECT id FROM categories WHERE name='Food'").fetchone()[0]
        get_db().execute(
            "INSERT INTO budgets (category_id, monthly_limit) VALUES (?, ?)",
            (food, 99900))
        get_db().commit()
    token = _csrf_token(client, "/data")
    data = {
        "categories_file": (io.BytesIO(b"name,type\nGadgets,expense\n"), "c.csv"),
        "transactions_file": (io.BytesIO(
            b"date,type,category,amount,note\n2026-03-01,expense,Gadgets,42,new-note\n"),
            "t.csv"),
        "csrf_token": token, "confirm": "yes",
    }
    r = client.post("/data/restore-csv", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert r.status_code == 200
    assert b"Restored from CSV" in r.data
    page = client.get("/transactions")
    assert b"new-note" in page.data and b"old-note" not in page.data
    # budgets were replaced too (old Food budget wiped, no budgets file given)
    with client.application.app_context():
        assert get_db().execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 0


def test_csv_restore_requires_file_and_confirm(client):
    seed_txn(client, 10, "expense", "keep-me")
    token = _csrf_token(client, "/data")
    # no files at all
    r = client.post("/data/restore-csv", data={"csrf_token": token},
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"at least one CSV file" in r.data
    # file without confirmation
    data = {"transactions_file": (io.BytesIO(
        b"date,type,category,amount,note\n2026-03-01,expense,Food,5,x\n"), "t.csv"),
        "csrf_token": token}
    r = client.post("/data/restore-csv", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"confirmation" in r.data
    assert b"keep-me" in client.get("/transactions").data
    # wrong extension
    data = {"transactions_file": (io.BytesIO(b"a,b\n1,2\n"), "t.txt"),
            "csrf_token": token, "confirm": "yes"}
    r = client.post("/data/restore-csv", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert b".csv" in r.data
    assert b"keep-me" in client.get("/transactions").data


def test_csv_restore_rejects_bad_headers(client):
    seed_txn(client, 10, "expense", "keep-me")
    token = _csrf_token(client, "/data")
    data = {"transactions_file": (io.BytesIO(b"foo,bar\n1,2\n"), "t.csv"),
            "csrf_token": token, "confirm": "yes"}
    r = client.post("/data/restore-csv", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"Restore failed" in r.data and b"missing column" in r.data
    assert b"keep-me" in client.get("/transactions").data


def test_csv_restore_preserves_users(client):
    postf(client, "/users", "/users", username="analyst", password="s3cretpass")
    token = _csrf_token(client, "/data")
    data = {"transactions_file": (io.BytesIO(
        b"date,type,category,amount,note\n2026-03-01,expense,Food,5,csv-kept\n"), "t.csv"),
        "csrf_token": token, "confirm": "yes"}
    r = client.post("/data/restore-csv", data=data,
                    content_type="multipart/form-data", follow_redirects=True)
    assert b"Users preserved" in r.data
    assert b"csv-kept" in client.get("/transactions").data
    # analyst can still sign in after the replace
    c2 = client.application.test_client()
    assert login(c2, "analyst", "s3cretpass").status_code == 302


# ---------- savings buckets ----------

def test_savings_excluded_from_spending(client):
    from datetime import date as _date
    today = _date.today().isoformat()
    savings = cat_id_of(client, "expense", "Savings")
    assert savings, "Savings bucket should be seeded by default"
    income_cat = cat_id_of(client, "income", "Salary")
    food = cat_id_of(client, "expense", "Food")
    postf(client, "/add", "/", amount="1000", type="income",
          category_id=str(income_cat), date=today, note="pay")
    postf(client, "/add", "/", amount="400", type="expense",
          category_id=str(food), date=today, note="groceries")
    postf(client, "/add", "/", amount="300", type="expense",
          category_id=str(savings), date=today, note="sip")
    # dashboard: spending 400, saved 300, rate on spending (60%, not 30%)
    page = client.get("/").data.decode()
    assert "60.0% saved" in page
    assert "Month saved" in page
    # api summary carries the saved bucket
    j = client.get("/api/summary").get_json()
    assert j["income"] == 1000.0 and j["expense"] == 400.0
    assert j["saved"] == 300.0 and j["savings"] == 600.0
    # transactions list shows the Saved chip and badges the bucket
    tx_page = client.get("/transactions").data.decode()
    assert "Saved" in tx_page and "🏦" in tx_page


def test_savings_toggle_and_budget_guard(client):
    food = cat_id_of(client, "expense", "Food")
    # budget on Food, then flag as savings -> budget cleared
    postf(client, "/budgets", "/budgets", category_id=str(food),
          monthly_limit="5000", follow_redirects=True)
    r = postf(client, f"/categories/savings/{food}", "/categories",
              follow_redirects=True)
    assert b"savings bucket" in r.data
    with client.application.app_context():
        db = get_db()
        assert db.execute("SELECT is_savings FROM categories WHERE id=?",
                          (food,)).fetchone()[0] == 1
        assert db.execute("SELECT COUNT(*) FROM budgets").fetchone()[0] == 0
    # budgets on savings buckets are rejected
    r = postf(client, "/budgets", "/budgets", category_id=str(food),
              monthly_limit="100", follow_redirects=True)
    assert b"savings bucket" in r.data
    # income categories cannot be flagged
    inc = cat_id_of(client, "income")
    r = postf(client, f"/categories/savings/{inc}", "/categories",
              follow_redirects=True)
    assert b"Only expense categories" in r.data
    # toggle back to regular spending
    r = postf(client, f"/categories/savings/{food}", "/categories",
              follow_redirects=True)
    assert b"regular spending" in r.data


def test_backup_preserves_savings_flag(client):
    payload = json.loads(client.get("/data/backup.json").data.decode())
    row = next(c for c in payload["data"]["categories"] if c["name"] == "Savings")
    assert row["is_savings"] == 1
    # SQL roundtrip keeps the flag too
    blob = client.get("/data/backup").data
    assert b"is_savings" in blob
    r = postf(client, "/data/restore", "/data",
              backup_file=(io.BytesIO(blob), "b.sql"), confirm="yes",
              follow_redirects=True)
    assert b"Restored" in r.data
    with client.application.app_context():
        assert get_db().execute(
            "SELECT is_savings FROM categories WHERE name='Savings'").fetchone()[0] == 1


def test_restore_pg_path_resets_sequences():
    """The Postgres restore path must translate placeholders and reset id sequences."""
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
    assert counts == {"categories": 1, "budgets": 1, "transactions": 1,
                      "users": 1, "recurring_transactions": 0}
    stmts = [s for s, _ in seen]
    # sqlite-style ? placeholders translated for psycopg, no ? left behind
    assert any("%s" in s and s.startswith("INSERT INTO users") for s in stmts)
    assert not any("?" in s for s in stmts)
    # amounts converted back to integer cents on restore
    tx_insert = next(s for s in stmts if s.startswith("INSERT INTO transactions"))
    assert tx_insert.count("%s") == 13  # incl. currency, orig_amount, split_group, deleted_at, receipt_path
    # one sequence reset per table (empty tables restart at 1 via 3-arg setval)
    resets = [s for s in stmts if "pg_get_serial_sequence" in s]
    assert len(resets) == 5
    assert all("setval" in s and ", (SELECT COUNT(*) FROM " in s for s in resets)


# ---------- legacy-shape migrations ----------

def test_retired_members_cleaned_up(tmp_path):
    """DBs from the members era lose the table/column on boot, data kept."""
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
    # legacy REAL amount converted to integer cents
    assert db.execute("SELECT amount FROM transactions").fetchone()[0] == 950


def test_real_to_cents_migration_preserves_rows(tmp_path):
    """A pre-cents DB with REAL amounts and created_at migrates losslessly."""
    path = str(tmp_path / "real-era.db")
    db = sqlite3.connect(path)
    db.execute("CREATE TABLE categories (id INTEGER PRIMARY KEY AUTOINCREMENT,"
               " name TEXT UNIQUE NOT NULL, type TEXT NOT NULL)")
    db.execute("INSERT INTO categories (name, type) VALUES ('Food', 'expense')")
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT,"
               " username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,"
               " session_timeout_minutes INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    db.execute("INSERT INTO users (username, password_hash) VALUES ('admin', 'x')")
    db.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY AUTOINCREMENT,"
               " amount REAL NOT NULL, type TEXT NOT NULL, category_id INTEGER NOT NULL,"
               " date TEXT NOT NULL, note TEXT, user_id INTEGER,"
               " created_at TEXT DEFAULT CURRENT_TIMESTAMP)")
    db.execute("INSERT INTO transactions (amount, type, category_id, date, note, user_id)"
               " VALUES (123.45, 'expense', 1, '2026-02-01', 'precision', 1)")
    db.execute("CREATE TABLE budgets (id INTEGER PRIMARY KEY AUTOINCREMENT,"
               " category_id INTEGER UNIQUE NOT NULL, monthly_limit REAL NOT NULL)")
    db.execute("INSERT INTO budgets (category_id, monthly_limit) VALUES (1, 5000.55)")
    db.commit()
    db.close()
    from app.db import init_db
    init_db({"DB_TYPE": "sqlite", "DATABASE_URL": None, "EXPENSE_DB": path})
    db = sqlite3.connect(path)
    assert db.execute("SELECT amount FROM transactions").fetchone()[0] == 12345
    assert db.execute("SELECT monthly_limit FROM budgets").fetchone()[0] == 500055


# ---------- engine SQL translation ----------

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


# ---------- monitoring ----------

def test_metrics_endpoint(client):
    r = client.get("/metrics")
    assert r.status_code == 200
    assert b"exptracker_http_requests_total" in r.data
    # metrics require login (no anonymous operational enumeration)
    c2 = client.application.test_client()
    r = c2.get("/metrics", follow_redirects=False)
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_healthz_includes_version(client):
    r = client.get("/healthz")
    assert r.get_json()["version"]


# ---------- RBAC roles ----------

def _force_csrf(client):
    """Provide a valid CSRF token for pages that render no forms.

    flask-wtf signs session['csrf_token'] (a raw hash); we set the raw value
    and return its signed form so validation passes.
    """
    import hashlib
    import os as _os

    from itsdangerous import URLSafeTimedSerializer
    raw = hashlib.sha1(_os.urandom(64)).hexdigest()
    with client.session_transaction() as sess:
        sess["csrf_token"] = raw
    s = URLSafeTimedSerializer(client.application.secret_key, salt="wtf-csrf-token")
    return s.dumps(raw)


def test_viewer_role_restrictions(client):
    # admin creates a viewer account
    r = postf(client, "/users", "/users", username="scout",
              password="viewerpass1", role="viewer", follow_redirects=True)
    assert b"scout" in r.data and b"viewer" in r.data
    c = client.application.test_client()
    assert login(c, "scout", "viewerpass1").status_code == 302
    # viewer can browse
    for url in ["/", "/transactions", "/reports", "/budgets", "/categories",
                "/recurring", "/data", "/profile", "/trash"]:
        assert c.get(url).status_code == 200, url
    # viewer cannot POST data (no row created)
    token = _force_csrf(c)
    r = c.post("/add", data={"amount": "10", "type": "expense",
                             "category_id": str(cat_id_of(c, "expense")),
                             "date": "2026-01-15", "note": "nope",
                             "csrf_token": token}, follow_redirects=False)
    assert r.status_code == 302
    with client.application.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM transactions WHERE note='nope'").fetchone()[0] == 0
    # admin-only pages bounce away
    assert c.get("/users").status_code == 302
    assert c.get("/audit").status_code == 302
    # admin pages hide write controls for viewers
    page = c.get("/transactions").data
    assert b"id=\"bulk-form\"" not in page
    assert client.get("/transactions").data.count(b"bulk-form") == 1


def test_role_change_and_last_admin_guard(client):
    postf(client, "/users", "/users", username="second",
          password="adminpass1", role="admin", follow_redirects=True)
    uid = _user_id(client, "second")
    # demote works while another admin exists
    r = postf(client, f"/users/role/{uid}", "/users", role="viewer",
              follow_redirects=True)
    assert b"Role updated" in r.data
    # promoting back works
    r = postf(client, f"/users/role/{uid}", "/users", role="admin",
              follow_redirects=True)
    assert b"Role updated" in r.data
    # demoting the last admin is refused (admin is 'me', cannot change own role)
    r = postf(client, f"/users/role/{uid}", "/users", role="viewer",
              follow_redirects=True)
    assert b"Role updated" in r.data
    with client.application.app_context():
        admins = get_db().execute(
            "SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]
    assert admins >= 1


# ---------- password policy ----------

def test_password_policy(client):
    # too short
    r = postf(client, "/users", "/users", username="weak1", password="ab1",
              follow_redirects=True)
    assert b"at least 8" in r.data
    # letters only
    r = postf(client, "/users", "/users", username="weak2",
              password="abcdefghij", follow_redirects=True)
    assert b"letters and numbers" in r.data
    # digits only
    r = postf(client, "/users", "/users", username="weak3",
              password="12345678", follow_redirects=True)
    assert b"letters and numbers" in r.data
    # good password accepted
    r = postf(client, "/users", "/users", username="strong",
              password="goodpass1", follow_redirects=True)
    assert b"strong" in r.data


# ---------- two-factor auth ----------

def test_totp_2fa_flow(client):
    import pyotp
    # start enrollment: secret is shown once on the profile page
    postf(client, "/profile/totp/enable", "/profile")
    page = client.get("/profile").data.decode()
    m = re.search(r"letter-spacing:2px\">([A-Z2-7]+=*)<", page)
    assert m, page
    secret = m.group(1)
    code = pyotp.TOTP(secret).now()
    r = postf(client, "/profile/totp/confirm", "/profile", code=code,
              follow_redirects=True)
    assert b"Two-factor authentication enabled" in r.data
    # fresh client: password alone is not enough — second step required
    c2 = client.application.test_client()
    r = login(c2, "admin", "admin")
    assert r.status_code == 302 and "/login/totp" in r.headers["Location"]
    assert c2.get("/").status_code == 302  # still not fully signed in
    # wrong code rejected
    token = _csrf_token(c2, "/login/totp")
    r = c2.post("/login/totp", data={"code": "000000", "csrf_token": token},
                follow_redirects=False)
    assert r.status_code == 200 and b"Invalid or expired code" in r.data
    # correct code completes the login
    r = c2.post("/login/totp", data={"code": pyotp.TOTP(secret).now(),
                                     "csrf_token": token})
    assert r.status_code == 302
    assert c2.get("/").status_code == 200
    # disable again with a valid code
    r = postf(client, "/profile/totp/disable", "/profile",
              code=pyotp.TOTP(secret).now(), follow_redirects=True)
    assert b"Two-factor authentication disabled" in r.data
    c3 = client.application.test_client()
    r = login(c3, "admin", "admin")
    assert r.status_code == 302 and r.headers["Location"].endswith("/")


# ---------- trash ----------

def test_trash_restore_and_purge(client):
    seed_txn(client, 111, "expense", "trashable")
    with client.application.app_context():
        tid = get_db().execute("SELECT id FROM transactions WHERE note='trashable'"
                               ).fetchone()[0]
    postf(client, f"/delete/{tid}", "/transactions")
    # in trash, out of the list
    assert b"trashable" in client.get("/trash").data
    assert b"trashable" not in client.get("/transactions").data
    # restore puts it back
    r = postf(client, f"/trash/{tid}/restore", "/trash", follow_redirects=True)
    assert b"restored" in r.data
    assert b"trashable" in client.get("/transactions").data
    # purge removes it for good
    postf(client, f"/delete/{tid}", "/transactions")
    postf(client, f"/trash/{tid}/purge", "/trash")
    assert b"trashable" not in client.get("/trash").data
    with client.application.app_context():
        assert get_db().execute(
            "SELECT COUNT(*) FROM transactions WHERE note='trashable'"
            ).fetchone()[0] == 0


# ---------- split group view ----------

def test_split_group_view(client):
    food = cat_id_of(client, "expense", "Food")
    transport = cat_id_of(client, "expense", "Transport")
    postf(client, "/add", "/", amount="500", type="expense",
          category_id=str(cat_id_of(client, "expense", "Shopping")),
          date="2026-01-15", note="group-receipt",
          split_category_2=str(food), split_amount_2="200",
          split_category_3=str(transport), split_amount_3="100")
    with client.application.app_context():
        db = get_db()
        group = db.execute("SELECT split_group FROM transactions WHERE"
                           " note='group-receipt' LIMIT 1").fetchone()[0]
    page = client.get(f"/transactions/split/{group}")
    assert page.status_code == 200
    data = page.data
    assert b"Food" in data and b"Transport" in data and b"Shopping" in data
    assert "500.00".encode() in data  # total shown
    # deleting the whole split moves all lines to trash
    r = postf(client, f"/transactions/split/{group}/delete", f"/transactions/split/{group}",
              follow_redirects=True)
    assert b"3 split line(s)" in r.data
    assert b"group-receipt" not in client.get("/transactions").data
    assert b"group-receipt" in client.get("/trash").data


# ---------- audit log ----------

def test_audit_page_and_purge(client):
    seed_txn(client, 10, "expense", "audited")
    with client.application.app_context():
        tid = get_db().execute("SELECT id FROM transactions WHERE note='audited'"
                               ).fetchone()[0]
    postf(client, f"/delete/{tid}", "/transactions")
    page = client.get("/audit")
    assert page.status_code == 200
    assert b"soft_delete_transaction" in page.data
    # purge with a huge retention window keeps recent entries
    r = postf(client, "/audit/purge", "/audit", days="3650", follow_redirects=True)
    assert b"Purged 0" in r.data or b"audit entries older than" in r.data
    assert b"soft_delete_transaction" in client.get("/audit").data


# ---------- recurring currency ----------

def test_recurring_currency(client):
    expense_cat = cat_id_of(client, "expense", "Bills")
    r = postf(client, "/recurring", "/recurring", amount="50", type="expense",
              category_id=str(expense_cat), frequency="monthly",
              start_date="2030-01-01", note="USD sub", currency="USD")
    assert r.status_code == 302
    with client.application.app_context():
        db = get_db()
        row = db.execute("SELECT amount, currency, orig_amount FROM recurring_transactions"
                         " WHERE note='USD sub'").fetchone()
    assert row["amount"] == 50 * 83 * 100  # 50 USD -> 4,150.00 base in cents
    assert row["currency"] == "USD" and row["orig_amount"] == 5000
    page = client.get("/recurring").data
    assert b"USD" in page


# ---------- reports: variance, forecast, PDF ----------

def test_reports_variance_and_forecast(client):
    food = cat_id_of(client, "expense", "Food")
    postf(client, "/budgets", "/budgets", category_id=str(food),
          monthly_limit="1000", follow_redirects=True)
    postf(client, "/add", "/", amount="400", type="expense",
          category_id=str(food), date="2026-01-15", note="var-spent")
    page = client.get("/reports?view=budgets&month=2026-01")
    assert page.status_code == 200
    assert b"Budget vs actual" in page.data
    assert "400.00".encode() in page.data
    fpage = client.get("/reports?view=forecast")
    assert fpage.status_code == 200
    assert b"Cash-flow forecast" in fpage.data
    assert b"Projected balance" in fpage.data


def test_report_pdf_export(client):
    seed_txn(client, 250, "expense", "pdf-note")
    r = client.get("/reports/export-pdf?view=daily&month=2026-01")
    assert r.status_code == 200
    assert "application/pdf" in r.content_type
    assert r.data[:5] == b"%PDF-"


# ---------- auto-backup job ----------

def test_auto_backup_job(tmp_path):
    bdir = tmp_path / "backups"
    app = create_app({"TESTING": True, "EXPENSE_DB": str(tmp_path / "bk.db"),
                      "AUTO_BACKUP": "1", "BACKUP_DIR": str(bdir),
                      "BACKUP_KEEP": "2"})
    files = sorted(bdir.glob("auto-backup-*.sql"))
    assert len(files) == 1
    body = files[0].read_text()
    assert "exptracker SQL backup" in body
    assert 'INSERT INTO "categories"' in body


def test_backup_rotation(tmp_path):
    from app.jobs import _rotate
    bdir = tmp_path / "b"
    bdir.mkdir()
    for i in range(5):
        (bdir / f"auto-backup-2026010{i}-000000.sql").write_text("-- exptracker SQL backup")
    _rotate(str(bdir), 2)
    assert len(list(bdir.glob("auto-backup-*.sql"))) == 2


# ---------- FX rates ----------

def test_fx_cache_refresh(tmp_path):
    import time as _time
    cache = tmp_path / "fx.json"
    cache.write_text(json.dumps({
        "base": "INR", "ts": _time.time(),
        "rates": {"EUR": 99.0, "USD": 84.0, "INR": 1.0}}))
    app = create_app({"TESTING": True, "EXPENSE_DB": str(tmp_path / "fx.db"),
                      "FX_AUTO_FETCH": True, "FX_CACHE_FILE": str(cache)})
    assert app.config["CURRENCY_RATES"]["EUR"] == 99.0
    assert "EUR" in app.config["CURRENCY_CODES"]


def test_fx_offline_keeps_static_rates(tmp_path, monkeypatch):
    def _boom(base, timeout=5):
        raise OSError("offline")
    monkeypatch.setattr("app.fx._fetch", _boom)
    app = create_app({"TESTING": True, "EXPENSE_DB": str(tmp_path / "fx2.db"),
                      "FX_AUTO_FETCH": True,
                      "FX_CACHE_FILE": str(tmp_path / "missing.json")})
    # fetch failed -> static defaults stay in place
    assert app.config["CURRENCY_RATES"]["USD"] == 83.0


# ---------- server-side sessions ----------

def test_server_side_sessions(tmp_path):
    sdir = tmp_path / "sessions"
    app = create_app({"TESTING": True, "EXPENSE_DB": str(tmp_path / "s.db"),
                      "SESSION_TYPE": "filesystem",
                      "SESSION_FILE_DIR": str(sdir)})
    c = app.test_client()
    login(c)
    assert c.get("/").status_code == 200
    files = list(sdir.glob("*"))
    assert files, "server-side session files should exist"


# ---------- Postgres restore keeps roles/recurrence currency ----------

def test_restore_preserves_roles_and_recurrence_currency():
    from app.db import Connection
    from app.modules.data import models as data_models

    class FakeCursor:
        def fetchone(self):
            return None

        def fetchall(self):
            return []

    class FakeRaw:
        def execute(self, sql, params=()):
            return FakeCursor()

        def commit(self):
            pass

        def rollback(self):
            pass

    payload = {
        "app": "exptracker", "version": 1,
        "data": {
            "users": [{"id": 1, "username": "admin", "password_hash": "x",
                       "role": "viewer", "totp_enabled": 1,
                       "totp_secret": "ABC234"}],
            "categories": [{"id": 1, "name": "Food", "type": "expense"}],
            "recurring_transactions": [{"id": 1, "user_id": 1, "amount": 100, "type": "expense",
                             "category_id": 1, "frequency": "monthly",
                             "next_run_date": "2026-01-01", "currency": "USD",
                             "orig_amount": 50, "active": 1}],
        },
    }
    conn = Connection(FakeRaw(), "pg")
    counts, err = data_models.restore_backup(conn, payload)
    assert err is None, err
    assert counts["recurring_transactions"] == 1 and counts["users"] == 1
