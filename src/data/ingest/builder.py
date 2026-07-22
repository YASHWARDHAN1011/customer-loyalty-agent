"""
Builder: assemble validated data into canonical tables + a FeatureMatrix.

Runs the validator, then (on success) collapses `orders` to one row per order_id
and hands the canonical tables to Phase 1's `build_feature_matrix`. Returns a plain
dict so the (later) UI layer can render success, warnings, or a clean error list
without catching exceptions.

Collapse rule (grain param):
  - grain=None (auto): identical amounts kept once (repeated order total); differing
    amounts summed (per-line prices). Warns when it sums.
  - grain="line_item": always sum all line amounts to an order total, even when
    identical. Use when you know the file is line-grained.
  - grain="order_level": always keep the first amount. Use when you know each row
    is already one order total and repeats are incidental. Warns when amounts differ.

detect_grain(df, mapping) is a pure helper that guesses the grain from the data
before build_canonical is called — useful for the confirm-mapping UI.
"""

import pandas as pd
from src.data.ingest.validator import validate


def _collapse_amount(s):
    """Per order: identical amounts are a repeated order total (keep one);
    differing amounts are per-line prices (sum to the order total)."""
    return s.iloc[0] if s.nunique(dropna=False) == 1 else s.sum()


def detect_grain(df, mapping):
    """Pure: 'line_item' if any order id shows more than one distinct amount,
    else 'order_level'. Safe default 'order_level' when amount/order_id are
    unmapped/absent or on any coercion error (never raises)."""
    amt_col = mapping.get("order_amount")
    oid_col = mapping.get("order_id")
    if not amt_col or not oid_col or amt_col not in df.columns or oid_col not in df.columns:
        return "order_level"
    try:
        from src.data.ingest.validator import _clean_amount
        tmp = pd.DataFrame({"oid": df[oid_col].astype(str),
                            "amt": _clean_amount(df[amt_col])})
        per = tmp.groupby("oid")["amt"].nunique(dropna=True)
        return "line_item" if bool((per > 1).any()) else "order_level"
    except Exception:
        return "order_level"


def build_canonical(df, mapping, dayfirst=None, grain=None,
                    reporting_currency=None, rates=None) -> dict:
    """Validate + build. Returns {ok, errors, warnings, orders, order_items,
    matrix, reporting_currency}; matrix/orders are None when validation fails.

    dayfirst: override date locale (None = auto-detect).
    grain: None = auto / "line_item" = always-sum / "order_level" = keep-first.
    reporting_currency: consolidate all amounts into this currency (None = auto
      from a single detected currency; a multi-currency file then needs `rates`).
    rates: {code: rate-to-reporting-currency} for multi-currency files. Missing
      rates gate the build to a clean error (never a silent wrong number).
    """
    result = validate(df, mapping, dayfirst=dayfirst,
                      reporting_currency=reporting_currency, rates=rates)
    if not result.ok:
        return {"ok": False, "errors": result.errors, "warnings": result.warnings,
                "orders": None, "order_items": None, "matrix": None,
                "reporting_currency": result.reporting_currency}

    from src.data.canonical import build_feature_matrix

    # Copy warnings so we never mutate the ValidationResult's list.
    warnings = list(result.warnings)

    rows_per_order = result.orders.groupby("order_id").size()
    amt_nunique = result.orders.groupby("order_id")["order_amount"].nunique()

    if grain == "line_item":
        amount_agg = "sum"
        n = int((rows_per_order > 1).sum())
        if n:
            warnings.append(
                f"{n} order(s) had their line amounts summed to an order total "
                "(line-item file).")
    elif grain == "order_level":
        amount_agg = "first"
        n = int((amt_nunique > 1).sum())
        if n:
            warnings.append(
                f"{n} order(s) had multiple differing amounts; the first was kept "
                "(order-level file). If this is a line-item export, choose "
                "'Line-item' instead.")
    else:
        amount_agg = _collapse_amount
        n = int((amt_nunique > 1).sum())
        if n:
            warnings.append(
                f"{n} order(s) spanned multiple line amounts and were summed to "
                "an order total. Verify the amount column mapping.")

    orders = (result.orders
              .groupby("order_id", sort=False)
              .agg(customer_id=("customer_id", "first"),
                   order_date=("order_date", "first"),
                   order_amount=("order_amount", amount_agg))
              .reset_index())
    orders = orders[["customer_id", "order_id", "order_date", "order_amount"]]
    # build_feature_matrix is exception-safe on validated input (amounts numeric,
    # dates parsed, ids non-null, orders non-empty after dedup).
    matrix = build_feature_matrix(orders, result.order_items)
    return {"ok": True, "errors": [], "warnings": warnings,
            "orders": orders, "order_items": result.order_items, "matrix": matrix,
            "reporting_currency": result.reporting_currency}
