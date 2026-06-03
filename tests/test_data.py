"""
Standalone data check.

Verifies the 5 raw Instacart CSVs are present under data/instacart/ and parse.
Large files are sampled with nrows (proving they're valid CSVs) so the check
stays fast instead of loading ~690MB.

Run from the inner project dir:
  ..\\venv\\Scripts\\python.exe tests/test_data.py
"""

import os
import sys

import pandas as pd

DATA_DIR = 'data/instacart'

# filename -> nrows to read (None = whole file; small files load fully)
FILES = {
    'orders.csv': 1000,
    'order_products__prior.csv': 1000,
    'products.csv': None,
    'departments.csv': None,
    'aisles.csv': None,
}

failures = []

print("=== Checking files exist ===")
for name in FILES:
    path = os.path.join(DATA_DIR, name)
    ok = os.path.exists(path)
    print(f"[{'OK ' if ok else 'MISSING'}] {path}")
    if not ok:
        failures.append(f"missing {path}")

if failures:
    print("\nFAILED: raw data missing — see data/instacart/.")
    sys.exit(1)

print("\n=== Loading and checking data ===")
for name, nrows in FILES.items():
    path = os.path.join(DATA_DIR, name)
    df = pd.read_csv(path, nrows=nrows)
    suffix = f"(first {nrows:,} rows)" if nrows else f"({len(df):,} rows)"
    print(f"\n{name} {suffix}")
    print(f"  Columns: {df.columns.tolist()}")

print("\nALL CHECKS PASSED.")
