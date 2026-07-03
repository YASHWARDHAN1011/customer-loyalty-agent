"""
Validator: the malfunction firewall.

Takes the raw DataFrame + a confirmed column mapping and returns a
`ValidationResult`. On bad data it returns precise, human-readable messages —
never a stack trace. Coercion is deterministic and lives ONLY here: amounts are
stripped of currency symbols/commas and forced numeric (negatives clipped to 0
with a warning), dates are parsed, and rows missing any required field after
coercion are dropped. Pure module.
"""

from dataclasses import dataclass, field

import pandas as pd

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


def _clean_amount(series: pd.Series) -> pd.Series:
    """Strip currency symbols/commas and coerce to float (NaN if empty).

    Accounting-style parenthesised values like "(50.00)" are read as NEGATIVE
    (they denote refunds/credits) rather than being silently turned positive.
    """
    s = series.astype(str).str.strip()
    # (50.00) -> -50.00  before the generic strip, so refunds stay negative.
    accounting = s.str.match(r"^\([\d,.\s]+\)$").fillna(False)
    s = s.where(~accounting, "-" + s.str.strip("()"))
    cleaned = s.str.replace(r"[^0-9.\-]", "", regex=True).replace("", None)
    return pd.to_numeric(cleaned, errors="coerce")


def validate(df: pd.DataFrame, mapping: dict) -> ValidationResult:
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
    dates = pd.to_datetime(raw_dates, errors="coerce")
    bad_dates = dates.isna() & raw_dates.notna() & (raw_dates.astype(str).str.strip() != "")
    if len(df) and bad_dates.mean() > _FAIL_FRACTION:
        errors.append(
            f"{int(bad_dates.sum())} of {len(df)} value(s) "
            f"({bad_dates.mean():.0%}) in the date column "
            f"'{mapping['order_date']}' could not be read as dates.")
    orders["order_date"] = dates

    raw_amt = df[mapping["order_amount"]]
    amt = _clean_amount(raw_amt)
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

    return ValidationResult(True, [], warnings, orders, items)
