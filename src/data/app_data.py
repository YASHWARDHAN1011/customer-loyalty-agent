"""Adapter: canonical FeatureMatrix -> the DataFrame the app already consumes.

The legacy app + agent tools key on `user_id`. Canonical data keys on
`customer_id`. This adapter aliases one to the other so existing consumers keep
working, while exposing the availability map + active levers the re-anchored
scoring/sidebar need. This is the single wiring seam between the canonical layer
and the Streamlit app.
"""

import json
import os

import pandas as pd

from src.data.canonical import build_feature_matrix, FeatureMatrix
from src.data import levers as _levers

CANON_DIR = "data/artifacts/canonical"
CANON_ORDERS = os.path.join(CANON_DIR, "orders.parquet")
# The precomputed per-customer FeatureMatrix (frame + availability). We commit
# this — NOT the raw order_items table (that is ~300MB for Instacart, over
# GitHub's limit and pointless: its only committed consumers are the optional
# features, which are already baked into this matrix). Item-level surfaces
# (happy-path) degrade gracefully on the cloud where items aren't shipped.
CANON_MATRIX = os.path.join(CANON_DIR, "features.parquet")
CANON_AVAIL = os.path.join(CANON_DIR, "availability.json")


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
    return (os.path.exists(CANON_MATRIX)
            and os.path.exists(CANON_AVAIL)
            and os.path.exists(CANON_ORDERS))


def load_demo_app_data():
    """Load the demo canonical data as (orders, order_items, features, available, active).

    Prefers precomputed canonical artifacts (fast boot): the per-customer
    FeatureMatrix (frame + availability) and slim orders. `order_items` is
    returned as None on this path — item-level surfaces (happy-path) degrade
    gracefully. Falls back to reading the raw Instacart CSVs through the demo
    adapter locally, which yields the full item table.
    """
    if canonical_artifacts_exist():
        frame = pd.read_parquet(CANON_MATRIX)
        with open(CANON_AVAIL, "r", encoding="utf-8") as fh:
            available_map = json.load(fh)
        matrix = FeatureMatrix(frame=frame, available=available_map)
        orders = pd.read_parquet(CANON_ORDERS)
        items = None
    else:
        from src.data.demo.instacart import load_demo_canonical
        orders, items, matrix = load_demo_canonical()
    features, available, active = features_from_matrix(matrix)
    return orders, items, features, available, active
