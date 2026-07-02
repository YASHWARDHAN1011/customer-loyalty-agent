"""Standalone tests for src/data/demo/instacart.py. No network, tiny fixtures."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def _orders_raw():
    """Instacart-shaped orders. User 1: 3 prior orders (gaps 0,10,9) + 1 train
    order (must be excluded). User 2: 1 prior order.
    """
    return pd.DataFrame({
        "order_id":   [101, 102, 103, 199, 201],
        "user_id":    [1, 1, 1, 1, 2],
        "eval_set":   ["prior", "prior", "prior", "train", "prior"],
        "order_number": [1, 2, 3, 4, 1],
        "days_since_prior_order": [None, 10.0, 9.0, 5.0, None],
    })


def test_reconstruct_order_dates():
    from src.data.demo.instacart import reconstruct_order_dates, DEMO_ANCHOR_DATE
    out = reconstruct_order_dates(_orders_raw())
    check("order_date column added", "order_date" in out.columns)
    by_order = out.set_index("order_id")["order_date"]
    # user 1 cum gaps: 0, 10, 19 from anchor 2024-01-01
    check("u1 first order == anchor", by_order[101] == DEMO_ANCHOR_DATE)
    check("u1 second order +10d",
          by_order[102] == DEMO_ANCHOR_DATE + pd.Timedelta(days=10))
    check("u1 third order +19d",
          by_order[103] == DEMO_ANCHOR_DATE + pd.Timedelta(days=19))
    check("u2 first order == anchor", by_order[201] == DEMO_ANCHOR_DATE)
    # dates strictly increase with order_number within a user
    u1 = out[out["user_id"] == 1].sort_values("order_number")
    check("u1 dates monotonic increasing",
          u1["order_date"].is_monotonic_increasing)


def _products_raw():
    return pd.DataFrame({
        "product_id":   [1, 2, 3, 4],
        "product_name": ["milk", "eggs", "bread", "soda"],
        "aisle_id":     [10, 10, 20, 30],
        "department_id": [1, 1, 2, 3],
    })


def test_assign_synthetic_prices():
    from src.data.demo.instacart import assign_synthetic_prices
    prices = assign_synthetic_prices(_products_raw())
    check("one price per product", len(prices) == 4)
    check("indexed by product_id", set(prices.index) == {1, 2, 3, 4})
    check("all in [1, 25]", ((prices >= 1.0) & (prices <= 25.0)).all())
    # deterministic: same input -> identical prices
    again = assign_synthetic_prices(_products_raw())
    check("deterministic across calls", (prices == again).all())
    # not all equal (per-product variation, not a flat price)
    check("prices vary across products", prices.nunique() > 1)


def _prior_raw():
    """order_products__prior: order_id, product_id, add_to_cart_order, reordered.
    Order 101: milk(1), eggs(2). 102: milk(1). 103: bread(3). 201: soda(4).
    Train order 199 has NO lines (as in real Instacart prior file).
    """
    return pd.DataFrame({
        "order_id":         [101, 101, 102, 103, 201],
        "product_id":       [1, 2, 1, 3, 4],
        "add_to_cart_order": [1, 2, 1, 1, 1],
        "reordered":        [0, 0, 1, 0, 0],
    })


def test_build_canonical_orders():
    from src.data.demo.instacart import (
        build_canonical_orders, assign_synthetic_prices,
    )
    prices = assign_synthetic_prices(_products_raw())
    orders = build_canonical_orders(_orders_raw(), _prior_raw(), prices)

    check("canonical columns", list(orders.columns) ==
          ["customer_id", "order_id", "order_date", "order_amount"])
    # train order 199 excluded (prior-only)
    check("train order excluded", 199 not in set(orders["order_id"]))
    check("4 prior orders kept", len(orders) == 4)
    check("customer_id renamed from user_id", set(orders["customer_id"]) == {1, 2})
    # order 101 amount == price(milk) + price(eggs)
    expected_101 = round(float(prices[1] + prices[2]), 2)
    amt_101 = float(orders.set_index("order_id").loc[101, "order_amount"])
    check("order 101 amount == sum of its line prices", amt_101 == expected_101)
    check("all amounts positive", (orders["order_amount"] > 0).all())


def _departments_raw():
    return pd.DataFrame({
        "department_id": [1, 2, 3],
        "department":    ["dairy", "bakery", "drinks"],
    })


def test_build_canonical_order_items():
    from src.data.demo.instacart import build_canonical_order_items
    items = build_canonical_order_items(
        _prior_raw(), _products_raw(), _departments_raw())
    check("canonical item columns",
          set(items.columns) == {"order_id", "product", "category", "quantity"})
    check("one row per prior line", len(items) == 5)
    check("quantity all 1", (items["quantity"] == 1).all())
    # product name + department mapped through
    line = items[(items["order_id"] == 101)].set_index("product")
    check("milk mapped to dairy", line.loc["milk", "category"] == "dairy")
    check("eggs mapped to dairy", line.loc["eggs", "category"] == "dairy")
    bread = items[items["product"] == "bread"].iloc[0]
    check("bread mapped to bakery", bread["category"] == "bakery")


def test_to_canonical_and_feature_matrix():
    from src.data.demo.instacart import to_canonical, REVENUE_IS_SYNTHETIC
    from src.data.canonical import (
        build_feature_matrix, CORE_FEATURES, OPTIONAL_FEATURES,
    )
    orders, items = to_canonical(
        _orders_raw(), _prior_raw(), _products_raw(), _departments_raw())

    # items restricted to surviving (prior) orders
    check("no train-order items", 199 not in set(items["order_id"]))
    check("revenue flagged synthetic", REVENUE_IS_SYNTHETIC is True)

    fm = build_feature_matrix(orders, items)
    # demo is the RICH dataset -> Full: everything available
    check("demo == Full (all features available)",
          set(fm.available_features()) == set(CORE_FEATURES + OPTIONAL_FEATURES))
    check("one row per customer", set(fm.frame["customer_id"]) == {1, 2})

    row1 = fm.frame.set_index("customer_id").loc[1]
    # user 1 last order == dataset max -> recency 0
    check("u1 recency 0", row1["recency_days"] == 0)
    # u1 products: milk,eggs,milk,bread -> 4 lines, 3 unique -> reorder 0.25
    check("u1 reorder_rate 0.25", row1["reorder_rate"] == 0.25)
    # u1 categories: dairy, bakery -> 2
    check("u1 category_diversity 2", row1["category_diversity"] == 2)
    # u1 baskets: 2,1,1 lines -> mean 1.3333
    check("u1 avg_basket_size 1.3333",
          round(row1["avg_basket_size"], 4) == 1.3333)
    # monetary > 0 (synthetic) and equals sum of the 3 orders' amounts
    check("u1 monetary positive", row1["monetary"] > 0)


def test_load_demo_canonical_from_csvs(tmp_dir=None):
    import tempfile
    from src.data.demo.instacart import load_demo_canonical
    from src.data.canonical import CORE_FEATURES, OPTIONAL_FEATURES

    d = tmp_dir or tempfile.mkdtemp()
    _orders_raw().to_csv(os.path.join(d, "orders.csv"), index=False)
    _prior_raw().to_csv(os.path.join(d, "order_products__prior.csv"), index=False)
    _products_raw().to_csv(os.path.join(d, "products.csv"), index=False)
    _departments_raw().to_csv(os.path.join(d, "departments.csv"), index=False)

    orders, items, fm = load_demo_canonical(data_dir=d)
    check("loaded canonical orders", list(orders.columns) ==
          ["customer_id", "order_id", "order_date", "order_amount"])
    check("loaded canonical items",
          set(items.columns) == {"order_id", "product", "category", "quantity"})
    check("loaded feature matrix is Full",
          set(fm.available_features()) == set(CORE_FEATURES + OPTIONAL_FEATURES))


def test_reconstruct_dates_all_nan_gaps():
    """A gap column that is entirely NaN must NOT crash (object-dtype cumsum)."""
    from src.data.demo.instacart import reconstruct_order_dates, DEMO_ANCHOR_DATE
    orders = pd.DataFrame({
        "order_id":   [1, 2],
        "user_id":    [1, 2],
        "eval_set":   ["prior", "prior"],
        "order_number": [1, 1],
        "days_since_prior_order": [None, None],
    })
    out = reconstruct_order_dates(orders)
    # every order is a first order -> all land on the anchor
    check("all-NaN gaps -> all dates == anchor",
          (out["order_date"] == DEMO_ANCHOR_DATE).all())


def test_dates_driven_by_sort_not_input_order():
    """Rows shuffled and order_number non-contiguous: dates follow order_number."""
    from src.data.demo.instacart import reconstruct_order_dates, DEMO_ANCHOR_DATE
    orders = pd.DataFrame({
        "order_id":   [30, 10, 70],
        "user_id":    [1, 1, 1],
        "eval_set":   ["prior", "prior", "prior"],
        "order_number": [7, 1, 3],          # out of order, non-contiguous
        "days_since_prior_order": [4.0, None, 6.0],
    })
    by_order = reconstruct_order_dates(orders).set_index("order_id")["order_date"]
    # order_number 1 (order 10) -> anchor; 3 (order 70) -> +6; 7 (order 30) -> +10
    check("first by order_number == anchor", by_order[10] == DEMO_ANCHOR_DATE)
    check("second by order_number +6d",
          by_order[70] == DEMO_ANCHOR_DATE + pd.Timedelta(days=6))
    check("third by order_number +10d",
          by_order[30] == DEMO_ANCHOR_DATE + pd.Timedelta(days=10))


def test_items_no_fanout_on_duplicate_product_id():
    """A duplicated product_id in products must NOT fan out item lines."""
    from src.data.demo.instacart import build_canonical_order_items
    prior = pd.DataFrame({
        "order_id": [1, 1],
        "product_id": [5, 6],
        "add_to_cart_order": [1, 2],
        "reordered": [0, 0],
    })
    products = pd.DataFrame({
        "product_id":   [5, 5, 6],          # 5 duplicated
        "product_name": ["milk", "milk", "eggs"],
        "aisle_id":     [1, 1, 1],
        "department_id": [1, 1, 1],
    })
    departments = pd.DataFrame({"department_id": [1], "department": ["dairy"]})
    items = build_canonical_order_items(prior, products, departments)
    check("dup product_id -> no item fan-out (2 lines stay 2)", len(items) == 2)


def main():
    test_reconstruct_order_dates()
    test_assign_synthetic_prices()
    test_build_canonical_orders()
    test_build_canonical_order_items()
    test_to_canonical_and_feature_matrix()
    test_load_demo_canonical_from_csvs()
    test_reconstruct_dates_all_nan_gaps()
    test_dates_driven_by_sort_not_input_order()
    test_items_no_fanout_on_duplicate_product_id()
    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
