# scripts/build_canonical_artifacts.py
"""Precompute canonical demo artifacts so the app boots without reading ~690MB.

Writes, into data/artifacts/canonical/:
  - features.parquet   : the per-customer FeatureMatrix frame (small)
  - availability.json  : the matrix's per-feature availability map
  - orders.parquet     : slim canonical orders (for the sidebar count)

We deliberately do NOT commit the raw order_items table — for Instacart it is
~300MB (over GitHub's limit) and its only committed consumers (the optional
features) are already computed into features.parquet. Item-level surfaces
(happy-path) degrade gracefully where items aren't shipped.

Run: ..\\venv\\Scripts\\python.exe scripts\\build_canonical_artifacts.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.data.demo.instacart import load_demo_canonical
from src.data.app_data import CANON_DIR, CANON_ORDERS, CANON_MATRIX, CANON_AVAIL


def main():
    os.makedirs(CANON_DIR, exist_ok=True)
    orders, _items, matrix = load_demo_canonical()

    matrix.frame.to_parquet(CANON_MATRIX, index=False)
    with open(CANON_AVAIL, "w", encoding="utf-8") as fh:
        json.dump({k: bool(v) for k, v in matrix.available.items()}, fh, indent=2)
    orders.to_parquet(CANON_ORDERS, index=False)

    print(f"Wrote {len(matrix.frame):,} customers -> {CANON_MATRIX}")
    print(f"Wrote availability map -> {CANON_AVAIL}")
    print(f"Wrote {len(orders):,} orders -> {CANON_ORDERS}")


if __name__ == "__main__":
    main()
