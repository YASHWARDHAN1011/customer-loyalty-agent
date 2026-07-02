"""
Instacart demo adapter.

Translates the raw Instacart dataset into the canonical `orders` + `order_items`
tables (see src/data/canonical.py) so the built-in demo flows through the SAME
pipe a client upload will. If it works for the demo, the same code works for a
client — Instacart stops being a special case.

Instacart quirks this adapter absorbs:
  - No dates: only `days_since_prior_order` -> reconstruct absolute order_date.
  - No money: assign deterministic SYNTHETIC per-product prices (clearly
    flagged via REVENUE_IS_SYNTHETIC) so Monetary/AOV light up.
  - One row per product-in-order -> quantity is 1 per line.
  - Line items exist only for eval_set == "prior" orders -> demo is prior-only.

Pure module: NO Streamlit dependency; unit-testable on tiny fixtures.
"""

import os

import numpy as np
import pandas as pd

# Synthetic "today" anchor. Recency/tenure are relative to the dataset max, so
# the absolute value is immaterial — it only needs to be a fixed reference.
DEMO_ANCHOR_DATE = pd.Timestamp("2024-01-01")

# The demo's order_amount is fabricated (Instacart has no revenue). Exported so
# the UI can label the demo's money as synthetic.
REVENUE_IS_SYNTHETIC = True


def reconstruct_order_dates(orders_raw: pd.DataFrame,
                            anchor: pd.Timestamp = DEMO_ANCHOR_DATE) -> pd.DataFrame:
    """Add an absolute `order_date` to Instacart orders.

    Per customer, sort by order_number, treat the first order's NaN gap as 0,
    cumulative-sum `days_since_prior_order`, and add the running total (in days)
    to `anchor`. Returns the input frame with an `order_date` column.
    """
    df = orders_raw.copy().sort_values(["user_id", "order_number"])
    gap = pd.to_numeric(df["days_since_prior_order"], errors="coerce").fillna(0.0)
    cum = gap.groupby(df["user_id"]).cumsum()
    df["order_date"] = anchor + pd.to_timedelta(cum, unit="D")
    return df


def assign_synthetic_prices(products_raw: pd.DataFrame,
                            min_price: float = 1.0,
                            max_price: float = 25.0,
                            seed: int = 42) -> pd.Series:
    """Assign a deterministic synthetic unit price to each product.

    Keyed by product_id sorted ascending with a fixed seed, so the same catalog
    always yields the same prices (reproducible demo). Per-product variation
    keeps synthetic revenue from being perfectly collinear with basket size.
    Returns a Series named `unit_price` indexed by product_id.
    """
    pids = products_raw["product_id"].drop_duplicates().sort_values()
    rng = np.random.RandomState(seed)
    prices = rng.uniform(min_price, max_price, size=len(pids)).round(2)
    return pd.Series(prices, index=pids.values, name="unit_price")


def build_canonical_orders(orders_raw: pd.DataFrame,
                           prior_raw: pd.DataFrame,
                           product_prices: pd.Series) -> pd.DataFrame:
    """Build the canonical `orders` table from Instacart (prior orders only).

    order_amount is synthetic: the sum of each order's line unit prices
    (quantity 1 per Instacart line). Orders with no priced lines get 0.0.
    """
    dated = reconstruct_order_dates(orders_raw)
    prior_orders = dated[dated["eval_set"] == "prior"]

    lines = prior_raw.merge(
        product_prices.rename("unit_price"),
        left_on="product_id", right_index=True, how="left")
    amount = (lines.groupby("order_id")["unit_price"].sum()
              .rename("order_amount"))

    out = prior_orders.merge(amount, on="order_id", how="left")
    out = out.rename(columns={"user_id": "customer_id"})
    out["order_amount"] = out["order_amount"].fillna(0.0).round(2)
    return out[["customer_id", "order_id", "order_date", "order_amount"]] \
        .reset_index(drop=True)


def build_canonical_order_items(prior_raw: pd.DataFrame,
                                products_raw: pd.DataFrame,
                                departments_raw: pd.DataFrame) -> pd.DataFrame:
    """Build the canonical `order_items` table from Instacart line items.

    product <- product_name, category <- department, quantity <- 1 (Instacart
    has one row per product-in-order and no quantity column).
    """
    # drop_duplicates guards against a duplicated product_id fanning out item
    # lines (which would inflate basket size / reorder_rate / revenue).
    prod = products_raw.drop_duplicates("product_id").merge(
        departments_raw, on="department_id", how="left")
    lines = prior_raw.merge(
        prod[["product_id", "product_name", "department"]],
        on="product_id", how="left")
    return pd.DataFrame({
        "order_id": lines["order_id"].values,
        "product": lines["product_name"].values,
        "category": lines["department"].values,
        "quantity": 1,
    })


def to_canonical(orders_raw: pd.DataFrame,
                 prior_raw: pd.DataFrame,
                 products_raw: pd.DataFrame,
                 departments_raw: pd.DataFrame):
    """Full Instacart -> canonical translation.

    Returns (orders, order_items) in canonical shape. Items are restricted to
    the prior orders that survived into the canonical `orders` table.
    """
    prices = assign_synthetic_prices(products_raw)
    orders = build_canonical_orders(orders_raw, prior_raw, prices)
    items = build_canonical_order_items(prior_raw, products_raw, departments_raw)
    # .isin on the Series is C-level; the filter only drops orphan lines (it is
    # near-a-no-op on real Instacart data, where prior lines already match).
    items = items[items["order_id"].isin(orders["order_id"])] \
        .reset_index(drop=True)
    return orders, items


def load_demo_canonical(data_dir: str = "data/instacart"):
    """Read the raw Instacart CSVs and return canonical (orders, items, matrix).

    Convenience entry point over `to_canonical` + Phase 1's build_feature_matrix.
    Reads orders.csv, order_products__prior.csv, products.csv, departments.csv
    from `data_dir`. NOTE: on the full dataset this reads ~690MB; the deployed
    app will use precomputed canonical artifacts (a later integration step), not
    this function, at boot.
    """
    from src.data.canonical import build_feature_matrix

    orders_raw = pd.read_csv(os.path.join(data_dir, "orders.csv"))
    prior_raw = pd.read_csv(os.path.join(data_dir, "order_products__prior.csv"))
    products_raw = pd.read_csv(os.path.join(data_dir, "products.csv"))
    departments_raw = pd.read_csv(os.path.join(data_dir, "departments.csv"))

    orders, items = to_canonical(
        orders_raw, prior_raw, products_raw, departments_raw)
    fm = build_feature_matrix(orders, items)
    return orders, items, fm
