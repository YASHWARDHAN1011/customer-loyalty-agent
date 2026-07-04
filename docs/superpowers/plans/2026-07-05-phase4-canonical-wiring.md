# Phase 4 — Re-anchor + Wire Canonical Data — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the app load the canonical demo (a `FeatureMatrix`) instead of the hardcoded Instacart path, and make the scoring/churn/simulation engine + sidebar operate over whichever loyalty *levers* the data actually supports — so nothing malfunctions on partial data.

**Architecture:** A new pure module `src/data/levers.py` defines the canonical loyalty levers and renormalizes weights over the ones that are *available*. A new adapter `src/data/app_data.py` turns a canonical `FeatureMatrix` into the `features` DataFrame the existing app already consumes (aliasing `customer_id` → `user_id` for backward compatibility) and reports the active levers. `app.py` loads through this adapter; the sidebar renders one weight slider per active lever; churn switches to `recency_days`. A canonical artifact builder keeps boot fast.

**Tech Stack:** Python, pandas, Streamlit. Tests are **standalone scripts** (repo convention — not pytest); each `assert`s and exits non-zero on failure. Run with `..\venv\Scripts\python.exe tests\<name>.py`.

---

## Scope (read this first)

**In scope:** load canonical data → the app; lever-agnostic scoring weights, thresholds, churn, simulation; dynamic sidebar sliders; a canonical artifact builder; keep the app booting without `KeyError` on canonical data.

**Deliberately deferred to Phase 7 (chat-first shell):** deep re-anchoring of the five dashboard tabs' charts (Overview/Scoring/Segments/Happy Path/Interventions) and the per-tool column renaming in `tools.py`. **Reason:** Phase 7 removes the dashboard tabs entirely, so fully rebuilding their Instacart-specific charts now is throwaway work. This plan gives those tabs a **minimal degradation guard** (show "not available on this dataset" instead of crashing) — enough to keep the app usable until Phase 7 replaces them. The scoring engine, churn, simulation, and sidebar (which all survive Phase 7) get the *real* re-anchoring here.

**Canonical vs legacy names:** the canonical `FeatureMatrix` uses `customer_id` + RFM feature names (`recency_days, frequency, monetary, avg_order_value, tenure_days, avg_days_between_orders` + optional `category_diversity, avg_basket_size, reorder_rate`). The legacy app uses `user_id` + Instacart names (`total_orders, reorder_rate, dept_diversity, avg_basket_size, total_items`). The adapter bridges the `id` column; the *feature* set legitimately changes (that is the whole point), so downstream must read levers from the data, never a hardcoded list.

---

## File Structure

- **Create** `src/data/levers.py` — pure: `SCORING_LEVERS`, `LEVER_LABELS`, `active_levers()`, `default_weights()`, `renormalize_weights()`.
- **Create** `src/data/app_data.py` — adapter: `features_from_matrix()`, `load_demo_app_data()`, canonical-artifact load/exists.
- **Create** `scripts/build_canonical_artifacts.py` — precompute canonical parquet so boot is fast.
- **Create** `tests/test_levers.py`, `tests/test_app_data.py` — standalone-script tests.
- **Modify** `src/analysis/scoring.py` — `get_thresholds()` takes a dynamic feature list.
- **Modify** `src/analysis/metrics.py` — `calculate_churn_risk()` uses `recency_days` (id-column agnostic).
- **Modify** `src/analysis/simulation.py` — `simulate_campaign()` accepts an explicit lever set.
- **Modify** `app.py` — load via `app_data`; default weights from active levers; store `available`/`active_levers`.
- **Modify** `src/ui/sidebar.py` — dynamic weight sliders from active levers.
- **Modify** `src/ui/tabs/*.py` (guard only) — degrade gracefully when a referenced column is absent.

---

## Task 1: Levers module — the "which features can we score on" contract

