"""Smoke tests for Expense Tracker v2. Run: python -m pytest -q"""
import csv
import io
import os
import tempfile

import app as app_module


def make_client(tmp_path=None):
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    app_module.DB_PATH = path
    app_module.init_db()
    app_module.app.config["TESTING"] = True
    client = app_module.app.test_client()
    return client, path


def seed_txn(client, amount=100, ttype="expense", note="test"):
    with app_module.app.app_context():
        db = app_module.get_db()
        cat = db.execute("SELECT id FROM categories WHERE type=? LIMIT 1", (ttype,)).fetchone()
        cat_id = cat["id"]
    return client.post("/add", data={
        "amount": str(amount), "type": ttype, "category_id": str(cat_id),
        "date": "2026-01-15", "note": note}, follow_redirects=False)


def test_healthz():
    client, _ = make_client()
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_add_and_list():
    client, _ = make_client()
    r = seed_txn(client, 250, "expense", "groceries")
    assert r.status_code == 302
    r = client.get("/transactions")
    assert r.status_code == 200
    assert b"groceries" in r.data


def test_validation_rejects_bad_amount():
    client, _ = make_client()
    r = seed_txn(client, -5, "expense")
    assert r.status_code == 302  # redirect with flash
    r = client.get("/transactions")
    assert b"No transactions found" in r.data or b"0 total" in r.data


def test_type_mismatch_rejected():
    client, _ = make_client()
    with app_module.app.app_context():
        db = app_module.get_db()
        cat = db.execute("SELECT id FROM categories WHERE type='income' LIMIT 1").fetchone()
    r = client.post("/add", data={"amount": "10", "type": "expense",
                                  "category_id": str(cat["id"]),
                                  "date": "2026-01-15", "note": "x"})
    assert r.status_code == 302


def test_budgets_set_and_show():
    client, _ = make_client()
    with app_module.app.app_context():
        db = app_module.get_db()
        cat = db.execute("SELECT id FROM categories WHERE type='expense' LIMIT 1").fetchone()
    r = client.post("/budgets", data={"category_id": str(cat["id"]),
                                      "monthly_limit": "5000"},
                    follow_redirects=True)
    assert r.status_code == 200
    assert b"5000" in r.data or b"Budget" in r.data


def test_csv_export_import_roundtrip():
    client, _ = make_client()
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


def test_api():
    client, _ = make_client()
    seed_txn(client, 500, "income", "salary-x")
    r = client.get("/api/summary?month=2026-01")
    assert r.status_code == 200
    assert r.get_json()["income"] >= 500
    r = client.get("/api/transactions?limit=5")
    assert r.status_code == 200
    assert isinstance(r.get_json(), list)


def test_reports_and_dashboard_render():
    client, _ = make_client()
    seed_txn(client, 50, "expense", "rep")
    for url in ["/", "/reports", "/reports?view=monthly&year=2026",
                "/categories", "/budgets"]:
        assert client.get(url).status_code == 200
