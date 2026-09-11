"""Seed dummy transactions for demo/testing.

Usage:  python seed_dummy.py [months]
Inserts realistic Income + Expense rows spread over the last N months
(default 6, ending today). Re-running adds MORE rows — delete
expenses.db to start fresh. Stdlib only.
"""
import calendar
import random
import sys
from datetime import date, timedelta

import expense_tracker as app


def month_list(n, end):
    """Last n (year, month) pairs ending at `end` date, oldest first."""
    out, y, m = [], end.year, end.month
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return out[::-1]


def seed(months=6):
    random.seed(42)
    today = date.today()
    count = 0

    def add(d, t, c, a, note=""):
        nonlocal count
        if d > today:  # never seed the future
            return
        app.db_add_txn(d.isoformat(), t, c, round(a, 2), note)
        count += 1

    for y, m in month_list(months, today):
        ndays = calendar.monthrange(y, m)[1]
        last = min(ndays, today.day) if (y, m) == (today.year, today.month) else ndays

        def day(d):
            return date(y, m, min(d, last))

        # ---- income ----
        add(day(1), "Income", "Salary", random.randint(45000, 55000) // 100 * 100, "Monthly salary")
        if random.random() < 0.5:
            add(day(random.randint(5, 25)), "Income", "Freelance",
                random.randint(3000, 15000) // 100 * 100, "Side project")
        if random.random() < 0.3:
            add(day(random.randint(10, 28)), "Income", "Interest",
                random.randint(500, 2500), "Bank interest")

        # ---- fixed expenses ----
        add(day(5), "Expense", "Rent", random.randint(10000, 12000) // 100 * 100, "House rent")
        add(day(15), "Expense", "Utilities",
            random.randint(1500, 3500), random.choice(["Electricity bill", "Water bill", "Internet"]))

        # ---- groceries: weekly ----
        for d in range(3, last + 1, 7):
            add(day(d), "Expense", "Groceries", random.randint(800, 2500), "Weekly groceries")

        # ---- food: few times a week ----
        for d in range(1, last + 1):
            if random.random() < 0.35:
                add(day(d), "Expense", "Food", random.randint(120, 600),
                    random.choice(["Lunch", "Dinner", "Snacks", "Coffee"]))

        # ---- transport: most weekdays ----
        for d in range(1, last + 1):
            try:
                wd = date(y, m, d).weekday()
            except ValueError:
                continue
            if wd < 5 and random.random() < 0.8:
                add(day(d), "Expense", "Transport", random.randint(50, 300),
                    random.choice(["Bus", "Metro", "Auto", "Fuel"]))

        # ---- shopping / entertainment / health / education ----
        for _ in range(random.randint(2, 4)):
            add(day(random.randint(1, last)), "Expense", "Shopping",
                random.randint(500, 5000), random.choice(["Clothes", "Shoes", "Gadgets", "Gifts"]))
        for _ in range(random.randint(1, 3)):
            add(day(random.randint(1, last)), "Expense", "Entertainment",
                random.randint(200, 1500), random.choice(["Movie", "Restaurant", "Games"]))
        if random.random() < 0.6:
            add(day(random.randint(1, last)), "Expense", "Health",
                random.randint(300, 2000), random.choice(["Pharmacy", "Checkup"]))
        if random.random() < 0.4:
            add(day(random.randint(1, last)), "Expense", "Education",
                random.randint(500, 3000), random.choice(["Books", "Course"]))

    return count


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 6
    app.init_db()
    n_rows = seed(n)
    inc, exp, bal = app.db_totals()
    print(f"Inserted {n_rows} dummy transactions ({n} months).")
    print(f"Overall: Income Rs.{inc:,.2f} | Expense Rs.{exp:,.2f} | Balance Rs.{bal:,.2f}")