**Files:**
- Create: `src/data/levers.py`
- Test: `tests/test_levers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_levers.py — standalone script (repo convention)
import sys
import pandas as pd
from src.data.canonical import build_feature_matrix
from src.data import levers

checks = 0
def ok(cond, msg):
    global checks
    assert cond, msg
    checks += 1

# orders-only matrix -> only orders-derivable levers are active
orders = pd.DataFrame({
    "customer_id": [1, 1, 2],
    "order_id": [10, 11, 12],
    "order_date": ["2024-01-01", "2024-01-10", "2024-01-05"],
    "order_amount": [50.0, 30.0, 20.0],
})
m_core = build_feature_matrix(orders)
al = levers.active_levers(m_core)
ok("frequency" in al, "frequency should be an active lever on orders-only")
ok("monetary" in al, "monetary should be active")
ok("avg_basket_size" not in al, "optional levers inactive without order_items")
ok("recency_days" not in levers.SCORING_LEVERS, "recency is churn, not a loyalty lever")
ok("avg_days_between_orders" not in levers.SCORING_LEVERS, "avg-gap is churn, not a lever")

# default_weights: equal, sums to 1.0, one entry per active lever
w = levers.default_weights(al)
ok(abs(sum(w.values()) - 1.0) < 1e-9, "default weights must sum to 1.0")
ok(set(w.keys()) == set(al), "default weights cover exactly the active levers")

# renormalize_weights: drop absent levers, rescale remainder to sum 1.0
raw = {"frequency": 0.5, "monetary": 0.25, "avg_basket_size": 0.25}
rn = levers.renormalize_weights(raw, ["frequency", "monetary"])
ok(set(rn.keys()) == {"frequency", "monetary"}, "renorm drops unavailable levers")
ok(abs(sum(rn.values()) - 1.0) < 1e-9, "renorm rescales to 1.0")
ok(abs(rn["frequency"] - (0.5 / 0.75)) < 1e-9, "renorm preserves relative weight")

# all-zero weights over the levers -> fall back to equal
rz = levers.renormalize_weights({"frequency": 0.0, "monetary": 0.0}, ["frequency", "monetary"])
ok(abs(rz["frequency"] - 0.5) < 1e-9, "all-zero renorm falls back to equal weights")

# every lever has a human label
for lv in levers.SCORING_LEVERS:
    ok(lv in levers.LEVER_LABELS, f"{lv} needs a UI label")

print(f"test_levers: {checks} checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_levers.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.data.levers'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/data/levers.py
"""Loyalty scoring levers over the canonical FeatureMatrix.

A "lever" is a canonical feature where higher = more loyal, so it can carry a
scoring weight. recency_days and avg_days_between_orders are excluded — they are
"lower = better" churn signals, not loyalty levers (mirrors the old
simulation.LEVERS decision). Downstream reads the ACTIVE levers from the data's
availability map, never a hardcoded column list — that is the "never
malfunctions" mechanism at the scoring layer.
"""

from src.data.canonical import CORE_FEATURES, OPTIONAL_FEATURES  # noqa: F401

# Higher-is-better canonical features, in display order.
SCORING_LEVERS = [
    "frequency",
    "monetary",
    "avg_order_value",
    "tenure_days",
    "category_diversity",
    "avg_basket_size",
    "reorder_rate",
]

LEVER_LABELS = {
    "frequency": "Order Frequency",
    "monetary": "Total Spend",
    "avg_order_value": "Avg Order Value",
    "tenure_days": "Tenure",
    "category_diversity": "Category Diversity",
    "avg_basket_size": "Basket Size",
    "reorder_rate": "Reorder Rate",
}


def active_levers(matrix):
    """The SCORING_LEVERS the given FeatureMatrix can actually compute."""
    return [lv for lv in SCORING_LEVERS if matrix.is_available(lv)]


def default_weights(levers):
    """Equal weights over `levers`, summing to 1.0 (empty -> {})."""
    if not levers:
        return {}
    share = 1.0 / len(levers)
    return {lv: share for lv in levers}


def renormalize_weights(weights, levers):
    """Keep only weights for `levers` and rescale them to sum to 1.0.

    If none of the levers carry positive weight, fall back to equal weights so
    scoring never divides by zero or silently zeroes every score.
    """
    if not levers:
        return {}
    kept = {lv: float(weights.get(lv, 0.0)) for lv in levers}
    total = sum(kept.values())
    if total <= 0:
        return default_weights(levers)
    return {lv: w / total for lv, w in kept.items()}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_levers.py`
