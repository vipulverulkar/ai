"""Shared helpers: number formatting, date/month utilities and pagination."""
from datetime import date, datetime

from .config import PER_PAGE_CHOICES as PER_PAGE_CHOICES
from .config import PER_PAGE_DEFAULT as PER_PAGE_DEFAULT

def to_cents(value):
    """Convert decimal amount (string or float) to integer cents.

    Uses Decimal (ROUND_HALF_UP) so 3rd-decimal inputs convert exactly —
    float would give int(1.005*100) == 100 instead of 101.
    """
    from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
    try:
        return int((Decimal(str(value).replace(",", "").strip()) * 100)
                   .to_integral_value(rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, TypeError, AttributeError):
        return 0

def from_cents(cents):
    """Convert integer cents to float rupees."""
    return (cents or 0) / 100.0


def format_bytes(num_bytes):
    """Human size for upload caps: 2097152 -> '2 MB', 512000 -> '500 KB'."""
    try:
        n = float(num_bytes)
    except (ValueError, TypeError):
        return "?"
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):g} MB"
    return f"{n / 1024:g} KB"


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


def parse_month_strict(month_str):
    """'YYYY-MM' -> (year, month), raising ValueError on anything else.

    Use at request boundaries so ?month=foo / ?month=2026-13 surfaces an
    error instead of silently showing the current month. Note strptime
    accepts '2026-1' (no zero-pad) — normalized callers should reformat
    with f"{y}-{m:02d}".
    """
    if not isinstance(month_str, str) or not month_str:
        raise ValueError(f"Invalid month: {month_str!r} (use YYYY-MM).")
    dt = datetime.strptime(month_str.strip(), "%Y-%m")
    # strptime already rejects month 13+; guard the year range loosely.
    if not 1900 <= dt.year <= 2100:
        raise ValueError(f"Month out of range: {month_str!r}.")
    return dt.year, dt.month


def is_valid_month(month_str):
    """True when month_str is a strict YYYY-MM value."""
    try:
        parse_month_strict(month_str)
        return True
    except (ValueError, TypeError):
        return False


def safe_sheet_value(value):
    """Neutralize spreadsheet formula injection for CSV/XLSX exports.

    Values starting with = + - @ (or tab/CR) become live formulas when a
    CSV/XLSX is opened in Excel/Sheets. Prefixing such values with a single
    quote keeps the visible text identical while forcing plain-text cells.
    Non-strings pass through unchanged.
    """
    if not isinstance(value, str):
        return value
    if value and value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


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


def paginate(total, page_raw=None, per_page_raw=None, default=PER_PAGE_DEFAULT):
    """Clamp page/per_page query params for a list with `total` rows.

    Returns (page, per_page, total_pages, offset). Invalid values fall
    back to page 1 and `default` (or PER_PAGE_DEFAULT when default is invalid).
    """
    try:
        per_page = int(per_page_raw)
    except (ValueError, TypeError):
        per_page = default
    if per_page not in PER_PAGE_CHOICES:
        per_page = default if default in PER_PAGE_CHOICES else PER_PAGE_DEFAULT
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


def canonical_clean_args(query, defaults):
    """Return a cleaned copy of a query mapping with clutter removed.

    Drops keys whose value equals the default in `defaults`, drops empty
    values for keys defaulting to "", and always drops `csrf_token`
    (a GET filter form must never leak the token into the URL/history).
    Unknown keys are preserved unchanged.

    `query` is a Flask MultiDict (e.g. request.args). Returns a plain dict
    of the params worth keeping, or None if nothing would change.
    """
    cleaned = {}
    changed = False
    for key in query.keys():
        # request.args.keys() may repeat; keep first occurrence only.
        if key in cleaned:
            changed = True
            continue
        value = query.get(key, "")
        if key == "csrf_token":
            changed = True
            continue
        if key in defaults:
            default = defaults[key]
            if value == default or (default == "" and value == ""):
                changed = True
                continue
            # Treat explicit page=1 / per_page=default as clutter too.
            if value == str(default):
                changed = True
                continue
        cleaned[key] = value
    # Also flag the case where a default key is simply absent vs present —
    # only redirect when we actually dropped something.
    if not changed:
        return None
    return cleaned
