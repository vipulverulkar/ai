"""Bank statement import logic with template mapping.
This module allows users to map their specific bank CSV headers to the app's required fields.
"""
import csv
import io
from datetime import datetime
from flask import current_app

REQUIRED_FIELDS = ["date", "type", "category", "amount"]


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
    """Ensure all required fields are mapped."""
    return all(field in mapping for field in REQUIRED_FIELDS)


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
