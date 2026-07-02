# Canonical Data Foundation Implementation Plan (Phase 1 of 6)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the canonical per-customer feature matrix with per-feature availability tags — the one internal data model every analysis/agent/UI surface will read from — so the app can compute meaningful loyalty signals from *any* store's data, not just Instacart.

**Architecture:** A new pure module `src/data/canonical.py` defines two canonical table contracts (`orders`, `order_items`) and a `FeatureMatrix` object: a one-row-per-customer DataFrame plus an `available` map tagging each feature computable/not. RFM-core features come from `orders` alone; optional extension features require `order_items`. Nothing here imports Streamlit; it is fully unit-testable as a standalone script.

**Tech Stack:** Python 3, pandas, numpy, standalone `check()` test scripts (repo house style — no pytest, no network).

**Scope note:** This is Phase 1 of the intelligence-layer BYOD redesign (spec: `docs/superpowers/specs/2026-06-26-intelligence-layer-byod-design.md`). It delivers the canonical model + feature builder + its trust-contract tests. It does NOT wire the app to it — the demo adapter (Phase 2), ingestion pipeline (Phase 3), consumer re-anchoring (Phase 4), degradation UI (Phase 5), and mapping persistence (Phase 6) are separate plans. After this phase, `test_canonical.py` passes and the module is importable, but `app.py` is unchanged and still runs on the old path.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/data/canonical.py` (create) | Canonical table contracts, `FeatureMatrix` dataclass, feature builders (core + optional), availability tagging, the public `build_feature_matrix()` entry point. |
| `tests/test_canonical.py` (create) | The trust contract: feature-math correctness + availability tagging across orders-only and orders+items inputs, plus edge cases (single order, empty items). |

**Canonical contracts (the vocabulary every later phase depends on):**

`orders` DataFrame columns:
- `customer_id` — any hashable id (required)
- `order_id` — unique per order (required)
- `order_date` — pandas datetime (required)
- `order_amount` — float ≥ 0 (required)

`order_items` DataFrame columns (optional table; any subset of the non-`order_id` columns may be absent):
- `order_id` — foreign key into `orders` (required when the table is present)
- `product` — item identifier/name (optional)
- `category` — department/category label (optional)
- `quantity` — int ≥ 1 (optional; defaults to 1 per line when absent)

**Feature vocabulary:**

RFM core (always computable from `orders` alone):
`recency_days`, `frequency`, `monetary`, `avg_order_value`, `tenure_days`, `avg_days_between_orders`

Optional extensions (require `order_items`):
`category_diversity` (needs `category`), `avg_basket_size` (needs item lines), `reorder_rate` (needs `product`)

---

### Task 1: `FeatureMatrix` container + feature-name constants

**Files:**
- Create: `src/data/canonical.py`
- Test: `tests/test_canonical.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_canonical.py`:

```python
"""Standalone tests for src/data/canonical.py — the trust contract. No network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.data.canonical import (
    CORE_FEATURES, OPTIONAL_FEATURES, FeatureMatrix,
)

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def test_feature_matrix_container():
    frame = pd.DataFrame({"customer_id": [1, 2], "recency_days": [3, 9]})
    fm = FeatureMatrix(frame=frame, available={"recency_days": True,
                                               "category_diversity": False})
    check("frame round-trips", list(fm.frame["customer_id"]) == [1, 2])
    check("is_available true", fm.is_available("recency_days") is True)
    check("is_available false", fm.is_available("category_diversity") is False)
    check("unknown feature is unavailable",
          fm.is_available("does_not_exist") is False)
    check("available_features lists only available",
          fm.available_features() == ["recency_days"])
    check("core constant shape", CORE_FEATURES[0] == "recency_days"
          and len(CORE_FEATURES) == 6)
    check("optional constant shape", set(OPTIONAL_FEATURES) ==
          {"category_diversity", "avg_basket_size", "reorder_rate"})


def main():
    test_feature_matrix_container()
    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_canonical.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.data.canonical'` (or ImportError on the names).

- [ ] **Step 3: Write minimal implementation**

Create `src/data/canonical.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_canonical.py`
Expected: PASS — `7 checks passed.`

- [ ] **Step 5: Commit**

```bash
git add src/data/canonical.py tests/test_canonical.py
git commit -m "Canonical: FeatureMatrix container + feature constants"
```

---

### Task 2: RFM-core feature builder (from `orders` alone)

**Files:**
- Modify: `src/data/canonical.py`
- Test: `tests/test_canonical.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_canonical.py` (above `main`), then add the call inside `main`:

```python
def _orders_fixture():
    """Two customers, hand-computable. as_of (max date) = 2024-01-20.
    Customer 1: 3 orders on Jan 1, Jan 11, Jan 20; amounts 10, 20, 30.
    Customer 2: 1 order on Jan 10; amount 100.
    """
    return pd.DataFrame({
        "customer_id": [1, 1, 1, 2],
        "order_id":    [101, 102, 103, 201],
        "order_date":  pd.to_datetime(
            ["2024-01-01", "2024-01-11", "2024-01-20", "2024-01-10"]),
        "order_amount": [10.0, 20.0, 30.0, 100.0],
    })


def test_core_features():
    from src.data.canonical import build_core_features
    fm = build_core_features(_orders_fixture())
    row1 = fm.frame.set_index("customer_id").loc[1]
    row2 = fm.frame.set_index("customer_id").loc[2]

    # as_of = 2024-01-20 (max order_date in the dataset)
    check("recency c1", row1["recency_days"] == 0)        # last order == as_of
    check("recency c2", row2["recency_days"] == 10)       # Jan 20 - Jan 10
    check("frequency c1", row1["frequency"] == 3)
    check("frequency c2", row2["frequency"] == 1)
    check("monetary c1", row1["monetary"] == 60.0)
    check("monetary c2", row2["monetary"] == 100.0)
    check("aov c1", row1["avg_order_value"] == 20.0)
    check("aov c2", row2["avg_order_value"] == 100.0)
    check("tenure c1", row1["tenure_days"] == 19)         # Jan 20 - Jan 1
    check("tenure c2", row2["tenure_days"] == 10)         # Jan 20 - Jan 10
    # gaps for c1: 10 days, 9 days -> mean 9.5; c2 has 1 order -> 0
    check("gap c1", row1["avg_days_between_orders"] == 9.5)
    check("gap c2 single order -> 0", row2["avg_days_between_orders"] == 0.0)

    check("core all available", all(fm.is_available(f) for f in CORE_FEATURES))
    check("optional all unavailable",
          all(not fm.is_available(f) for f in OPTIONAL_FEATURES))
```

Add `test_core_features()` to `main()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_canonical.py`
Expected: FAIL — `ImportError: cannot import name 'build_core_features'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/data/canonical.py`:

```python
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

    # Mean gap between consecutive orders per customer; single-order customers
    # have no gap -> 0 (kept as a secondary churn signal downstream).
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_canonical.py`
Expected: PASS — all core checks plus Task 1's checks.

- [ ] **Step 5: Commit**

```bash
git add src/data/canonical.py tests/test_canonical.py
git commit -m "Canonical: RFM-core feature builder from orders"
```

---

### Task 3: Optional-extension feature builder (from `order_items`)

**Files:**
- Modify: `src/data/canonical.py`
- Test: `tests/test_canonical.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_canonical.py`:

```python
def _items_fixture():
    """order_items for the orders fixture. Customer 1 (orders 101/102/103),
    Customer 2 (order 201). Two categories for c1; c1 reorders 'milk'.
    """
    return pd.DataFrame({
        "order_id": [101, 101, 102, 103, 201],
        "product":  ["milk", "eggs", "milk", "bread", "soda"],
        "category": ["dairy", "dairy", "dairy", "bakery", "drinks"],
        "quantity": [1, 2, 1, 1, 3],
    })


def test_optional_features_full():
    from src.data.canonical import build_optional_features
    fm = build_optional_features(_orders_fixture(), _items_fixture())
    row1 = fm.frame.set_index("customer_id").loc[1]
    row2 = fm.frame.set_index("customer_id").loc[2]

    # c1 categories: dairy, bakery -> 2 ; c2: drinks -> 1
    check("category_diversity c1", row1["category_diversity"] == 2)
    check("category_diversity c2", row2["category_diversity"] == 1)
    # c1 baskets: order101 has 2 lines, 102 has 1, 103 has 1 -> mean (2+1+1)/3
    check("avg_basket_size c1", round(row1["avg_basket_size"], 4) == 1.3333)
    check("avg_basket_size c2", row2["avg_basket_size"] == 1.0)
    # c1 products: milk,eggs,milk,bread -> 4 lines, 3 unique -> reorder 1-3/4=0.25
    check("reorder_rate c1", row1["reorder_rate"] == 0.25)
    check("reorder_rate c2 no repeats", row2["reorder_rate"] == 0.0)

    check("optional all available",
          all(fm.is_available(f) for f in OPTIONAL_FEATURES))


def test_optional_features_partial_columns():
    """order_items with no `category` -> category_diversity unavailable, others OK."""
    from src.data.canonical import build_optional_features
    items = _items_fixture().drop(columns=["category"])
    fm = build_optional_features(_orders_fixture(), items)
    check("category_diversity unavailable when no category column",
          fm.is_available("category_diversity") is False)
    check("category_diversity column absent from frame",
          "category_diversity" not in fm.frame.columns)
    check("avg_basket_size still available",
          fm.is_available("avg_basket_size") is True)
    check("reorder_rate still available",
          fm.is_available("reorder_rate") is True)
```

Add both to `main()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_canonical.py`
Expected: FAIL — `ImportError: cannot import name 'build_optional_features'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/data/canonical.py`:

```python
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

    # Attribute each item line to a customer via the order it belongs to.
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

    # avg_basket_size = mean lines-per-order for the customer (always derivable
    # once item lines exist).
    lines_per_order = line.groupby(["customer_id", "order_id"]).size()
    feats["avg_basket_size"] = lines_per_order.groupby("customer_id").mean()
    available["avg_basket_size"] = True

    if "product" in line.columns:
        # reorder_rate = share of item-lines that are NOT a customer's first
        # buy of that product = 1 - (distinct products / total lines).
        total_lines = grp.size()
        distinct = grp["product"].nunique()
        feats["reorder_rate"] = (1 - (distinct / total_lines))
        available["reorder_rate"] = True

    present = [f for f in OPTIONAL_FEATURES if f in feats.columns]
    feats[present] = feats[present].fillna(0).round(4)
    feats = feats.reset_index()

    return FeatureMatrix(frame=feats, available=available)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_canonical.py`
Expected: PASS — all optional checks plus prior tasks'.

- [ ] **Step 5: Commit**

```bash
git add src/data/canonical.py tests/test_canonical.py
git commit -m "Canonical: optional-extension features with per-column availability"
```

---

### Task 4: Public `build_feature_matrix()` entry point (merge core + optional)

**Files:**
- Modify: `src/data/canonical.py`
- Test: `tests/test_canonical.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_canonical.py`:

```python
def test_build_feature_matrix_orders_only():
    from src.data.canonical import build_feature_matrix
    fm = build_feature_matrix(_orders_fixture())          # no items
    check("orders-only rows == customers", len(fm.frame) == 2)
    check("orders-only has all core cols",
          all(c in fm.frame.columns for c in CORE_FEATURES))
    check("orders-only optional unavailable",
          all(not fm.is_available(f) for f in OPTIONAL_FEATURES))
    check("orders-only available_features == core",
          set(fm.available_features()) == set(CORE_FEATURES))


def test_build_feature_matrix_full():
    from src.data.canonical import build_feature_matrix
    fm = build_feature_matrix(_orders_fixture(), _items_fixture())
    check("full rows == customers", len(fm.frame) == 2)
    check("full has core + optional cols",
          all(c in fm.frame.columns for c in CORE_FEATURES + OPTIONAL_FEATURES))
    check("full everything available",
          set(fm.available_features()) == set(CORE_FEATURES + OPTIONAL_FEATURES))
    # one row per customer after the merge, no duplication
    check("no duplicate customers", fm.frame["customer_id"].is_unique)
    # spot-check a merged value from each side
    row1 = fm.frame.set_index("customer_id").loc[1]
    check("merged core value intact", row1["monetary"] == 60.0)
    check("merged optional value intact", row1["category_diversity"] == 2)
```

Add both to `main()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_canonical.py`
Expected: FAIL — `ImportError: cannot import name 'build_feature_matrix'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/data/canonical.py`:

```python
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

    # Any customer with no item lines gets 0 for the optional columns.
    present_opt = [c for c in OPTIONAL_FEATURES if c in merged.columns]
    merged[present_opt] = merged[present_opt].fillna(0).round(4)

    return FeatureMatrix(frame=merged, available=available)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_canonical.py`
Expected: PASS — orders-only + full checks plus all prior.

- [ ] **Step 5: Commit**

```bash
git add src/data/canonical.py tests/test_canonical.py
git commit -m "Canonical: build_feature_matrix entry point (core + optional merge)"
```

---

### Task 5: Edge-case hardening (single order, empty items, missing customers)

**Files:**
- Modify: `src/data/canonical.py` (only if a test fails)
- Test: `tests/test_canonical.py`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_canonical.py`:

```python
def test_edge_single_customer_single_order():
    from src.data.canonical import build_feature_matrix
    one = pd.DataFrame({
        "customer_id": [7], "order_id": [1],
        "order_date": pd.to_datetime(["2024-05-01"]),
        "order_amount": [42.0],
    })
    fm = build_feature_matrix(one)
    row = fm.frame.set_index("customer_id").loc[7]
    check("single: recency 0", row["recency_days"] == 0)
    check("single: frequency 1", row["frequency"] == 1)
    check("single: gap 0 (no diff)", row["avg_days_between_orders"] == 0.0)
    check("single: aov == monetary", row["avg_order_value"] == 42.0)


def test_edge_empty_items_table():
    from src.data.canonical import build_feature_matrix
    empty_items = pd.DataFrame(columns=["order_id", "product",
                                        "category", "quantity"])
    fm = build_feature_matrix(_orders_fixture(), empty_items)
    check("empty items -> optional unavailable",
          all(not fm.is_available(f) for f in OPTIONAL_FEATURES))
    check("empty items -> core still available",
          all(fm.is_available(f) for f in CORE_FEATURES))


def test_edge_customer_with_no_items():
    """Customer 2 has an order but NO item lines -> optional cols are 0, not NaN."""
    from src.data.canonical import build_feature_matrix
    items_c1_only = _items_fixture()[_items_fixture()["order_id"] != 201]
    fm = build_feature_matrix(_orders_fixture(), items_c1_only)
    row2 = fm.frame.set_index("customer_id").loc[2]
    check("no-item customer basket 0", row2["avg_basket_size"] == 0.0)
    check("no-item customer category_diversity 0",
          row2["category_diversity"] == 0.0)
    check("no NaNs in optional cols",
          not fm.frame[["avg_basket_size", "category_diversity",
                        "reorder_rate"]].isna().any().any())
```

Add all three to `main()`.

- [ ] **Step 2: Run test to verify it fails or reveals a bug**

Run: `..\venv\Scripts\python.exe tests/test_canonical.py`
Expected: Either PASS (implementation already handles these — likely) or a precise FAIL pointing at the row that needs a guard. The empty-items case relies on `build_feature_matrix` treating a 0-row items table like `None`.

- [ ] **Step 3: Fix implementation if needed**

If `test_edge_empty_items_table` fails, harden the guard in `build_feature_matrix` — change the early-return condition so an all-empty items frame is treated as "no items":

```python
    if order_items is None or len(order_items) == 0:
        return core
```

(Already present from Task 4 — confirm it covers the empty-DataFrame path; if the empty frame still flows through, add `order_items = order_items.dropna(how="all")` before the length check.)

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_canonical.py`
Expected: PASS — every check, all tasks.

- [ ] **Step 5: Commit**

```bash
git add src/data/canonical.py tests/test_canonical.py
git commit -m "Canonical: edge-case hardening (single order, empty/absent items)"
```

---

### Task 6: Regression sweep — existing suites stay green

**Files:**
- No production changes. This task proves Phase 1 added the module without disturbing anything.

- [ ] **Step 1: Run the full existing test suite**

Run each (repo house style — standalone scripts):

```powershell
..\venv\Scripts\python.exe tests/test_canonical.py
..\venv\Scripts\python.exe tests/test_scoring.py
..\venv\Scripts\python.exe tests/test_simulation.py
..\venv\Scripts\python.exe tests/test_persistence.py
```

Expected: every script prints `N checks passed.` and exits 0. (Other suites — insights/proactive/memory/router/watches — are untouched by this phase; run them too if quick.)

- [ ] **Step 2: Confirm the app still boots (unchanged path)**

Run:

```powershell
..\venv\Scripts\python.exe -c "import ast; ast.parse(open('src/data/canonical.py', encoding='utf-8').read()); print('canonical.py parses')"
```

Expected: `canonical.py parses`. (App wiring is Phase 2+; a headless boot test belongs there.)

- [ ] **Step 3: Commit journal entry**

Add a dated entry to the top of the Project Journal in `CLAUDE.md`:

```markdown
### 2026-07-02 — Intelligence Layer, Phase 1: Canonical data model
Added the one internal data shape every surface will read from (spec:
docs/superpowers/specs/2026-06-26-intelligence-layer-byod-design.md).
- **`src/data/canonical.py`** (NEW, pure / Streamlit-free): canonical `orders`
  + `order_items` contracts; `FeatureMatrix` (per-customer frame + per-feature
  `available` map with `is_available` / `available_features`); `build_core_features`
  (RFM core from orders alone — recency/frequency/monetary/AOV/tenure/avg-gap,
  all always available), `build_optional_features` (category_diversity/
  avg_basket_size/reorder_rate, each tagged available only when its column
  exists), and `build_feature_matrix(orders, order_items=None)` merging both.
- Availability tagging is the "never malfunctions" mechanism: orders-only input
  tags all optional features unavailable; downstream phases degrade on the tag.
- Tests: `tests/test_canonical.py` — the trust contract (feature math on a
  hand-computable fixture + availability across orders-only / full / partial /
  edge inputs). No network. Existing suites still green.
- Scope: model + builder + tests only. App still runs the old Instacart path;
  demo adapter / ingestion / re-anchoring / degradation / persistence are the
  next phases.
```

```bash
git add CLAUDE.md
git commit -m "Docs: journal entry for Phase 1 canonical data model"
```

---

## Self-Review

**1. Spec coverage (this phase):** Spec §2 (canonical model — two tables, feature matrix with availability tags) → Tasks 1–4. RFM-core feature list → Task 2 (matches spec table exactly: recency_days, frequency, monetary, avg_order_value, tenure_days, avg_days_between_orders). Optional extensions → Task 3 (category_diversity, avg_basket_size, reorder_rate). Availability tagging as the never-malfunctions mechanism → Tasks 3–5. Spec §7 "test_canonical.py is the trust contract" → Tasks 1–5. Out-of-phase spec sections (§3 ingestion, §4 re-anchoring, §5 degradation, §6 demo, persistence) are explicitly deferred to sibling plans — noted in the header scope note.

**2. Placeholder scan:** No TBD/TODO/"handle edge cases" left abstract — Task 5 enumerates the exact edge cases with concrete assertions. Every code step shows full code.

**3. Type consistency:** `FeatureMatrix(frame=..., available=...)`, `.is_available(str)->bool`, `.available_features()->list`, `build_core_features(orders)->FeatureMatrix`, `build_optional_features(orders, order_items)->FeatureMatrix`, `build_feature_matrix(orders, order_items=None)->FeatureMatrix`, `CORE_FEATURES` (6 names), `OPTIONAL_FEATURES` (3 names) — used identically across all tasks and tests. Canonical column names (`customer_id`, `order_id`, `order_date`, `order_amount`, `product`, `category`, `quantity`) are consistent throughout.

**Open decision carried to Phase 2 (demo adapter):** `reorder_rate` here is derived as `1 - distinct_products/total_lines` (no `reordered` flag in the canonical `order_items` contract). The Instacart demo adapter must map products so this proxy lands close to Instacart's native reorder signal — flag this when writing Phase 2.

---

## Remaining phases (sibling plans to write next)

Per spec §9 build order — each is its own plan producing working, testable software:

2. **Demo adapter** (`src/data/demo/instacart.py`) — Instacart → canonical (reconstruct dates, synthetic labelled revenue, products→order_items). Proves the pipe on known data.
3. **Ingestion pipeline** (`src/data/ingest/`: reader, profiler, mapper, confirm UI, validator, builder). The upload path + malfunction firewall.
4. **Re-anchor consumers** — scoring renormalisation, churn→recency, segmentation/interventions/simulation over active levers, dynamic sidebar sliders.
5. **Degradation UI** — Full/Degraded/Unavailable states per surface + empty-state card component.
6. **Mapping persistence** — save mapping recipe + dataset fingerprint (never raw rows); auto-apply on same-shaped re-upload.
