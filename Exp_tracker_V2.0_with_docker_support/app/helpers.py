"""Shared helpers: number formatting and date/month utilities."""
from datetime import date, datetime


def format_inr(value, decimals=2):
    """Format a number Indian-style: 1234567.89 -> '12,34,567.89'."""
    try:
        v = float(value or 0)
    except (ValueError, TypeError):
        return f"0.{'0' * decimals}"
    neg = v < 0
    v = abs(v)
    s = f"{v:.{decimals}f}"
    if "." in s:
        intpart, dec = s.split(".")
    else:
        intpart, dec = s, ""
    if len(intpart) > 3:
        last3 = intpart[-3:]
        rest = intpart[:-3]
        groups = []
        while len(rest) > 2:
            groups.insert(0, rest[-2:])
            rest = rest[:-2]
        if rest:
            groups.insert(0, rest)
        intpart = ",".join(groups) + "," + last3
    out = f"{intpart}.{dec}" if dec else intpart
    return f"-{out}" if neg else out


def parse_month(month_str):
    """'YYYY-MM' -> (year, month). Defaults to current month."""
    try:
        dt = datetime.strptime(month_str, "%Y-%m")
        return dt.year, dt.month
    except (ValueError, TypeError):
        today = date.today()
        return today.year, today.month


def month_bounds(year, month):
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start.isoformat(), end.isoformat()


def last_n_months(n=6):
    today = date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append((y, m))
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))
