"""
Validator: the malfunction firewall.

Takes the raw DataFrame + a confirmed column mapping and returns a
`ValidationResult`. On bad data it returns precise, human-readable messages —
never a stack trace. Coercion is deterministic and lives ONLY here: amounts are
stripped of currency symbols/commas and forced numeric (negatives clipped to 0
with a warning), dates are parsed (day-first vs month-first can be forced via the
`dayfirst` parameter, or is otherwise inferred from the column's evidence; a
warning is emitted when the format is genuinely ambiguous and no override was
given), and rows missing any required field after coercion are dropped. Pure
module.
"""

import re
from dataclasses import dataclass, field

import pandas as pd

# Numeric D/M/Y or M/D/Y with 1-2 digit day and month (ISO YYYY-MM-DD and
# text-month formats are unambiguous and handled by pandas directly).
_AMBIG_DATE = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-]\d{2,4}\s*$")

# A trailing timezone offset ("+1000", "-05:00", "Z"). Real exports (e.g.
# Shopify "Created at": "2025-06-13 08:14:52 +1000") carry one, and an AU file
# spanning a DST switch MIXES offsets (+1000 winter / +1100 summer) — which
# makes pandas raise "Mixed timezones detected" even with errors="coerce".
_TZ_SUFFIX = re.compile(r"\s*(?:Z|[+-]\d{2}:?\d{2})\s*$")


def coerce_datetime(raw: pd.Series, dayfirst: bool = False) -> pd.Series:
    """Parse a column of date strings to tz-naive datetimes, never raising.

    A trailing timezone offset is stripped BEFORE parsing so (a) the order's
    LOCAL calendar day is preserved (what a merchant means by the order date)
    and (b) a column mixing offsets across a DST boundary cannot trip pandas'
    mixed-timezone error. The `utc=True` branch is a belt-and-braces fallback
    for any residual tz-aware content.
    """
    s = raw.astype(str).str.replace(_TZ_SUFFIX, "", regex=True)
    try:
        return pd.to_datetime(s, errors="coerce", dayfirst=dayfirst)
    except (ValueError, TypeError):
        out = pd.to_datetime(s, errors="coerce", dayfirst=dayfirst, utc=True)
        return out.dt.tz_localize(None)


def _infer_dayfirst(raw: pd.Series):
    """Decide day-first vs month-first from evidence in the column.

    Returns (dayfirst: bool, ambiguous: bool). `ambiguous` is True only when
    D/M values are present but none disambiguate (every day and month <= 12),
    in which case we default to day-first and the caller warns.
    """
    saw_ambig = first_gt12 = second_gt12 = False
    # dropna FIRST: under pandas' string dtype, astype(str) keeps NA as NA (a
    # float), not the literal "nan", so a blank cell (e.g. a Shopify
    # continuation row) would otherwise reach the regex as a float and raise.
    for v in raw.dropna().astype(str):
        mtch = _AMBIG_DATE.match(v)
        if not mtch:
            continue
        saw_ambig = True
        a, b = int(mtch.group(1)), int(mtch.group(2))
        if a > 12:
            first_gt12 = True
        if b > 12:
            second_gt12 = True
    if not saw_ambig:
        # No numeric D/M/Y patterns at all (e.g. pure ISO column) — let pandas
        # handle the column with its default (month-first / ISO-aware) parser.
        return False, False
    if first_gt12:
        return True, False
    if second_gt12:
        return False, False
    return True, saw_ambig

REQUIRED = ["customer_id", "order_id", "order_date", "order_amount"]
# Fraction of unparseable values in a required column that flips a warning into
# a hard rejection.
_FAIL_FRACTION = 0.1


@dataclass
class ValidationResult:
    ok: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    orders: pd.DataFrame = None       # canonical orders when ok
    order_items: pd.DataFrame = None  # canonical items when optional cols mapped
    reporting_currency: str = None    # resolved reporting currency (label/metadata)