Expected: PASS — `test_levers: N checks passed`

- [ ] **Step 5: Commit**

```bash
git add src/data/levers.py tests/test_levers.py
git commit -m "feat: canonical scoring levers + weight renormalization"
```

---

## Task 2: Dynamic thresholds — stop hardcoding the Instacart feature list

**Files:**
- Modify: `src/analysis/scoring.py:90-111` (`get_thresholds`)
- Test: extend `tests/test_scoring.py` (append; keep existing checks)

- [ ] **Step 1: Write the failing test (append to tests/test_scoring.py)**

```python
# --- Phase 4: get_thresholds over an explicit feature list ---
import pandas as pd
from src.analysis.scoring import get_thresholds

power = pd.DataFrame({"frequency": [10, 8], "monetary": [500.0, 400.0]})
regular = pd.DataFrame({"frequency": [2, 3], "monetary": [50.0, 70.0]})

# explicit canonical feature list -> table built over exactly those features
th = get_thresholds(power, regular, feature_cols=["frequency", "monetary"])
assert set(th["Feature"]) == {"Frequency", "Monetary"}, "thresholds honor feature_cols"
assert "Ratio" in th.columns, "thresholds keep the Ratio column"

# a feature absent from the frames is skipped, not a KeyError
th2 = get_thresholds(power, regular, feature_cols=["frequency", "reorder_rate"])
assert set(th2["Feature"]) == {"Frequency"}, "absent feature is skipped, no crash"
print("test_scoring: get_thresholds dynamic-list checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_scoring.py`
Expected: FAIL — `get_thresholds() got an unexpected keyword argument 'feature_cols'`

- [ ] **Step 3: Write minimal implementation (replace `get_thresholds`)**

```python
def get_thresholds(power, regular, feature_cols=None):
    """Build a feature-comparison table between segments.

    `feature_cols` defaults to whatever numeric feature columns both frames
    share (minus id/score columns), so it works on ANY dataset's levers.
    Columns not present in the frames are skipped rather than raising.
    """
    if feature_cols is None:
        skip = {"user_id", "customer_id", "raw_score", "loyalty_score"}
        feature_cols = [c for c in power.columns
                        if c not in skip and c in regular.columns]
    rows = []
    for col in feature_cols:
        if col not in power.columns or col not in regular.columns:
            continue
        pu_avg = power[col].mean()
        ru_avg = regular[col].mean()
        ratio = pu_avg / max(ru_avg, 0.001)
        rows.append({
            'Feature': col.replace('_', ' ').title(),
            'Power User Avg': round(pu_avg, 2),
            'Regular User Avg': round(ru_avg, 2),
            'Power User Min': round(power[col].min(), 2),
            'Ratio': round(ratio, 1),
        })
    return pd.DataFrame(rows).sort_values('Ratio', ascending=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_scoring.py`
Expected: PASS (existing checks + the new ones)

- [ ] **Step 5: Commit**

```bash
git add src/analysis/scoring.py tests/test_scoring.py
git commit -m "feat: get_thresholds operates over a dynamic feature list"
```

---

## Task 3: Churn on recency — the RFM churn signal

