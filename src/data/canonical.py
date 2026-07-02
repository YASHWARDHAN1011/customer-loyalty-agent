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
