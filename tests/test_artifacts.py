"""
Standalone test for the deploy-artifact pipeline (Feature 2).

Run from the inner project dir:
  ..\\venv\\Scripts\\python.exe tests/test_artifacts.py

Verifies that when artifacts have been built, the parquets load with the
expected columns and get_app_data() returns the three DataFrames the app needs.
Skips gracefully (and says so) if artifacts have not been built yet.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
from src.data.loader import (  # noqa: E402
    artifacts_exist,
    get_app_data,
    ARTIFACT_FEATURES,
    ARTIFACT_ORDERS,
    ARTIFACT_HAPPY,
    MAX_LOOKBACK,
)

FEATURE_COLS = {
    'user_id', 'total_orders', 'avg_days_between_orders', 'reorder_rate',
    'dept_diversity', 'avg_basket_size', 'total_items',
}

failures = []


def check(cond, msg):
    mark = "OK " if cond else "FAIL"
    print(f"[{mark}] {msg}")
    if not cond:
        failures.append(msg)


print("=== Artifact pipeline test ===")

if not artifacts_exist():
    print("Artifacts not built yet — run scripts/build_artifacts.py first.")
    print("SKIP (nothing to validate).")
    sys.exit(0)

# --- parquet column checks ---
feat = pd.read_parquet(ARTIFACT_FEATURES)
check(FEATURE_COLS.issubset(feat.columns), f"features.parquet has feature columns ({len(feat):,} users)")

orders = pd.read_parquet(ARTIFACT_ORDERS)
check({'user_id', 'order_number'}.issubset(orders.columns), f"orders_slim.parquet has key columns ({len(orders):,} rows)")

happy = pd.read_parquet(ARTIFACT_HAPPY)
check({'user_id', 'order_number', 'department'}.issubset(happy.columns), "happy_path.parquet has key columns")
check(int(happy['order_number'].max()) <= MAX_LOOKBACK, f"happy_path.parquet only early orders (<= {MAX_LOOKBACK})")

# --- get_app_data contract ---
o, fd, f = get_app_data()
check(isinstance(o, pd.DataFrame) and isinstance(fd, pd.DataFrame) and isinstance(f, pd.DataFrame),
      "get_app_data() returns three DataFrames")
check(FEATURE_COLS.issubset(f.columns), "get_app_data() features have expected columns")
check({'user_id', 'order_number', 'department'}.issubset(fd.columns), "get_app_data() full_data usable by happy-path")

print()
if failures:
    print(f"FAILED ({len(failures)} check(s)).")
    sys.exit(1)
print("ALL CHECKS PASSED.")
