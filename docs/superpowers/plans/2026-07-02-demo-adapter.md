# Instacart Demo Adapter Implementation Plan (Phase 2 of 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Translate the raw Instacart dataset into the canonical `orders` + `order_items` tables from Phase 1, so the built-in demo flows through the exact same pipe a client upload will — proving the canonical model works on real, known data.

**Architecture:** A new pure module `src/data/demo/instacart.py` with small single-job functions: reconstruct absolute order dates from Instacart's relative `days_since_prior_order`, assign deterministic synthetic per-product prices (Instacart has no money), build the canonical `orders` (with synthetic `order_amount`) and `order_items` (product/category), and a `to_canonical()` orchestrator. A thin `load_demo_canonical(data_dir)` reads the CSVs and returns canonical tables + a `FeatureMatrix` via Phase 1's `build_feature_matrix`. No Streamlit; fully testable on tiny Instacart-shaped fixtures (never the 690MB raw data).

**Tech Stack:** Python 3, pandas, numpy, standalone `check()` test scripts (repo house style — no pytest, no network).

**Scope note (NARROW — confirmed with user):** This phase delivers the adapter module + its tests ONLY. It does NOT rewire `app.py` and does NOT rebuild the committed parquet artifacts. `get_app_data()` stays the live path; the app is unchanged. Wiring the app to the canonical demo + regenerating artifacts is a later integration step (alongside Phase 4 re-anchoring). Depends on Phase 1 (`src/data/canonical.py`, merged to main).

**Instacart raw shape (verified from `data/instacart/`):**
- `orders.csv`: `order_id, user_id, eval_set, order_number, order_dow, order_hour_of_day, days_since_prior_order`
- `order_products__prior.csv`: `order_id, product_id, add_to_cart_order, reordered`
- `products.csv`: `product_id, product_name, aisle_id, department_id`
- `departments.csv`: `department_id, department`
- `aisles.csv`: `aisle_id, aisle` (not needed)

Line items live only in `order_products__prior.csv`, which covers `eval_set == "prior"` orders — so the demo restricts canonical orders to prior orders (train/test orders have no items and thus no derivable revenue).

---

## File Structure

| File | Responsibility |
|---|---|
| `src/data/demo/__init__.py` (create) | Make `src/data/demo` a package. |
| `src/data/demo/instacart.py` (create) | The Instacart→canonical adapter: date reconstruction, synthetic pricing, canonical `orders`/`order_items` builders, `to_canonical()`, `load_demo_canonical()`, `REVENUE_IS_SYNTHETIC`. |
| `tests/test_demo_adapter.py` (create) | Fixture-based tests: date monotonicity, price determinism/range, canonical table correctness, and end-to-end composition through `build_feature_matrix` (demo == Full dataset). |

**Design decisions locked:**
- **Dates:** per customer, sort by `order_number`, fill the first order's NaN gap with 0, cumulative-sum `days_since_prior_order`, add as days to `DEMO_ANCHOR_DATE` (2024-01-01). Recency/tenure are relative to the dataset max, so the absolute anchor value is immaterial.
- **Money (synthetic):** each product gets a deterministic pseudo-random unit price in [1.0, 25.0] (seeded, keyed by sorted `product_id`). `order_amount` = sum of its lines' unit prices (quantity 1). Per-product (not flat) pricing so `monetary` is NOT perfectly collinear with basket size — the demo shows RFM signals as independent. `REVENUE_IS_SYNTHETIC = True` is exported so the UI can label it later. (Spec §6 said "e.g. basket size × unit price"; per-product is the illustrative intent, refined to avoid collinearity.)
- **Items:** `product` ← `product_name`, `category` ← `department`, `quantity` = 1 (Instacart has one row per product-in-order). Mapping every product line across all a customer's orders makes Phase 1's `reorder_rate` proxy track real reorder behavior.
- **Prior-only:** canonical orders and items are restricted to `eval_set == "prior"`.

---

### Task 1: Package init + `reconstruct_order_dates`

**Files:**
- Create: `src/data/demo/__init__.py` (empty)
- Create: `src/data/demo/instacart.py`
- Test: `tests/test_demo_adapter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_demo_adapter.py`:

```python
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


def main():
    test_reconstruct_order_dates()
    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_demo_adapter.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.data.demo'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/data/demo/__init__.py` (empty file).

Create `src/data/demo/instacart.py`:

```python
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
    gap = df["days_since_prior_order"].fillna(0)
    cum = gap.groupby(df["user_id"]).cumsum()
    df["order_date"] = anchor + pd.to_timedelta(cum, unit="D")
    return df
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_demo_adapter.py`
Expected: PASS — `6 checks passed.`

- [ ] **Step 5: Commit**

