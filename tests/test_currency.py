"""Currency normalize/detect/convert/label contract (no network)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.data.ingest.currency import (
    normalize_currency, detect_currencies, convert_amounts, currency_label, AMBIGUOUS)


def test_normalize_iso_and_symbols():
    assert normalize_currency("usd") == "USD"
    assert normalize_currency("  AUD ") == "AUD"
    assert normalize_currency("A$") == "AUD"
    assert normalize_currency("US$") == "USD"
    assert normalize_currency("NZ$") == "NZD"
    assert normalize_currency("€") == "EUR"
    assert normalize_currency("$") == AMBIGUOUS
    assert normalize_currency("") is None
    assert normalize_currency(None) is None
    assert normalize_currency("wat") is None
    # Less-common but real ISO codes must still be recognized (not just the majors).
    assert normalize_currency("sgd") == "SGD"
    assert normalize_currency("CHF") == "CHF"


def test_detect_currencies_sorted_distinct():
    df = pd.DataFrame({"cur": ["USD", "usd", "AUD", ""], "x": [1, 2, 3, 4]})
    assert detect_currencies(df, {"order_currency": "cur"}) == ["AUD", "USD"]
    assert detect_currencies(df, {}) == []
    assert detect_currencies(df, {"order_currency": "missing"}) == []


def test_convert_amounts_multiplies_by_rate():
    amounts = pd.Series([10.0, 10.0, 5.0])
    codes = pd.Series(["USD", "AUD", "NZD"])
    rates = {"AUD": 1.0, "USD": 1.5, "NZD": 1.1}
    out = convert_amounts(amounts, codes, rates)
    assert list(out.round(2)) == [15.0, 10.0, 5.5]


def test_convert_amounts_missing_rate_is_nan():
    out = convert_amounts(pd.Series([10.0]), pd.Series(["JPY"]), {"AUD": 1.0})
    assert out.isna().all()


def test_currency_label_symbol_or_code():
    assert currency_label("AUD") == "A$"
    assert currency_label("USD") == "US$"
    assert currency_label("XYZ") == "XYZ"
    assert currency_label(None) == ""


if __name__ == "__main__":
    test_normalize_iso_and_symbols()
    test_detect_currencies_sorted_distinct()
    test_convert_amounts_multiplies_by_rate()
    test_convert_amounts_missing_rate_is_nan()
    test_currency_label_symbol_or_code()
    print("test_currency: OK")
