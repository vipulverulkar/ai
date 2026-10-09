"""Bank statement import logic with template mapping.
This module allows users to map their specific bank CSV headers to the app's required fields.
"""
import csv
import io
from datetime import datetime
from flask import current_app

REQUIRED_FIELDS = ["date", "type", "category", "amount"]

# Lowercased header aliases used to auto-guess the column mapping when a
# bank CSV is uploaded. First match wins.
HEADER_ALIASES = {
    "date": ("date", "txn date", "transaction date", "value date",
             "posting date", "posted date", "booking date", "txn_date",
             "transaction_date", "valuedate", "tran date"),
    "amount": ("amount", "amt", "value", "transaction amount", "net amount"),
    "debit": ("debit", "dr", "withdrawal", "withdrawals", "paid out",
              "money out", "debits"),
    "credit": ("credit", "cr", "deposit", "deposits", "paid in",
               "money in", "credits"),
    "type": ("type", "dr/cr", "drcr", "debit/credit", "debit credit",
             "transaction type", "txn type", "d/c", "tran type"),
    "category": ("category", "description", "narration", "particulars",
                 "remarks", "merchant", "payee", "details",
                 "transaction description", "transaction details",
                 "transaction remarks", "label"),
    "note": ("note", "notes", "reference", "ref no", "refno", "reference no",
             "utr", "transaction id", "txn id", "cheque", "check"),
}


def get_template(db, name):
    """Fetch a mapping template by name."""
    row = db.execute("SELECT * FROM import_templates WHERE name=?", (name,)).fetchone()
    return row if row else None


def get_template_by_id(db, template_id):
    """Fetch a mapping template by ID."""
    row = db.execute("SELECT * FROM import_templates WHERE id=?", (template_id,)).fetchone()
    return row if row else None


def save_template(db, name, mapping_dict):
    """Save a new mapping template."""
    import json
    db.execute(
        "INSERT INTO import_templates (name, mapping) VALUES (?, ?)",
        (name, json.dumps(mapping_dict))
    )
    db.commit()


def apply_mapping(row, mapping):
    """Map a CSV row based on the provided mapping dictionary."""
    mapped_row = {}
    for target, source in mapping.items():
        mapped_row[target] = row.get(source)
    return mapped_row


def validate_mapping(mapping):
    """Ensure all required fields are mapped.

    Amount may alternatively be given as a debit+credit column pair
    (common in bank statements), in which case no single amount column
    or explicit type column is needed.
    """
    if not mapping:
        return False
    if not all(f in mapping for f in ("date", "category")):
        return False
    if "amount" in mapping:
        return True
    return "debit" in mapping and "credit" in mapping


def guess_mapping(headers):
    """Auto-guess a column mapping from CSV headers.

    Returns {target_field: header_or_None}. Exact (case-insensitive)
    matches are tried before substring matches so e.g. "Transaction
    Date" beats "Value Date" only by alias order.
    """
    norm = {str(h or "").strip().lower(): h for h in (headers or [])}
    guessed = {}
    for target, aliases in HEADER_ALIASES.items():
        found = None
        for alias in aliases:
            if alias in norm:
                found = norm[alias]
                break
        if found is None:
            for alias in aliases:
                for low, orig in norm.items():
                    if alias in low:
                        found = orig
                        break
                if found is not None:
                    break
        guessed[target] = found
    return guessed