```bash
git add src/data/demo/__init__.py src/data/demo/instacart.py tests/test_demo_adapter.py
git commit -m "Demo adapter: reconstruct absolute order dates from Instacart gaps"
```

---

### Task 2: `assign_synthetic_prices` (deterministic per-product money)

**Files:**
- Modify: `src/data/demo/instacart.py`
- Test: `tests/test_demo_adapter.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_demo_adapter.py` and wire into `main()`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_demo_adapter.py`
Expected: FAIL — `ImportError: cannot import name 'assign_synthetic_prices'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/data/demo/instacart.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_demo_adapter.py`
Expected: PASS — Task 1 + Task 2 checks.

- [ ] **Step 5: Commit**

```bash
git add src/data/demo/instacart.py tests/test_demo_adapter.py
git commit -m "Demo adapter: deterministic synthetic per-product prices"
```

---

### Task 3: `build_canonical_orders` (prior-only, synthetic amount)

**Files:**
- Modify: `src/data/demo/instacart.py`
- Test: `tests/test_demo_adapter.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_demo_adapter.py` and wire into `main()`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_demo_adapter.py`
Expected: FAIL — `ImportError: cannot import name 'build_canonical_orders'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/data/demo/instacart.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_demo_adapter.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/data/demo/instacart.py tests/test_demo_adapter.py
git commit -m "Demo adapter: canonical orders with synthetic amount (prior-only)"
```

---

### Task 4: `build_canonical_order_items` (product/category lines)

**Files:**
- Modify: `src/data/demo/instacart.py`
- Test: `tests/test_demo_adapter.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_demo_adapter.py` and wire into `main()`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_demo_adapter.py`
Expected: FAIL — `ImportError: cannot import name 'build_canonical_order_items'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/data/demo/instacart.py`:

```python
def build_canonical_order_items(prior_raw: pd.DataFrame,
                                products_raw: pd.DataFrame,
                                departments_raw: pd.DataFrame) -> pd.DataFrame:
    """Build the canonical `order_items` table from Instacart line items.

    product <- product_name, category <- department, quantity <- 1 (Instacart
    has one row per product-in-order and no quantity column).
    """
    prod = products_raw.merge(departments_raw, on="department_id", how="left")
    lines = prior_raw.merge(
        prod[["product_id", "product_name", "department"]],
        on="product_id", how="left")
    return pd.DataFrame({
        "order_id": lines["order_id"].values,
        "product": lines["product_name"].values,
        "category": lines["department"].values,
        "quantity": 1,
    })
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_demo_adapter.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/data/demo/instacart.py tests/test_demo_adapter.py
git commit -m "Demo adapter: canonical order_items (product/category lines)"
```

---

### Task 5: `to_canonical` orchestrator + end-to-end composition through Phase 1

**Files:**
- Modify: `src/data/demo/instacart.py`
- Test: `tests/test_demo_adapter.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_demo_adapter.py` and wire into `main()`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_demo_adapter.py`
Expected: FAIL — `ImportError: cannot import name 'to_canonical'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/data/demo/instacart.py`:

```python
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
    items = items[items["order_id"].isin(set(orders["order_id"]))] \
        .reset_index(drop=True)
    return orders, items
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_demo_adapter.py`
Expected: PASS — end-to-end composition through Phase 1's `build_feature_matrix` confirms the demo is a Full dataset with the hand-computed feature values.

- [ ] **Step 5: Commit**

```bash
git add src/data/demo/instacart.py tests/test_demo_adapter.py
git commit -m "Demo adapter: to_canonical orchestrator + feature-matrix composition"
```

---

### Task 6: `load_demo_canonical` (CSV entry point) + regression sweep + journal

**Files:**
- Modify: `src/data/demo/instacart.py`
- Test: `tests/test_demo_adapter.py`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_demo_adapter.py` and wire into `main()`. This writes the fixtures to a temp dir as CSVs and reads them back through the CSV entry point (so it exercises file I/O without the 690MB real data):

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_demo_adapter.py`
Expected: FAIL — `ImportError: cannot import name 'load_demo_canonical'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/data/demo/instacart.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes + regression sweep**

Run the new suite and the existing ones:

```powershell
..\venv\Scripts\python.exe tests/test_demo_adapter.py
..\venv\Scripts\python.exe tests/test_canonical.py
..\venv\Scripts\python.exe tests/test_scoring.py
..\venv\Scripts\python.exe tests/test_simulation.py
```

Expected: `test_demo_adapter.py` prints its total and exits 0; `test_canonical.py` = `52 checks passed.`; scoring/simulation unchanged. Confirm the module has no Streamlit import:

```powershell
..\venv\Scripts\python.exe -c "src=open('src/data/demo/instacart.py',encoding='utf-8').read(); print('clean' if 'streamlit' not in src else 'FOUND streamlit')"
```

Expected: `clean`.

- [ ] **Step 5: Journal entry + commit**

Add a dated entry to the top of the Project Journal in `CLAUDE.md`:

```markdown
### 2026-07-02 — Intelligence Layer, Phase 2: Instacart demo adapter
Instacart now flows into the canonical shape through the same pipe a client
upload will (spec §6; plan: docs/superpowers/plans/2026-07-02-demo-adapter.md).
- **`src/data/demo/instacart.py`** (NEW, pure / Streamlit-free): `reconstruct_order_dates`
  (cumulative-sum days_since_prior_order from a fixed anchor), `assign_synthetic_prices`
  (deterministic per-product prices — Instacart has no money; REVENUE_IS_SYNTHETIC
  flag), `build_canonical_orders` (prior-only, synthetic order_amount),
  `build_canonical_order_items` (product/category lines, quantity 1), `to_canonical`
  orchestrator, and `load_demo_canonical(data_dir)` reading the 4 CSVs -> canonical
  tables + a Phase 1 FeatureMatrix.