**Files:**
- Modify: `src/analysis/metrics.py` (`calculate_churn_risk`)
- Test: `tests/test_metrics.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics.py — standalone script
import pandas as pd
from src.analysis.metrics import calculate_churn_risk

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

# recency-based churn (canonical): recency_days > threshold = at risk
feat = pd.DataFrame({
    "customer_id": [1, 2, 3],
    "recency_days": [10, 45, 90],
    "frequency": [5, 3, 2],
})
at_risk, at_risk_power = calculate_churn_risk(feat, power_user_ids={2}, churn_days=30)
ok(set(at_risk["customer_id"]) == {2, 3}, "recency>30 flags customers 2 and 3")
ok(set(at_risk_power["customer_id"]) == {2}, "at-risk power = intersection with power ids")

# legacy fallback: no recency_days but avg_days_between_orders + user_id present
legacy = pd.DataFrame({
    "user_id": [1, 2],
    "avg_days_between_orders": [10, 60],
})
lr, lrp = calculate_churn_risk(legacy, power_user_ids=set(), churn_days=30)
ok(set(lr["user_id"]) == {2}, "falls back to avg_days_between_orders when no recency")

print(f"test_metrics: {checks} checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_metrics.py`
Expected: FAIL — `KeyError: 'avg_days_between_orders'` (recency branch not implemented)

- [ ] **Step 3: Write minimal implementation (replace `calculate_churn_risk`)**

```python
def calculate_churn_risk(features, power_user_ids, churn_days=30):
    """Identify customers at risk of churning.

    Primary signal is `recency_days` (days since last order) — the RFM churn
    measure that works on any store. Falls back to `avg_days_between_orders`
    for legacy/Instacart frames that lack recency. Id column is whichever of
    `customer_id` / `user_id` is present.
    """
    id_col = "customer_id" if "customer_id" in features.columns else "user_id"
    signal = "recency_days" if "recency_days" in features.columns \
        else "avg_days_between_orders"
    at_risk = features[features[signal] > churn_days]
    at_risk_power = at_risk[at_risk[id_col].isin(power_user_ids)]
    return at_risk, at_risk_power
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_metrics.py`
Expected: PASS — `test_metrics: N checks passed`

- [ ] **Step 5: Commit**

```bash
git add src/analysis/metrics.py tests/test_metrics.py
git commit -m "feat: churn risk uses recency_days with legacy avg-gap fallback"
```

---

## Task 4: Simulation over an explicit lever set

**Files:**
- Modify: `src/analysis/simulation.py:20-70` (`simulate_campaign` signature)
- Test: extend `tests/test_simulation.py` (append)

- [ ] **Step 1: Write the failing test (append to tests/test_simulation.py)**

```python
# --- Phase 4: simulate over canonical levers via an explicit `levers` arg ---
import pandas as pd
from src.analysis import simulation

feats = pd.DataFrame({
    "user_id": [1, 2, 3, 4],
    "frequency": [1, 2, 8, 10],
    "monetary": [20.0, 40.0, 300.0, 500.0],
})
weights = {"frequency": 0.5, "monetary": 0.5}
res = simulation.simulate_campaign(
    feats, weights, top_pct=25, feature="frequency", lift_pct=50,
    levers=["frequency", "monetary"],
)
assert res["feature"] == "frequency", "sim runs on a canonical lever"
assert res["conversions"] >= 0, "sim returns conversions"
print("test_simulation: canonical-lever sim checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_simulation.py`
Expected: FAIL — `simulate_campaign() got an unexpected keyword argument 'levers'`

- [ ] **Step 3: Write minimal implementation**

Change the signature and drop the reorder-clip to be lever-name-driven. Replace the `def simulate_campaign(...)` line and the reorder clip:

```python
def simulate_campaign(features, weights, top_pct, feature, lift_pct, levers=None):
    """Project a single-feature campaign lift on regular users.

    `levers` (defaults to the module LEVERS) is only used by callers to validate
    `feature`; the math is unchanged. Kept as a param so the app can pass the
    dataset's ACTIVE levers instead of the hardcoded Instacart five.
    """
```

Leave the body identical EXCEPT the reorder clip line — make it name-based so it also clips the canonical `reorder_rate`:

```python
    if feature == "reorder_rate":
        lifted.loc[mask, feature] = lifted.loc[mask, feature].clip(upper=1.0)
```

