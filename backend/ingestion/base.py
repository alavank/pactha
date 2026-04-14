"""Utilidades compartilhadas para ingestao de dados governamentais."""
import re
from datetime import datetime, date
from decimal import Decimal, InvalidOperation


def parse_date_br(value) -> date | None:
    """Parse date in DD/MM/YYYY or YYYY-MM-DD format."""
    if not value or str(value).strip() in ("", "nan", "None", "NaT"):
        return None
    s = str(value).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d/%m/%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def parse_decimal_br(value) -> Decimal | None:
    """Parse Brazilian decimal: 1.234.567,89 -> 1234567.89"""
    if value is None or str(value).strip() in ("", "nan", "None"):
        return None
    s = str(value).strip()
    # Remove currency symbols
    s = s.replace("R$", "").strip()
    # Brazilian format: dots as thousands, comma as decimal
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except (InvalidOperation, ValueError):
        return None


def clean_string(value) -> str | None:
    """Clean string value from CSV."""
    if value is None or str(value).strip() in ("", "nan", "None"):
        return None
    return str(value).strip()


def extract_year(dt: date | None) -> int | None:
    """Extract year from date."""
    return dt.year if dt else None