def _clean_amount(series: pd.Series) -> pd.Series:
    """Strip currency symbols/commas and coerce to float (NaN if empty).

    Accounting-style parenthesised values like "(50.00)" are read as NEGATIVE
    (they denote refunds/credits) rather than being silently turned positive.
    """
    s = series.astype(str).str.strip()
    # Any parenthesised value containing a digit is accounting-negative
    # notation (refund/credit): "(50.00)", "($25.00)", "(1,200)". Rewrite to a
    # leading minus BEFORE the generic strip so it stays negative.
    accounting = s.str.match(r"^\(.*\d.*\)$").fillna(False)
    s = s.where(~accounting, "-" + s.str.replace(r"[()]", "", regex=True))
    cleaned = s.str.replace(r"[^0-9.\-]", "", regex=True).replace("", None)
    return pd.to_numeric(cleaned, errors="coerce")


def validate(df: pd.DataFrame, mapping: dict, dayfirst=None, reporting_currency=None, rates=None) -> ValidationResult:
    errors, warnings = [], []

    missing = [f for f in REQUIRED if not mapping.get(f)]
    if missing:
        errors.append(
            "These required fields are not mapped to a column: "
            + ", ".join(missing) + ". Map them on the confirm screen and retry.")
        return ValidationResult(False, errors, warnings)

    mapped_cols = [mapping[f] for f in REQUIRED]
    mapped_cols += [mapping[f] for f in ("product", "category", "quantity")
                    if mapping.get(f)]
    absent = sorted({c for c in mapped_cols if c not in df.columns})
    if absent:
        errors.append(
            "These mapped columns are not in the uploaded file: "
            + ", ".join(absent) + ". Re-check the column mapping.")
        return ValidationResult(False, errors, warnings)

    if len(df) == 0:
        return ValidationResult(
            False, ["The uploaded file has no data rows."], warnings)

    orders = pd.DataFrame({
        "customer_id": df[mapping["customer_id"]].astype(str).str.strip(),
        "order_id": df[mapping["order_id"]].astype(str).str.strip(),
    })

    raw_dates = df[mapping["order_date"]]
    if dayfirst is None:
        resolved, ambiguous = _infer_dayfirst(raw_dates)
    else:
        resolved, ambiguous = dayfirst, False
    dates = coerce_datetime(raw_dates, dayfirst=resolved)
    if ambiguous:
        warnings.append(
            f"Dates in column '{mapping['order_date']}' use an ambiguous "
            f"D/M/Y format (all values <= 12) and were read as day-first "
            f"(DD/MM/YYYY). Verify the date column if your data is US-style "
            f"(MM/DD/YYYY).")
    bad_dates = dates.isna() & raw_dates.notna() & (raw_dates.astype(str).str.strip() != "")
    if len(df) and bad_dates.mean() > _FAIL_FRACTION:
        errors.append(
            f"{int(bad_dates.sum())} of {len(df)} value(s) "
            f"({bad_dates.mean():.0%}) in the date column "
            f"'{mapping['order_date']}' could not be read as dates.")
    orders["order_date"] = dates

    raw_amt = df[mapping["order_amount"]]
    amt = _clean_amount(raw_amt)

    # --- Currency consolidation. Active ONLY when a currency column is mapped;
    # single-currency and no-column files are byte-for-byte unchanged. Conversion
    # happens here (all amount coercion lives in the validator) so every check
    # below sees final reporting-currency amounts. ---
    resolved_currency = reporting_currency
    curr_col = mapping.get("order_currency")
    if curr_col and curr_col in df.columns:
        from src.data.ingest.currency import (
            detect_currencies, convert_amounts, normalize_currency, AMBIGUOUS)
        detected = detect_currencies(df, mapping)
        if len(detected) == 1:
            only = detected[0]
            # A single-currency file normally needs no conversion. But an override
            # reporting currency that DIFFERS from the file's actual currency (e.g. a
            # saved multi-currency recipe replayed on a file that now holds one
            # foreign currency) must still convert — otherwise amounts stay in the
            # source currency but get LABELLED as the reporting one (silent wrong
            # number). Gate on a missing rate exactly like the multi-currency path.
            if reporting_currency and reporting_currency != only and only != AMBIGUOUS:
                rate_map = dict(rates or {})
                rate_map.setdefault(reporting_currency, 1.0)
                if not rate_map.get(only):
                    errors.append(
                        f"This file is in {only} but the reporting currency is "
                        f"{reporting_currency}. Enter a {only}->{reporting_currency} "
                        f"conversion rate before analysis can run.")
                    return ValidationResult(False, errors, warnings)
                amt = convert_amounts(amt, df[curr_col].map(normalize_currency),
                                      rate_map)
                resolved_currency = reporting_currency
            else:
                resolved_currency = reporting_currency or only
        elif len(detected) > 1:
            codes = df[curr_col].map(normalize_currency)
            # Never let the ambiguous "$?" sentinel become the base currency —
            # doing so would give it a 1.0 rate and keep those rows instead of
            # dropping them (a silent-wrong-number path). There is always >=1
            # non-ambiguous code here since len(detected) > 1.
            base = reporting_currency or str(
                codes[codes != AMBIGUOUS].value_counts().idxmax())
            rate_map = dict(rates or {})
            rate_map.setdefault(base, 1.0)
            required = [c for c in detected if c != AMBIGUOUS]
            unrated = [c for c in required if not rate_map.get(c)]
            if rates is None or unrated:
                errors.append(
                    f"This file contains {len(detected)} currencies "
                    f"({', '.join(detected)}). Enter a conversion rate for each "
                    f"(relative to {base}) on the confirm screen before analysis "
                    f"can run.")
                return ValidationResult(False, errors, warnings)
            if AMBIGUOUS in detected and not rate_map.get(AMBIGUOUS):
                n_amb = int((codes == AMBIGUOUS).sum())
                warnings.append(
                    f"{n_amb} order(s) use an ambiguous '$' currency with no rate "
                    f"and were dropped. Assign a rate to '$?' to include them.")
            amt = convert_amounts(amt, codes, rate_map)
            resolved_currency = base

    bad_amt = amt.isna() & raw_amt.notna() & (raw_amt.astype(str).str.strip() != "")
    if len(df) and bad_amt.mean() > _FAIL_FRACTION:
        errors.append(
            f"{int(bad_amt.sum())} of {len(df)} value(s) "
            f"({bad_amt.mean():.0%}) in the amount column "
            f"'{mapping['order_amount']}' are not numeric.")
    negatives = (amt < 0)
    if negatives.any():
        warnings.append(
            f"{int(negatives.sum())} negative amount(s) were clipped to 0 "
            f"(likely returns/refunds).")
        amt = amt.clip(lower=0)
    orders["order_amount"] = amt

    # Comma-as-decimal (e.g. "1.234,56") parses to a ~1000x-wrong number and does
    # NOT trip the numeric check. We don't guess the locale — we warn so the
    # operator can verify on the confirm screen.
    comma_decimal = (raw_amt.astype(str).str.strip()
                     .str.match(r"^-?[\d.]*\d,\d{1,2}$").fillna(False))
    if comma_decimal.any():
        warnings.append(
            f"{int(comma_decimal.sum())} amount(s) look like they use a comma as "
            f"the decimal separator (e.g. '1.234,56') and may be misread. Check "
            f"the amount column '{mapping['order_amount']}'.")

    orders["customer_id"] = orders["customer_id"].replace("", None)
    orders["order_id"] = orders["order_id"].replace("", None)

    if errors:
        return ValidationResult(False, errors, warnings)

    orders = orders.dropna(subset=REQUIRED).reset_index(drop=True)
    if len(orders) == 0:
        return ValidationResult(
            False,
            ["No rows survived validation — every row was missing a required "
             "customer, order, date, or amount value."],
            warnings)

    items = None
    if mapping.get("product") or mapping.get("category"):
        items = pd.DataFrame({"order_id": df[mapping["order_id"]].astype(str).str.strip()})
        if mapping.get("product"):
            items["product"] = df[mapping["product"]]
        if mapping.get("category"):
            items["category"] = df[mapping["category"]]
        if mapping.get("quantity"):
            items["quantity"] = _clean_amount(df[mapping["quantity"]]).fillna(1)
        else:
            items["quantity"] = 1
        items = items[items["order_id"].isin(orders["order_id"])].reset_index(drop=True)

    return ValidationResult(True, [], warnings, orders, items,
                            reporting_currency=resolved_currency)