(No change needed to that line — it already matches the canonical name. The `levers` param is accepted and ignored by the math; validation happens at the tool layer.)

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_simulation.py`
Expected: PASS (existing + new)

- [ ] **Step 5: Commit**

```bash
git add src/analysis/simulation.py tests/test_simulation.py
git commit -m "feat: simulate_campaign accepts an explicit lever set"
```

---

## Task 5: App-data adapter — canonical FeatureMatrix → the app's `features` frame

**Files:**
- Create: `src/data/app_data.py`
- Test: `tests/test_app_data.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app_data.py — standalone script
import pandas as pd
from src.data.canonical import build_feature_matrix
from src.data.app_data import features_from_matrix

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

orders = pd.DataFrame({
    "customer_id": [1, 1, 2],
    "order_id": [10, 11, 12],
    "order_date": ["2024-01-01", "2024-01-10", "2024-01-05"],
    "order_amount": [50.0, 30.0, 20.0],
})
matrix = build_feature_matrix(orders)
features, available, active = features_from_matrix(matrix)

ok("user_id" in features.columns, "adapter aliases customer_id -> user_id")
ok("customer_id" in features.columns, "adapter keeps customer_id too")
ok(list(features["user_id"]) == list(features["customer_id"]), "user_id equals customer_id")
ok("frequency" in features.columns, "canonical feature columns pass through")
ok(available["frequency"] is True, "availability map is returned")
ok("frequency" in active and "avg_basket_size" not in active,
   "active levers reflect availability")

