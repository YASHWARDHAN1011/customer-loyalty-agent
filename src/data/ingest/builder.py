"""
Builder: assemble validated data into canonical tables + a FeatureMatrix.

Runs the validator, then (on success) collapses `orders` to one row per order_id
and hands the canonical tables to Phase 1's `build_feature_matrix`. Returns a plain
dict so the (later) UI layer can render success, warnings, or a clean error list
without catching exceptions.

Collapse rule: per order_id, if all line amounts are identical the value is treated
as a repeated order total (kept once); if the amounts differ they are per-line prices
and are summed to the order total. This handles both order-grained and line-grained
exports without silent revenue under-counting.
"""

from src.data.ingest.validator import validate


def _collapse_amount(s):
    """Per order: identical amounts are a repeated order total (keep one);
    differing amounts are per-line prices (sum to the order total)."""
    return s.iloc[0] if s.nunique(dropna=False) == 1 else s.sum()


def build_canonical(df, mapping) -> dict:
    """Validate + build. Returns {ok, errors, warnings, orders, order_items,
    matrix}; matrix/orders are None when validation fails."""
    result = validate(df, mapping)
    if not result.ok:
        return {"ok": False, "errors": result.errors, "warnings": result.warnings,
                "orders": None, "order_items": None, "matrix": None}

    from src.data.canonical import build_feature_matrix

    # Copy warnings so we never mutate the ValidationResult's list.
    warnings = list(result.warnings)

    amt_per_order = result.orders.groupby("order_id")["order_amount"].nunique()
    summed = int((amt_per_order > 1).sum())
    if summed:
        warnings.append(
            f"{summed} order(s) spanned multiple line amounts and were summed to "
            "an order total. Verify the amount column mapping.")

    orders = (result.orders
              .groupby("order_id", sort=False)
              .agg(customer_id=("customer_id", "first"),
                   order_date=("order_date", "first"),
                   order_amount=("order_amount", _collapse_amount))
              .reset_index())
    orders = orders[["customer_id", "order_id", "order_date", "order_amount"]]
    # build_feature_matrix is exception-safe on validated input (amounts numeric,
    # dates parsed, ids non-null, orders non-empty after dedup).
    matrix = build_feature_matrix(orders, result.order_items)
    return {"ok": True, "errors": [], "warnings": warnings,
            "orders": orders, "order_items": result.order_items, "matrix": matrix}
