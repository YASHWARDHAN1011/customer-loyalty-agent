"""Adapter: canonical FeatureMatrix -> the DataFrame the app already consumes.

The legacy app + agent tools key on `user_id`. Canonical data keys on
`customer_id`. This adapter aliases one to the other so existing consumers keep
working, while exposing the availability map + active levers the re-anchored
scoring/sidebar need. This is the single wiring seam between the canonical layer
and the Streamlit app.
"""

import os

import pandas as pd

from src.data.canonical import build_feature_matrix
from src.data import levers as _levers

CANON_DIR = "data/artifacts/canonical"
CANON_ORDERS = os.path.join(CANON_DIR, "orders.parquet")
CANON_ITEMS = os.path.join(CANON_DIR, "order_items.parquet")


def features_from_matrix(matrix):
    """Return (features_df, available_map, active_levers) from a FeatureMatrix.

    `features_df` has both `customer_id` and a `user_id` alias so legacy
    consumers work unchanged.
    """
    features = matrix.frame.copy()
    if "customer_id" in features.columns and "user_id" not in features.columns:
        features["user_id"] = features["customer_id"]
    active = _levers.active_levers(matrix)
    return features, dict(matrix.available), active


def canonical_artifacts_exist():
    return os.path.exists(CANON_ORDERS) and os.path.exists(CANON_ITEMS)


def load_demo_app_data():
    """Load the demo canonical data as (orders, order_items, features, available, active).

    Prefers precomputed canonical parquet artifacts (fast boot); falls back to
    reading the raw Instacart CSVs through the demo adapter.
    """
    if canonical_artifacts_exist():
        orders = pd.read_parquet(CANON_ORDERS)
        items = pd.read_parquet(CANON_ITEMS)
        matrix = build_feature_matrix(orders, items)
    else:
        from src.data.demo.instacart import load_demo_canonical
        orders, items, matrix = load_demo_canonical()
    features, available, active = features_from_matrix(matrix)
    return orders, items, features, available, active
