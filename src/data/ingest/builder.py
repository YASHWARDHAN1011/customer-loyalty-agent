"""
Builder: assemble validated data into canonical tables + a FeatureMatrix.

Runs the validator, then (on success) de-duplicates `orders` on order_id and
hands the canonical tables to Phase 1's `build_feature_matrix`. Returns a plain
dict so the (later) UI layer can render success, warnings, or a clean error list
without catching exceptions.

Assumption: the uploaded file is order-grained for `orders` — a logical order may
appear on several line rows, so `order_amount` is read as an order TOTAL repeated
across those rows (kept once via drop_duplicates), NOT summed per line. Line-level
detail flows into `order_items` when product/category columns are mapped.
"""

from src.data.ingest.validator import validate


def build_canonical(df, mapping) -> dict:
    """Validate + build. Returns {ok, errors, warnings, orders, order_items,
    matrix}; matrix/orders are None when validation fails."""
    result = validate(df, mapping)
    if not result.ok:
        return {"ok": False, "errors": result.errors, "warnings": result.warnings,
                "orders": None, "order_items": None, "matrix": None}

    from src.data.canonical import build_feature_matrix

    # Detect a likely line-grained file (same order_id with more than one
    # distinct amount) before dedup, so a silent revenue under-count surfaces
    # as a warning the operator can act on. Copy warnings so we never mutate
    # the ValidationResult's list.
    warnings = list(result.warnings)
    amt_per_order = result.orders.groupby("order_id")["order_amount"].nunique()
    ambiguous = int((amt_per_order > 1).sum())
    if ambiguous:
        warnings.append(
            f"{ambiguous} order id(s) appear with more than one distinct amount. "
            "This file may be line-grained (amount per line, not per order); the "
            "first amount per order id is used, so revenue totals may be off. "
            "Verify the amount column mapping.")

    orders = result.orders.drop_duplicates("order_id").reset_index(drop=True)
    # build_feature_matrix is exception-safe on validated input (amounts numeric,
    # dates parsed, ids non-null, orders non-empty after dedup).
    matrix = build_feature_matrix(orders, result.order_items)
    return {"ok": True, "errors": [], "warnings": warnings,
            "orders": orders, "order_items": result.order_items, "matrix": matrix}
