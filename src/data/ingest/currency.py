"""
Currency normalization + conversion for the ingest firewall.

Pure module (no Streamlit, no network). Turns a raw currency column into
canonical uppercase ISO codes, detects which currencies a file contains, and
applies operator-supplied FLAT conversion rates to fold every order amount into a
single reporting currency. Rate provenance is the caller's concern — this module
applies whatever {code: rate} dict it is handed (base currency = 1.0).
"""

import pandas as pd

# Unambiguous symbol -> ISO code. A bare "$" is shared by USD/AUD/NZD/CAD and is
# NOT here; it normalizes to the ambiguous sentinel so the UI can surface it.
_SYMBOL_TO_CODE = {
    "US$": "USD", "A$": "AUD", "AU$": "AUD", "NZ$": "NZD",
    "C$": "CAD", "CA$": "CAD", "€": "EUR", "£": "GBP", "¥": "JPY",
}
AMBIGUOUS = "$?"

# Code -> display symbol for labeling. Falls back to the raw code.
_CODE_TO_SYMBOL = {
    "USD": "US$", "AUD": "A$", "NZD": "NZ$", "CAD": "C$",
    "EUR": "€", "GBP": "£", "JPY": "¥",
}

# Valid ISO 4217 currency codes (whitelist for the normalized check).
_VALID_CODES = {
    "USD", "AUD", "NZD", "CAD", "EUR", "GBP", "JPY",
}


def normalize_currency(raw):
    """One raw cell -> canonical uppercase ISO code, the '$?' sentinel, or None.

    - 3-letter alpha tokens that are valid ISO codes ('usd' -> 'USD').
    - Known multi-char symbols map via _SYMBOL_TO_CODE ('A$' -> 'AUD').
    - A bare '$' is ambiguous -> '$?'.
    - Blank / unrecognized -> None.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    up = s.upper()
    if up.isalpha() and len(up) == 3 and up in _VALID_CODES:
        return up
    if s in _SYMBOL_TO_CODE:
        return _SYMBOL_TO_CODE[s]
    if up in _SYMBOL_TO_CODE:
        return _SYMBOL_TO_CODE[up]
    if s == "$":
        return AMBIGUOUS
    return None


def detect_currencies(df, mapping):
    """Sorted distinct normalized currencies in the mapped currency column.
    Empty list if unmapped/absent. Never raises."""
    col = mapping.get("order_currency")
    if not col or col not in df.columns:
        return []
    try:
        codes = df[col].map(normalize_currency).dropna()
        return sorted(set(codes.tolist()))
    except Exception:
        return []


def convert_amounts(amounts, currencies, rates):
    """`amounts` (numeric Series) times each row's rate, looked up from the row's
    normalized `currencies` code in `rates` ({code: rate}, base=1.0). A currency
    absent from `rates` yields NaN (an unconvertible row the validator treats as a
    bad amount)."""
    factors = currencies.map(rates)
    return (pd.to_numeric(amounts, errors="coerce")
            * pd.to_numeric(factors, errors="coerce"))


def currency_label(code):
    """Display symbol for a code ('AUD' -> 'A$'); falls back to the raw code.
    Empty string for a falsy code."""
    if not code:
        return ""
    return _CODE_TO_SYMBOL.get(str(code).upper(), str(code))
