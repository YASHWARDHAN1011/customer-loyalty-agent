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

    orders = result.orders.drop_duplicates("order_id").reset_index(drop=True)
    matrix = build_feature_matrix(orders, result.order_items)
    return {"ok": True, "errors": [], "warnings": result.warnings,
            "orders": orders, "order_items": result.order_items, "matrix": matrix}
