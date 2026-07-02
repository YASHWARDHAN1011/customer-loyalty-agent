"""Standalone tests for src/data/canonical.py — the trust contract. No network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.data.canonical import (
    CORE_FEATURES, OPTIONAL_FEATURES, FeatureMatrix,
)

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def test_feature_matrix_container():
    frame = pd.DataFrame({"customer_id": [1, 2], "recency_days": [3, 9]})
    fm = FeatureMatrix(frame=frame, available={"recency_days": True,
                                               "category_diversity": False})
    check("frame round-trips", list(fm.frame["customer_id"]) == [1, 2])
    check("is_available true", fm.is_available("recency_days") is True)
    check("is_available false", fm.is_available("category_diversity") is False)
    check("unknown feature is unavailable",
          fm.is_available("does_not_exist") is False)
    check("available_features lists only available",
          fm.available_features() == ["recency_days"])
    check("core constant shape", CORE_FEATURES[0] == "recency_days"
          and len(CORE_FEATURES) == 6)
    check("optional constant shape", set(OPTIONAL_FEATURES) ==
          {"category_diversity", "avg_basket_size", "reorder_rate"})


def _orders_fixture():
    """Two customers, hand-computable. as_of (max date) = 2024-01-20.
    Customer 1: 3 orders on Jan 1, Jan 11, Jan 20; amounts 10, 20, 30.
    Customer 2: 1 order on Jan 10; amount 100.
    """
    return pd.DataFrame({
        "customer_id": [1, 1, 1, 2],
        "order_id":    [101, 102, 103, 201],
        "order_date":  pd.to_datetime(
            ["2024-01-01", "2024-01-11", "2024-01-20", "2024-01-10"]),
        "order_amount": [10.0, 20.0, 30.0, 100.0],
    })


def test_core_features():
    from src.data.canonical import build_core_features
    fm = build_core_features(_orders_fixture())
    row1 = fm.frame.set_index("customer_id").loc[1]
    row2 = fm.frame.set_index("customer_id").loc[2]

    check("recency c1", row1["recency_days"] == 0)
    check("recency c2", row2["recency_days"] == 10)
    check("frequency c1", row1["frequency"] == 3)
    check("frequency c2", row2["frequency"] == 1)
    check("monetary c1", row1["monetary"] == 60.0)
    check("monetary c2", row2["monetary"] == 100.0)
    check("aov c1", row1["avg_order_value"] == 20.0)
    check("aov c2", row2["avg_order_value"] == 100.0)
    check("tenure c1", row1["tenure_days"] == 19)
    check("tenure c2", row2["tenure_days"] == 10)
    check("gap c1", row1["avg_days_between_orders"] == 9.5)
    check("gap c2 single order -> 0", row2["avg_days_between_orders"] == 0.0)

    check("core all available", all(fm.is_available(f) for f in CORE_FEATURES))
    check("optional all unavailable",
          all(not fm.is_available(f) for f in OPTIONAL_FEATURES))


def _items_fixture():
    """order_items for the orders fixture. Customer 1 (orders 101/102/103),
    Customer 2 (order 201). Two categories for c1; c1 reorders 'milk'.
    """
    return pd.DataFrame({
        "order_id": [101, 101, 102, 103, 201],
        "product":  ["milk", "eggs", "milk", "bread", "soda"],
        "category": ["dairy", "dairy", "dairy", "bakery", "drinks"],
        "quantity": [1, 2, 1, 1, 3],
    })


def test_optional_features_full():
    from src.data.canonical import build_optional_features
    fm = build_optional_features(_orders_fixture(), _items_fixture())
    row1 = fm.frame.set_index("customer_id").loc[1]
    row2 = fm.frame.set_index("customer_id").loc[2]

    check("category_diversity c1", row1["category_diversity"] == 2)
    check("category_diversity c2", row2["category_diversity"] == 1)
    check("avg_basket_size c1", round(row1["avg_basket_size"], 4) == 1.3333)
    check("avg_basket_size c2", row2["avg_basket_size"] == 1.0)
    check("reorder_rate c1", row1["reorder_rate"] == 0.25)
    check("reorder_rate c2 no repeats", row2["reorder_rate"] == 0.0)

    check("optional all available",
          all(fm.is_available(f) for f in OPTIONAL_FEATURES))


def test_optional_features_partial_columns():
    """order_items with no `category` -> category_diversity unavailable, others OK."""
    from src.data.canonical import build_optional_features
    items = _items_fixture().drop(columns=["category"])
    fm = build_optional_features(_orders_fixture(), items)
    check("category_diversity unavailable when no category column",
          fm.is_available("category_diversity") is False)
    check("category_diversity column absent from frame",
          "category_diversity" not in fm.frame.columns)
    check("avg_basket_size still available",
          fm.is_available("avg_basket_size") is True)
    check("reorder_rate still available",
          fm.is_available("reorder_rate") is True)


def main():
    test_feature_matrix_container()
    test_core_features()
    test_optional_features_full()
    test_optional_features_partial_columns()
    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