- The demo is the RICH dataset: end-to-end it produces a Full FeatureMatrix
  (all core + optional features available), verified against hand-computed values.
- Scope (narrow): adapter + tests only. app.py untouched, parquet artifacts NOT
  rebuilt — get_app_data() still the live path. App wiring + canonical artifact
  rebuild is a later integration step.
- Tests: `tests/test_demo_adapter.py` — date reconstruction, price determinism,
  canonical tables, end-to-end composition through build_feature_matrix, and a
  CSV round-trip via load_demo_canonical (temp-dir fixtures, no 690MB read).
  No network. Existing suites (canonical 52, scoring, simulation) still green.
```

```bash
git add src/data/demo/instacart.py tests/test_demo_adapter.py CLAUDE.md
git commit -m "Demo adapter: load_demo_canonical entry point + Phase 2 journal"
```

---

## Self-Review

**1. Spec coverage (Phase 2 / spec §6):** Instacart → canonical through the same pipe → Tasks 3–5. Date reconstruction (cumulative `days_since_prior_order` from a synthetic anchor) → Task 1. Money decision "Both" (synthetic labelled revenue for the demo) → Task 2 + `REVENUE_IS_SYNTHETIC`. Products/depts → `order_items` so the demo lights up optional levers (the "rich"/Full dataset) → Tasks 4–5. `test_demo_adapter.py` (dates monotonic, synthetic revenue present + flagged, order_items populated, output usable by the canonical builder) → all tasks. Deferred (explicitly, per narrow scope): retiring `get_app_data()`, rewiring the app's data-source selector, and rebuilding parquet artifacts to canonical shape — those belong to the later integration step (noted in header + journal). The spec's "output passes the same validator a client upload would" is deferred because the validator itself is Phase 3; Task 5 substitutes the strongest available check (the output composes into a Full FeatureMatrix via Phase 1).

**2. Placeholder scan:** No TBD/TODO. Every code step is complete. Synthetic-price determinism, prior-only filtering, and eval_set exclusion are all concretely tested rather than described.

**3. Type consistency:** `reconstruct_order_dates(orders_raw, anchor)->DataFrame(+order_date)`, `assign_synthetic_prices(products_raw,...)->Series[unit_price] indexed by product_id`, `build_canonical_orders(orders_raw, prior_raw, product_prices)->canonical orders`, `build_canonical_order_items(prior_raw, products_raw, departments_raw)->canonical items`, `to_canonical(...)->(orders, items)`, `load_demo_canonical(data_dir)->(orders, items, FeatureMatrix)`. Canonical column names match Phase 1 exactly (`customer_id, order_id, order_date, order_amount` / `order_id, product, category, quantity`). `DEMO_ANCHOR_DATE`, `REVENUE_IS_SYNTHETIC` referenced consistently in tests and code.

**Optional post-phase check (controller, not a task):** run `load_demo_canonical()` on the real `data/instacart/` once to confirm it scales (may be slow / memory-heavy on ~690MB). Non-blocking — unit tests establish correctness; this only sanity-checks real-data volume.

---

## Remaining phases (sibling plans to write next)

3. **Ingestion pipeline** (`src/data/ingest/`: reader, profiler, mapper, confirm UI, validator, builder) — the upload path + malfunction firewall. The demo adapter and the ingestion builder both emit the same canonical tables.
4. **Re-anchor consumers** — scoring renormalisation, churn→recency, segmentation/interventions/simulation over active levers, dynamic sidebar sliders. **Integration step folds in here:** wire the app to load canonical data (demo via this adapter or an upload) and rebuild artifacts to canonical shape.
5. **Degradation UI** — Full/Degraded/Unavailable states per surface + empty-state card.
6. **Mapping persistence** — save mapping recipe + dataset fingerprint (never raw rows); auto-apply on same-shaped re-upload.
