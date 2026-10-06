"""Seed demo data for the Expense Tracker. Run: python3 seed_demo.py"""
import sqlite3
import random
from datetime import date

from app import init_db, DB_PATH

random.seed(42)

EXPENSE_NOTES = {
    "Food": [("Lunch at cafe", 150, 450), ("Groceries", 800, 3500),
             ("Dinner", 300, 1200), ("Snacks", 80, 300)],
    "Transport": [("Metro recharge", 200, 800), ("Petrol", 500, 2000),
                  ("Cab ride", 250, 700), ("Bus pass", 100, 300)],
    "Shopping": [("Clothes", 1200, 5000), ("Electronics", 2000, 15000),
                 ("Shoes", 1500, 4000)],
    "Bills": [("Electricity bill", 800, 2500), ("Internet", 499, 999),
              ("Mobile recharge", 239, 399), ("Rent", 8000, 12000)],
    "Entertainment": [("Movie", 400, 1000), ("Concert", 999, 2500),
                      ("Games", 300, 1500)],
    "Health": [("Pharmacy", 200, 1500), ("Doctor visit", 500, 2000),
               ("Gym", 800, 2000)],
    "Other": [("Gift", 500, 3000), ("Misc", 100, 1000)],
}
INCOME_NOTES = {
    "Salary": [("Monthly salary", 45000, 60000)],
    "Freelance": [("Freelance project", 5000, 20000), ("Side gig", 2000, 8000)],
    "Investment": [("Dividends", 1000, 5000), ("Interest", 500, 2500)],
}


def main(clear=True):
    init_db()
    db = sqlite3.connect(DB_PATH)
    db.execute("PRAGMA foreign_keys = ON")
    if clear:
        db.execute("DELETE FROM transactions")
        db.commit()

    cats = {r[1]: r[0] for r in db.execute("SELECT id, name FROM categories").fetchall()}
    today = date.today()

    # Build list of months: last 6 months including current
    months = []
    y, m = today.year, today.month
    for _ in range(6):
        months.append((y, m))
        m -= 1
        if m == 0:
            m = 12
            y -= 1
    months.reverse()

    count = 0
    for (y, m) in months:
        # monthly income: salary on 1st
        name = "Salary"
        note, lo, hi = random.choice(INCOME_NOTES[name])
        amt = round(random.uniform(lo, hi), 2)
        db.execute(
            "INSERT INTO transactions (amount,type,category_id,date,note) VALUES (?,?,?,?,?)",
            (amt, "income", cats[name], f"{y}-{m:02d}-01", note),
        )
        count += 1
        # freelance 0-2 per month (skip future dates)
        for _ in range(random.randint(0, 2)):
            day = random.randint(2, 28)
            d = date(y, m, day)
            if d > today:
                continue
            note, lo, hi = random.choice(INCOME_NOTES["Freelance"])
            amt = round(random.uniform(lo, hi), 2)
            db.execute(
                "INSERT INTO transactions (amount,type,category_id,date,note) VALUES (?,?,?,?,?)",
                (amt, "income", cats["Freelance"], d.isoformat(), note),
            )
            count += 1
        # occasional investment income
        if random.random() < 0.5:
            day = random.randint(2, 28)
            d = date(y, m, day)
            if d > today:
                pass
            else:
                note, lo, hi = random.choice(INCOME_NOTES["Investment"])
                amt = round(random.uniform(lo, hi), 2)
                db.execute(
                    "INSERT INTO transactions (amount,type,category_id,date,note) VALUES (?,?,?,?,?)",
                    (amt, "income", cats["Investment"], d.isoformat(), note),
                )
                count += 1
        # rent/bills on 5th
        for bcat in ("Bills",):
            note, lo, hi = random.choice(EXPENSE_NOTES[bcat])
            amt = round(random.uniform(lo, hi), 2)
            db.execute(
                "INSERT INTO transactions (amount,type,category_id,date,note) VALUES (?,?,?,?,?)",
                (amt, "expense", cats[bcat], f"{y}-{m:02d}-05", note),
            )
            count += 1
        # random daily expenses: 15-25 per month (skip future dates)
        for _ in range(random.randint(15, 25)):
            day = random.randint(1, 28)
            d = date(y, m, day)
            if d > today:
                continue
            ecat = random.choice(list(EXPENSE_NOTES.keys()))
            note, lo, hi = random.choice(EXPENSE_NOTES[ecat])
            amt = round(random.uniform(lo, hi), 2)
            db.execute(
                "INSERT INTO transactions (amount,type,category_id,date,note) VALUES (?,?,?,?,?)",
                (amt, "expense", cats[ecat], d.isoformat(), note),
            )
            count += 1

    db.commit()
    tot_inc = db.execute("SELECT SUM(amount) FROM transactions WHERE type='income'").fetchone()[0]
    tot_exp = db.execute("SELECT SUM(amount) FROM transactions WHERE type='expense'").fetchone()[0]
    print(f"Inserted {count} demo transactions.")
    print(f"Total income: {tot_inc:.2f} | Total expense: {tot_exp:.2f} | Balance: {tot_inc-tot_exp:.2f}")
    db.close()


if __name__ == "__main__":
    main()