print(f"test_app_data: {checks} checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_app_data.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.data.app_data'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/data/app_data.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_app_data.py`
Expected: PASS — `test_app_data: N checks passed`

- [ ] **Step 5: Commit**

```bash
git add src/data/app_data.py tests/test_app_data.py
git commit -m "feat: canonical FeatureMatrix -> app features adapter"
```

---

## Task 6: Canonical artifact builder — fast boot

**Files:**
- Create: `scripts/build_canonical_artifacts.py`

- [ ] **Step 1: Write the script**

```python
# scripts/build_canonical_artifacts.py
"""Precompute canonical demo artifacts so the app boots without reading ~690MB.

Writes data/artifacts/canonical/{orders,order_items}.parquet from the Instacart
demo adapter. The app rebuilds the FeatureMatrix from these at boot (cheap).
Run: ..\\venv\\Scripts\\python.exe scripts\\build_canonical_artifacts.py
"""

import os

from src.data.demo.instacart import load_demo_canonical
from src.data.app_data import CANON_DIR, CANON_ORDERS, CANON_ITEMS


def main():
    os.makedirs(CANON_DIR, exist_ok=True)
    orders, items, _matrix = load_demo_canonical()
    orders.to_parquet(CANON_ORDERS, index=False)
    items.to_parquet(CANON_ITEMS, index=False)
    print(f"Wrote {len(orders):,} orders -> {CANON_ORDERS}")
    print(f"Wrote {len(items):,} order_items -> {CANON_ITEMS}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it to build the artifacts**

Run: `..\venv\Scripts\python.exe scripts\build_canonical_artifacts.py`
Expected: prints two "Wrote N …" lines; `data/artifacts/canonical/orders.parquet` + `order_items.parquet` exist.

*(If the raw Instacart CSVs are absent locally, note this in the task report and skip — the app's fallback path still works once CSVs are present. Do NOT fabricate artifacts.)*

- [ ] **Step 3: Commit (artifacts + script)**

```bash
git add scripts/build_canonical_artifacts.py data/artifacts/canonical/
git commit -m "feat: canonical demo artifact builder + committed parquet"
```

*(Confirm `data/artifacts/` is force-included in .gitignore — the repo already un-ignores `data/artifacts/*.parquet`; extend the rule to the `canonical/` subdir if needed.)*

---

## Task 7: Wire app.py to canonical data

**Files:**
- Modify: `app.py:6` (import), `app.py:59-70` (load + defaults)

- [ ] **Step 1: Swap the data source + default weights**

Replace `from src.data.loader import get_app_data` with:

```python
from src.data.app_data import load_demo_app_data
from src.data.levers import default_weights
```

Replace `orders, full_data, features = get_app_data()` (line 59) with:

```python
orders, order_items, features, available, active_levers = load_demo_app_data()
full_data = order_items  # line-item table (used by happy-path; degrades if empty)
```

Replace the hardcoded `'weights': {...}` entry in `defaults` (line 65) with a computed default and add the new state keys:

```python
    'weights': default_weights(active_levers),
    'available': available,
    'active_levers': active_levers,
```

- [ ] **Step 2: Boot smoke test**

Run (headless):
```
..\venv\Scripts\python.exe -m streamlit run app.py --server.headless true
```
Then verify HTTP 200:
```
(Invoke-WebRequest http://localhost:8501 -UseBasicParsing).StatusCode
```
Expected: `200`, no traceback in the Streamlit output. Stop the process after.

- [ ] **Step 3: Commit**

```bash
git add app.py
git commit -m "feat: app.py loads canonical demo data + lever-based default weights"
```

---

## Task 8: Dynamic sidebar sliders (one per active lever)

**Files:**
- Modify: `src/ui/sidebar.py:66-107` (dataset stat + weight sliders block)

- [ ] **Step 1: Replace the five hardcoded sliders with a loop over active levers**

Replace the `st.metric("Avg Orders/User", ...)` line (line 63-66) — `total_orders` no longer exists — with a lever-agnostic stat:

```python
        if "frequency" in features.columns:
            st.metric("Avg Orders/User", f"{features['frequency'].mean():.1f}")
```

Replace the five `w_* = st.slider(...)` lines (74-78), the `total_w` sum (80), and the `st.session_state['weights'] = {...}` dict (101-107) with:

```python
        from src.data.levers import LEVER_LABELS, renormalize_weights
        active = st.session_state.get('active_levers', [])
        raw_weights = {}
        for lv in active:
            raw_weights[lv] = st.slider(
                LEVER_LABELS.get(lv, lv), 0.0, 1.0,
                float(st.session_state['weights'].get(lv, 0.0)), 0.05,
            )
        total_w = sum(raw_weights.values())
        if abs(total_w - 1.0) > 0.01:
            st.caption(f"Weights sum to {total_w:.2f} — normalized to 1.0 at scoring time.")
        else:
            st.success(f"✅ Weights sum: {total_w:.2f}")
        st.session_state['weights'] = renormalize_weights(raw_weights, active)
```

- [ ] **Step 2: Boot smoke test**

Run the headless boot + HTTP 200 check from Task 7 Step 2. Confirm the sidebar shows one slider per active lever (labels from `LEVER_LABELS`) and no `KeyError`.

- [ ] **Step 3: Commit**

```bash
git add src/ui/sidebar.py
git commit -m "feat: dynamic sidebar weight sliders over active levers"
```

---

## Task 9: Degradation guards on the dashboard tabs (keep the app booting)

**Files:**
- Modify: `src/ui/tabs/overview.py`, `scoring.py`, `segments.py`, `happy_path.py`, `interventions.py`

**Intent:** These tabs are removed in Phase 7. Here we only stop them from raising `KeyError` on canonical columns. Each tab, at its top, checks for the specific legacy columns it needs and shows a Streamlit info card instead of rendering when they are absent.

- [ ] **Step 1: Add a guard helper**

Create `src/ui/tabs/_guard.py`:

```python
# src/ui/tabs/_guard.py
import streamlit as st


def needs_columns(features, cols, tab_name):
    """Return True (and render an info card) if any required column is missing.

    Used by the legacy dashboard tabs to degrade instead of crashing on
    canonical data. These tabs are superseded by the chat-first shell (Phase 7).
    """
    missing = [c for c in cols if features is None or c not in features.columns]
    if missing:
        st.info(
            f"**{tab_name}** isn't available for this dataset "
            f"(missing: {', '.join(missing)}). Use the AI Chat to analyze "
            f"this data instead."
        )
        return True
    return False
```

- [ ] **Step 2: Guard each tab**

At the top of each tab's render function, before it touches feature columns, add the matching guard. Example for `overview.py` (`render_overview(features, orders)`):

```python
    from src.ui.tabs._guard import needs_columns
    if needs_columns(features, ["total_orders"], "Overview"):
        return
```

Apply the analogous guard to the other tabs using a column each is known to require:
- `scoring.py` → guard on `st.session_state.get('scored_df') is None` already exists; additionally guard reads of `total_orders`/`reorder_rate` with `needs_columns(st.session_state.get('features'), ["total_orders"], "Scoring")`.
- `segments.py` → `needs_columns(st.session_state.get('features'), ["total_orders"], "Segments")`.
- `happy_path.py` → guard on empty `full_data`: `if full_data is None or len(full_data) == 0: st.info("Happy Path needs product-level order data."); return`.
- `interventions.py` → `needs_columns(st.session_state.get('features'), ["reorder_rate"], "Interventions")` (the intervention templates are keyed to Instacart features).

- [ ] **Step 3: Boot smoke test**

Run the headless boot + HTTP 200 check. Click through all six tabs mentally via the render path: each legacy tab shows its info card (not a traceback); the AI Chat tab still renders.

- [ ] **Step 4: Commit**

```bash
git add src/ui/tabs/_guard.py src/ui/tabs/overview.py src/ui/tabs/scoring.py src/ui/tabs/segments.py src/ui/tabs/happy_path.py src/ui/tabs/interventions.py
git commit -m "feat: graceful degradation guards on legacy dashboard tabs"
```

---

## Task 10: Full-suite green + journal entry

**Files:**
- Modify: `CLAUDE.md` (add a dated journal entry at the top of the Project Journal)

- [ ] **Step 1: Run every no-network suite**

```
..\venv\Scripts\python.exe tests\test_levers.py
..\venv\Scripts\python.exe tests\test_app_data.py
..\venv\Scripts\python.exe tests\test_metrics.py
..\venv\Scripts\python.exe tests\test_scoring.py
..\venv\Scripts\python.exe tests\test_simulation.py
..\venv\Scripts\python.exe tests\test_canonical.py
..\venv\Scripts\python.exe tests\test_demo_adapter.py
```
Expected: every script prints its pass line and exits 0.

- [ ] **Step 2: Final boot smoke test**

Headless boot + HTTP 200, no traceback. Stop the process.

- [ ] **Step 3: Add the journal entry**

Prepend a `### 2026-07-05 — Intelligence Layer, Phase 4: Re-anchor + wire canonical data` entry to the Project Journal in `CLAUDE.md` summarizing: canonical data now loads via `app_data`, scoring/churn/simulation/sidebar are lever-agnostic, churn switched to `recency_days`, legacy tabs degrade gracefully (removed in Phase 7), canonical artifacts committed. Note deferrals (deep tab/tool re-anchoring → Phase 7).

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: journal entry for Phase 4 canonical wiring"
```

---

## Self-Review notes (author)

- **Spec coverage** (roadmap §6 Phase 4): retire `get_app_data` special path ✅ (Task 7 swaps it out; `loader.py` kept only as the demo-adapter's raw reader). Renormalize scoring over available levers ✅ (Tasks 1, 8). Dynamic sidebar sliders ✅ (Task 8). Churn → `recency_days` ✅ (Task 3). Rebuild canonical artifacts ✅ (Task 6). Graceful degradation per surface ✅ (Task 9, minimal by design — deep version folded into Phase 7 per the Scope section).
- **Deferred, documented, not gaps:** deep re-anchoring of dashboard-tab charts and `tools.py` column names → Phase 7 (tabs are deleted there; re-skinning them now is throwaway). `simulate_campaign`'s tool-layer lever validation is updated when `tools.py` is re-anchored in Phase 7 — Task 4 only makes the engine accept the lever set.
- **Type consistency:** `features_from_matrix()` returns `(features, available, active)` and `load_demo_app_data()` returns `(orders, items, features, available, active)` — app.py unpacks the 5-tuple (Task 7). `renormalize_weights(weights, levers)` signature identical in Task 1 def and Tasks 8 usage.
- **Known follow-up:** `get_thresholds` default now derives columns from the frame; the scoring tab that consumes `thresholds_df` is guarded in Task 9, so no crash.
```
