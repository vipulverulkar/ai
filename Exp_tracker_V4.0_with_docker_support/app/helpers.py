"""Shared helpers: number formatting, date/month utilities and pagination."""
from datetime import date, datetime

PER_PAGE_CHOICES = (10, 25, 50, 100)

def to_cents(value):
    """Convert decimal amount (string or float) to integer cents."""
    try:
        return int(round(float(str(value).replace(",", "").strip()) * 100))
    except (ValueError, TypeError):
        return 0

def from_cents(cents):
    """Convert integer cents to float rupees."""
    return (cents or 0) / 100.0

def format_inr(value, decimals=2):
    """Format a number Indian-style: 1234567.89 -> '12,34,567.89'."""
    # If the value is likely in cents (passed from a cents-column without conversion)
    # we expect the model to have called from_cents, but we'll be safe.
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


def paginate(total, page_raw=None, per_page_raw=None, default=25):
    """Clamp page/per_page query params for a list with `total` rows.

    Returns (page, per_page, total_pages, offset). Invalid values fall
    back to page 1 and `default` (or 25 when default is invalid).
    """
    try:
        per_page = int(per_page_raw)
    except (ValueError, TypeError):
        per_page = default
    if per_page not in PER_PAGE_CHOICES:
        per_page = default if default in PER_PAGE_CHOICES else 25
    total_pages = max(1, -(-total // per_page))
    try:
        page = int(page_raw)
    except (ValueError, TypeError):
        page = 1
    page = max(1, min(page, total_pages))
    return page, per_page, total_pages, (page - 1) * per_page


def page_window(page, total_pages):
    """Compact page-link list with None gaps: [1, None, 4, 5, 6, None, 20]."""
    out = []
    for p in range(1, total_pages + 1):
        if p == 1 or p == total_pages or abs(p - page) <= 2:
            out.append(p)
        elif out[-1] is not None:
            out.append(None)
    return out