def _safe_float(value):
    """float() that returns None for garbage instead of raising."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def combine_debit_credit(row, mapping):
    """Build (amount_raw, type_raw) from a debit/credit column pair.

    Returns (amount_string, 'expense'|'income'|None). An empty/zero side
    means the other side applies; when both sides are empty returns
    (None, None).
    """
    debit_raw = row.get(mapping.get("debit")) if mapping.get("debit") else None
    credit_raw = row.get(mapping.get("credit")) if mapping.get("credit") else None
    debit = normalize_amount(debit_raw)
    credit = normalize_amount(credit_raw)
    debit_f = _safe_float(debit) if debit else None
    credit_f = _safe_float(credit) if credit else None
    has_debit = debit_f is not None and debit_f != 0
    has_credit = credit_f is not None and credit_f != 0
    if has_credit and not has_debit:
        return credit.lstrip('-'), "income"
    if has_debit and not has_credit:
        return debit.lstrip('-'), "expense"
    if not has_debit and not has_credit:
        return None, None
    # Both sides filled (rare) — trust the larger one.
    if abs(credit_f) >= abs(debit_f):
        return credit.lstrip('-'), "income"
    return debit.lstrip('-'), "expense"


def sample_values(rows, headers, limit=3):
    """First `limit` non-empty values per header — shown under mapping dropdowns."""
    samples = {h: [] for h in (headers or [])}
    for row in (rows or []):
        for h in samples:
            if len(samples[h]) >= limit:
                continue
            v = (row.get(h) or "").strip() if isinstance(row.get(h), str) else row.get(h)
            if v not in (None, "") and v not in samples[h]:
                samples[h].append(v)
        if all(len(v) >= limit for v in samples.values()):
            break
    return samples


def detect_csv_encoding(file_bytes):
    """Detect CSV encoding from byte content.
    
    Supports UTF-8, UTF-8-SIG, and falls back to cp1252/ISO-8859-1.
    Returns decoded text string.
    """
    for encoding in ('utf-8-sig', 'utf-8', 'cp1252', 'iso-8859-1'):
        try:
            return file_bytes.decode(encoding)
        except UnicodeDecodeError:
            continue
    # If all fail, force cp1252 with replacement characters
    return file_bytes.decode('cp1252', errors='replace')


def infer_date_format(date_str):
    """Try to parse various date formats and return ISO format YYYY-MM-DD."""
    date_formats = [
        '%Y-%m-%d',       # Standard ISO
        '%d/%m/%Y',       # DD/MM/YYYY (common in India)
        '%m/%d/%Y',       # MM/DD/YYYY (US)
        '%d-%m-%Y',       # DD-MM-YYYY
        '%m-%d-%Y',       # MM-DD-YYYY
        '%Y/%m/%d',       # YYYY/MM/DD
        '%d.%m.%Y',       # DD.MM.YYYY (European)
        '%Y%m%d',         # YYYYMMDD
    ]
    
    if not date_str or not str(date_str).strip():
        return None
        
    date_str = str(date_str).strip()
    
    for fmt in date_formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt.strftime('%Y-%m-%d')
        except ValueError:
            continue
    
    return None


def normalize_amount(amount_raw):
    """Parse amount from various formats (with commas, currency symbols, etc.).
    
    Returns amount as string or None if unparseable.
    """
    if amount_raw is None:
        return None
    
    amount_str = str(amount_raw).strip()
    if not amount_str:
        return None
    
    # Remove common currency symbols and whitespace
    for symbol in ['₹', '$', '€', '£', '¥', 'Rs.', 'Rs', 'INR', 'USD', 'EUR']:
        amount_str = amount_str.replace(symbol, '')
    
    # Remove commas (Indian number format: 1,00,000)
    amount_str = amount_str.replace(',', '')
    
    # Handle parentheses for negative: (100) -> -100
    if amount_str.startswith('(') and amount_str.endswith(')'):
        amount_str = '-' + amount_str[1:-1]
    
    # Remove any remaining non-numeric except minus and decimal point
    cleaned = ''
    for char in amount_str:
        if char.isdigit() or char in '.-':
            cleaned += char
    
    if not cleaned or cleaned == '-' or cleaned == '.':
        return None
    
    return cleaned


def detect_type_from_amount(amount_str, type_value=None):
    """Detect transaction type from amount sign or explicit type value.
    
    Many bank statements use:
    - Separate Dr/Cr columns
    - Negative amounts for debits
    - Or explicit 'Dr'/'Cr' indicators
    
    Returns ('income'|'expense', amount_str_without_sign)
    """
    if type_value:
        type_str = str(type_value).strip().lower()
        if type_str in ('cr', 'credit', 'income', 'deposit', 'received'):
            return 'income', normalize_amount(amount_str)
        elif type_str in ('dr', 'debit', 'expense', 'withdrawal', 'paid'):
            return 'expense', normalize_amount(amount_str)
    
    # Try to detect from amount sign
    cleaned = normalize_amount(amount_str)
    if cleaned and cleaned.startswith('-'):
        # Negative = expense (debit)
        return 'expense', cleaned.lstrip('-')
    
    # Default: assume expense
    return 'expense', cleaned
