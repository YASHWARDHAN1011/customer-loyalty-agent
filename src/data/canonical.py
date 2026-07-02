"""
Canonical data model.

Defines the ONE internal shape every analysis/agent/UI surface reads from,
regardless of which store's data was ingested. Two canonical tables:

  orders      : customer_id, order_id, order_date, order_amount  (required)
  order_items : order_id, product, category, quantity            (optional)

From these we build a per-customer FeatureMatrix: a one-row-per-customer frame
plus an `available` map tagging each feature computable / not. RFM-core features
come from `orders` alone; optional extensions require `order_items`. That
availability tag is the mechanism that makes the app "never malfunction" on a
client's partial data — downstream code degrades on the tag, never on a raw
column name.

Pure module: NO Streamlit dependency, so it is unit-testable as a standalone
script and reusable by the offline artifact builder.
"""

from dataclasses import dataclass, field

import pandas as pd

# RFM core — always computable from `orders` alone.
CORE_FEATURES = [
    "recency_days",
    "frequency",
    "monetary",
    "avg_order_value",
    "tenure_days",
    "avg_days_between_orders",
]

# Optional extensions — require `order_items` (and the noted column).
OPTIONAL_FEATURES = [
    "category_diversity",   # needs `category`
    "avg_basket_size",      # needs item lines
    "reorder_rate",         # needs `product`
]


@dataclass
class FeatureMatrix:
    """One row per customer, plus a per-feature availability map.

    `frame` has a `customer_id` column and one column per computed feature.
    `available` maps every feature name in CORE_FEATURES + OPTIONAL_FEATURES to
    a bool. Surfaces call `is_available()` before reading a feature, so they
    never assume a column exists.
    """
    frame: pd.DataFrame
    available: dict = field(default_factory=dict)

    def is_available(self, feature: str) -> bool:
        return bool(self.available.get(feature, False))

    def available_features(self) -> list:
        return [f for f in self.frame.columns
                if f != "customer_id" and self.is_available(f)]


def build_core_features(orders: pd.DataFrame) -> FeatureMatrix:
    """Compute the RFM-core feature matrix from the canonical `orders` table.

    All six CORE_FEATURES are always computable, so all are tagged available.
    Recency/tenure are measured against `as_of` = the latest order_date in the
    dataset (a fixed reference so scores are comparable across customers).
    """
    df = orders.copy()
    df["order_date"] = pd.to_datetime(df["order_date"])
    as_of = df["order_date"].max()

    grp = df.groupby("customer_id")
    last_order = grp["order_date"].max()
    first_order = grp["order_date"].min()

    feats = pd.DataFrame({"customer_id": grp.size().index})
    feats = feats.set_index("customer_id")

    feats["recency_days"] = (as_of - last_order).dt.days
    feats["frequency"] = grp["order_id"].nunique()
    feats["monetary"] = grp["order_amount"].sum()
    feats["avg_order_value"] = (feats["monetary"] / feats["frequency"])
    feats["tenure_days"] = (as_of - first_order).dt.days

    def _mean_gap(dates):
        s = dates.sort_values()
        if len(s) < 2:
            return 0.0
        return float(s.diff().dropna().dt.days.mean())

    feats["avg_days_between_orders"] = grp["order_date"].apply(_mean_gap)

    feats = feats.reset_index()
    feats[CORE_FEATURES] = feats[CORE_FEATURES].fillna(0).round(4)

    available = {f: True for f in CORE_FEATURES}
    available.update({f: False for f in OPTIONAL_FEATURES})
    return FeatureMatrix(frame=feats, available=available)


def build_optional_features(orders: pd.DataFrame,
                            order_items: pd.DataFrame) -> FeatureMatrix:
    """Compute optional extension features from `order_items`.

    Each optional feature is tagged available ONLY when its required column is
    present; an absent column means the feature is neither computed nor tagged
    available. `order_items` is joined to `orders` to attribute lines to a
    customer. `quantity` defaults to 1 per line when absent.
    """
    items = order_items.copy()
    if "quantity" not in items.columns:
        items["quantity"] = 1

    line = items.merge(
        orders[["order_id", "customer_id"]], on="order_id", how="left")

    customers = orders["customer_id"].drop_duplicates()
    feats = pd.DataFrame({"customer_id": customers}).set_index("customer_id")

    available = {f: False for f in OPTIONAL_FEATURES}
    available.update({f: True for f in CORE_FEATURES})

    grp = line.groupby("customer_id")

    if "category" in line.columns:
        feats["category_diversity"] = grp["category"].nunique()
        available["category_diversity"] = True

    lines_per_order = line.groupby(["customer_id", "order_id"]).size()
    feats["avg_basket_size"] = lines_per_order.groupby("customer_id").mean()
    available["avg_basket_size"] = True

    if "product" in line.columns:
        total_lines = grp.size()
        distinct = grp["product"].nunique()
        feats["reorder_rate"] = (1 - (distinct / total_lines))
        available["reorder_rate"] = True

    present = [f for f in OPTIONAL_FEATURES if f in feats.columns]
    feats[present] = feats[present].fillna(0).round(4)
    feats = feats.reset_index()

    return FeatureMatrix(frame=feats, available=available)


def build_feature_matrix(orders: pd.DataFrame,
                         order_items: pd.DataFrame = None) -> FeatureMatrix:
    """Public entry point: assemble the full canonical feature matrix.

    With `orders` alone, returns the RFM-core matrix (optional features tagged
    unavailable). With `order_items` too, merges the optional extensions on and
    tags them per their column availability. Always one row per customer.
    """
    core = build_core_features(orders)
    if order_items is None or len(order_items) == 0:
        return core

    opt = build_optional_features(orders, order_items)
    opt_cols = [c for c in opt.frame.columns if c != "customer_id"]

    merged = core.frame.merge(
        opt.frame[["customer_id"] + opt_cols], on="customer_id", how="left")

    available = dict(core.available)
    available.update({f: opt.available.get(f, False) for f in OPTIONAL_FEATURES})

    present_opt = [c for c in OPTIONAL_FEATURES if c in merged.columns]
    merged[present_opt] = merged[present_opt].fillna(0).round(4)

    return FeatureMatrix(frame=merged, available=available)
