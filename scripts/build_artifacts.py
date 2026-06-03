"""
Build deploy artifacts.

Reads the ~690MB raw Instacart CSVs (must be present under data/instacart/)
and writes three small parquet files to data/artifacts/ that the deployed app
loads instead of the raw data:

  features.parquet     one row per user, 6 behavioral features
  orders_slim.parquet  orders reduced to the columns the app reads
  happy_path.parquet   early-order line items (user_id, order_number, department)

Run once locally from the inner project dir, then commit data/artifacts/:

  ..\\venv\\Scripts\\python.exe scripts/build_artifacts.py
"""

import os
import sys

# Make `src` importable when run as `python scripts/build_artifacts.py`.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.loader import (  # noqa: E402
    _merge_raw,
    _compute_features,
    ARTIFACT_DIR,
    ARTIFACT_FEATURES,
    ARTIFACT_ORDERS,
    ARTIFACT_HAPPY,
    MAX_LOOKBACK,
)


def _mb(path):
    return os.path.getsize(path) / (1024 * 1024)


def main():
    os.makedirs(ARTIFACT_DIR, exist_ok=True)

    print("Loading raw CSVs (this reads ~690MB, takes a minute)...")
    orders, full_data = _merge_raw()
    print(f"  orders: {len(orders):,} rows | full_data: {len(full_data):,} rows")

    print("Computing features...")
    features = _compute_features(orders, full_data)
    features.to_parquet(ARTIFACT_FEATURES, index=False)
    print(f"  -> {ARTIFACT_FEATURES} ({_mb(ARTIFACT_FEATURES):.1f} MB, {len(features):,} users)")

    print("Writing slim orders...")
    orders_slim = orders[['user_id', 'order_number', 'days_since_prior_order']]
    orders_slim.to_parquet(ARTIFACT_ORDERS, index=False)
    print(f"  -> {ARTIFACT_ORDERS} ({_mb(ARTIFACT_ORDERS):.1f} MB, {len(orders_slim):,} rows)")

    print(f"Writing happy-path early orders (order_number <= {MAX_LOOKBACK})...")
    happy = full_data[full_data['order_number'] <= MAX_LOOKBACK][
        ['user_id', 'order_number', 'department']
    ].copy()
    happy['department'] = happy['department'].astype('category')
    happy.to_parquet(ARTIFACT_HAPPY, index=False)
    print(f"  -> {ARTIFACT_HAPPY} ({_mb(ARTIFACT_HAPPY):.1f} MB, {len(happy):,} rows)")

    total = _mb(ARTIFACT_FEATURES) + _mb(ARTIFACT_ORDERS) + _mb(ARTIFACT_HAPPY)
    print(f"\nDone. Total artifact size: {total:.1f} MB")
    if total > 95:
        print("WARNING: artifacts approaching GitHub's 100MB/file limit; consider filtering further.")


if __name__ == '__main__':
    main()
