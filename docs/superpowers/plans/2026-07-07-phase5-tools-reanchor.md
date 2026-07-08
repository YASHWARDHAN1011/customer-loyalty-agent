# Phase 5 — Re-anchor Agent Tools on Canonical Levers + Minimal Degradation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every agent tool compute correct numbers on whatever features a dataset actually has — never `KeyError` on canonical/client data, and clearly say when a feature can't be computed — instead of assuming the Instacart columns.

**Architecture:** A new pure helper `src/agent/tool_context.py` centralizes "which column represents X, and what's present" so each tool reads the dataset's real features (via the `available`/`active_levers` map already in session state from Phase 4) rather than a hardcoded Instacart list. Tools degrade to a relayable message when a feature is absent. A generic intervention-template fallback keeps campaigns/emails/action-plans working on any lever set. The system prompt is genericized so the LLM stops promising Instacart-only fields.

**Tech Stack:** Python, pandas, Streamlit, `streamlit.testing.v1.AppTest`. Tests are **standalone scripts** (repo convention, not pytest); each exits non-zero on failure. Run with `..\venv\Scripts\python.exe tests\<name>.py`.

**Spec basis:** roadmap `docs/superpowers/specs/2026-07-05-chat-first-agent-roadmap-design.md` (Phase 5) + BYOD design `docs/superpowers/specs/2026-06-26-intelligence-layer-byod-design.md` §3–§4. Scope confirmed with user: **Minimal — crash-proof + correct** (generic campaign copy, no hand-authored e-commerce templates this phase).

---

## Scope

**In:** a pure column-resolution helper; re-anchor `run_scoring_analysis`, `get_current_stats`, `analyze_churn_risk`, `get_user_profile`, `search_users`, `simulate_campaign` (tools.py); re-anchor `select_target_users` (deliverables.py); a generic intervention-template fallback so `run_interventions`/emails/action-plan produce content on any levers; genericize `SYSTEM_PROMPT`; a canonical-data integration test proving no tool crashes on orders-only data.

**Out (later):** hand-authored per-lever email/intervention copy; the chat-first shell / dispatch ladder (Phase 7); grounded query tool (Phase 8); recipes (Phase 9); choosing the prod LLM host.

## Canonical vs Instacart columns (reference for all tasks)

- **Canonical features frame** (one row per customer, `user_id` after aliasing): always `recency_days, frequency, monetary, avg_order_value, tenure_days, avg_days_between_orders`; optionally `category_diversity, avg_basket_size, reorder_rate` (only when product-level data exists). `loyalty_score` appears after scoring.
- **Instacart-only names the tools currently hardcode (WILL crash on canonical):** `total_orders, reorder_rate, dept_diversity, avg_basket_size, total_items`.
- Session state already holds (from Phase 4): `features`, `available` (dict feature→bool), `active_levers` (list), `weights` (dict over active levers).

## File Structure

- **Create** `src/agent/tool_context.py` — pure column-resolution + labelling helper (no Streamlit).
- **Create** `tests/test_tool_context.py` — standalone unit test for the helper.
- **Create** `tests/test_tools_canonical.py` — `AppTest.from_string` integration test running the re-anchored tools on orders-only canonical data.
- **Modify** `src/agent/tools.py` — 6 tool functions read the helper instead of hardcoded columns.
- **Modify** `src/agent/deliverables.py` — dynamic target columns + churn/order columns; generic template in markdown builders.
- **Modify** `src/analysis/interventions.py` — add `template_for` generic fallback.
- **Modify** `src/config.py` — genericize `SYSTEM_PROMPT`.
- **Modify** `CLAUDE.md` — journal entry.

---

## Task 1: Pure column-resolution helper

**Files:**
- Create: `src/agent/tool_context.py`
- Test: `tests/test_tool_context.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tool_context.py — standalone script
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.agent import tool_context as tc

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

# canonical (orders-only) frame: core features, no optional
canon = pd.DataFrame({
    "user_id": [1, 2],
    "recency_days": [5, 40],
    "frequency": [10, 3],
    "monetary": [200.0, 50.0],
    "avg_order_value": [20.0, 16.7],
    "tenure_days": [100, 90],
    "avg_days_between_orders": [10.0, 30.0],
})
# instacart-style frame
insta = pd.DataFrame({
    "user_id": [1], "total_orders": [10], "reorder_rate": [0.5],
    "dept_diversity": [4], "avg_basket_size": [8.0], "total_items": [80],
})

ok(tc.feature_label("frequency") == "Order Frequency", "lever label from LEVER_LABELS")
ok(tc.feature_label("recency_days") == "Days Since Last Order", "core label")
ok(tc.feature_label("whatever_new") == "Whatever New", "fallback title-cases")

ok("user_id" not in tc.present_feature_cols(canon), "present cols drop user_id")
ok(tc.present_feature_cols(canon)[0] == "recency_days", "present cols keep frame order")

ok(tc.order_count_col(canon) == "frequency", "canonical order count = frequency")
ok(tc.order_count_col(insta) == "total_orders", "instacart order count = total_orders")
ok(tc.order_count_col(pd.DataFrame({"user_id": [1]})) is None, "no order col -> None")

ok(tc.churn_gap_col(canon) == "recency_days", "canonical churn col = recency_days")
ok(tc.churn_gap_col(insta) is None, "no churn col -> None")
ok(tc.churn_gap_col(pd.DataFrame({"user_id": [1], "avg_days_between_orders": [5.0]}))
   == "avg_days_between_orders", "avg-gap fallback")

stats = tc.summary_stats(canon, max_cols=3)
ok(len(stats) == 3, "summary_stats caps at max_cols")
ok(all(isinstance(v, float) for v in stats.values()), "summary_stats values are floats")
ok("Order Frequency" in stats, "summary_stats keys are labels")

print(f"test_tool_context: {checks} checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_tool_context.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.tool_context'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/agent/tool_context.py
"""Column resolution for the agent tools.

Pure (no Streamlit). Tools call these instead of hardcoding Instacart column
names, so they read whatever features the loaded dataset actually has — the
"never malfunctions on a client's data" rule, applied at the tool layer.
"""

from src.data.levers import LEVER_LABELS

# Labels for non-lever columns the tools display (levers come from LEVER_LABELS).
_EXTRA_LABELS = {
    "recency_days": "Days Since Last Order",
    "avg_days_between_orders": "Avg Days Between Orders",
    "total_orders": "Total Orders",
    "total_items": "Total Items",
    "dept_diversity": "Department Diversity",
    "loyalty_score": "Loyalty Score",
}

_NON_FEATURE = {"user_id"}


def feature_label(col):
    """Human label for a feature column (levers first, then extras, then title-case)."""
    return (LEVER_LABELS.get(col) or _EXTRA_LABELS.get(col)
            or col.replace("_", " ").title())


def present_feature_cols(features):
    """Feature columns actually in the frame (drops user_id), preserving order."""
    return [c for c in features.columns if c not in _NON_FEATURE]


def order_count_col(features):
    """Column representing how many orders a customer placed, or None."""
    for c in ("total_orders", "frequency"):
        if c in features.columns:
            return c
    return None


def churn_gap_col(features):
    """Column a churn/recency filter should use (recency first), or None."""
    for c in ("recency_days", "avg_days_between_orders"):
        if c in features.columns:
            return c
    return None


def summary_stats(features, cols=None, max_cols=4):
    """Mean of up to max_cols present numeric feature columns -> {label: float}."""
    cols = cols if cols is not None else present_feature_cols(features)
    out = {}
    for c in cols:
        if len(out) >= max_cols:
            break
        if c in features.columns:
            try:
                out[feature_label(c)] = round(float(features[c].mean()), 3)
            except (TypeError, ValueError):
                pass
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_tool_context.py`
Expected: PASS — `test_tool_context: 15 checks passed`

- [ ] **Step 5: Commit**

```bash
git add src/agent/tool_context.py tests/test_tool_context.py
git commit -m "feat: pure column-resolution helper for dataset-agnostic tools"
```

---

## Task 2: Canonical tool test harness + re-anchor run_scoring_analysis

**Files:**
- Create: `tests/test_tools_canonical.py`
- Modify: `src/agent/tools.py` (`run_scoring_analysis` weights)

- [ ] **Step 1: Write the failing test**

This test runs the app's real tools on an **orders-only canonical** dataset (core features only — the hardest degradation case) inside a real Streamlit runtime via `AppTest.from_string`. It grows one tool per task.

```python
# tests/test_tools_canonical.py — standalone script (real Streamlit runtime, no network)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest

# Script executed under a real runtime so st.session_state works and tools run
# for real on canonical (orders-only) data. Each tool's result is stashed in
# session_state["_r"] for the assertions below.
SCRIPT = r'''
import streamlit as st
import pandas as pd
from src.data.canonical import build_feature_matrix
from src.data.app_data import features_from_matrix

# Orders-only canonical dataset -> core features only (optional levers absent).
orders = pd.DataFrame({
    "customer_id": [1, 1, 1, 2, 2, 3, 3, 3, 3, 4],
    "order_id":    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "order_date": pd.to_datetime([
        "2024-01-01", "2024-01-10", "2024-01-25", "2024-02-01", "2024-03-01",
        "2024-01-05", "2024-01-06", "2024-01-20", "2024-02-15", "2024-01-02"]),
    "order_amount": [20.0, 25.0, 30.0, 10.0, 12.0, 40.0, 45.0, 50.0, 55.0, 5.0],
})
matrix = build_feature_matrix(orders)
features, available, active = features_from_matrix(matrix)
st.session_state["features"] = features
st.session_state["available"] = available
st.session_state["active_levers"] = active
st.session_state.setdefault("ui_history", [])

from src.agent import tools
r = st.session_state.setdefault("_r", {})
r["scoring"] = tools.run_scoring_analysis(50)   # 50% power split on tiny data
'''

def run():
    at = AppTest.from_string(SCRIPT, default_timeout=120)
    at.run()
    assert len(at.exception) == 0, f"tool crashed on canonical data: {[e.value for e in at.exception]}"
    return at

at = run()
r = at.session_state["_r"]
assert r["scoring"]["status"] == "success", f"scoring failed: {r['scoring']}"
assert r["scoring"]["power_user_count"] >= 1, "scoring produced power users on canonical data"
print("test_tools_canonical: run_scoring_analysis OK on canonical data")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: FAIL — an exception is captured because `run_scoring_analysis` builds `weights` from Instacart columns (`total_orders`, `reorder_rate`, …) absent here, so `score_users` scores on nothing / the assertion on `power_user_count` fails. (If it does not raise, the `status == "success"` + `power_user_count` assertion still fails because scoring over absent columns yields a degenerate frame.)

- [ ] **Step 3: Re-anchor `run_scoring_analysis` weights**

In `src/agent/tools.py`, replace the hardcoded default-weights block (currently lines ~61-67):

```python
    weights = st.session_state.get('weights', {
        'total_orders': 0.30,
        'reorder_rate': 0.25,
        'dept_diversity': 0.20,
        'avg_basket_size': 0.15,
        'total_items': 0.10
    })
```

with a dataset-driven default:

```python
    weights = st.session_state.get('weights')
    if not weights:
        from src.data import levers
        active = st.session_state.get('active_levers') or levers.SCORING_LEVERS
        weights = levers.default_weights(active)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: PASS — `test_tools_canonical: run_scoring_analysis OK on canonical data`

- [ ] **Step 5: Commit**

```bash
git add tests/test_tools_canonical.py src/agent/tools.py
git commit -m "feat: run_scoring_analysis uses dataset active levers, not Instacart weights"
```

---

## Task 3: Re-anchor get_current_stats

**Files:**
- Modify: `src/agent/tools.py` (`get_current_stats`)
- Test: extend `tests/test_tools_canonical.py`

- [ ] **Step 1: Extend the test (append the tool call in SCRIPT + an assertion)**

In `tests/test_tools_canonical.py`, add to the end of `SCRIPT` (after the scoring line):

```python
r["stats"] = tools.get_current_stats()
```

And after the existing scoring assertions, add:

```python
assert r["stats"]["data_loaded"] is True, "stats: data_loaded"
assert r["stats"]["scoring_complete"] is True, "stats: scoring done after scoring call"
assert isinstance(r["stats"].get("metrics"), dict) and r["stats"]["metrics"], \
    "stats: metrics dict computed over available features"
print("test_tools_canonical: get_current_stats OK on canonical data")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: FAIL — `get_current_stats` reads `features['total_orders'].mean()` / `features['reorder_rate'].mean()` → a captured `KeyError` (assertion `len(at.exception) == 0` fails).

- [ ] **Step 3: Re-anchor `get_current_stats`**

In `src/agent/tools.py`, replace the body that builds `result` (currently the block computing `avg_orders_per_user` / `avg_reorder_rate` around lines ~280-292) with an available-feature summary. Add the import at the top of the file (near the other `src.agent` imports):

```python
from src.agent import tool_context as tc
```

Then the `result` dict becomes:

```python
    result = {
        "data_loaded": True,
        "total_users": int(features['user_id'].nunique()),
        "metrics": tc.summary_stats(features),
        "scoring_complete": scored is not None,
        "segmentation_complete": power is not None,
        "happy_path_complete": 'paths' in st.session_state
    }
```

(Leave the trailing `if power is not None:` block that adds `power_users` / `power_user_pct` unchanged.)

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: PASS — prints the scoring + `get_current_stats` OK lines.

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools.py tests/test_tools_canonical.py
git commit -m "feat: get_current_stats summarizes available features, not Instacart columns"
```

---

## Task 4: Re-anchor analyze_churn_risk

**Files:**
- Modify: `src/agent/tools.py` (`analyze_churn_risk`)
- Test: extend `tests/test_tools_canonical.py`

- [ ] **Step 1: Extend the test**

Append to `SCRIPT`:

```python
r["churn"] = tools.analyze_churn_risk(20)
```

Add assertions:

```python
assert r["churn"]["status"] == "success", f"churn failed: {r['churn']}"
assert "total_at_risk" in r["churn"], "churn: total_at_risk present"
print("test_tools_canonical: analyze_churn_risk OK on canonical data")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: FAIL — the summary text and return read `at_risk['avg_days_between_orders'].mean()`; while `avg_days_between_orders` exists in core features, the churn flag itself is computed on `recency_days`, and the display must not assume the Instacart gap column. On an orders-only frame the current code still references a fixed column; make it use the resolved churn column. (The failing signal here is the missing dataset-agnostic field `at_risk_avg_gap`; the assertion additions plus the next task's message change drive it. If it already passes, keep the code change for correctness/robustness.)

- [ ] **Step 3: Re-anchor `analyze_churn_risk`**

In `src/agent/tools.py`, replace the summary line and the return field that hardcode `avg_days_between_orders`. Compute the gap from the resolved column:

Replace the at-risk avg-gap line inside `summary_text` (currently):

```python
        f"- At-risk avg gap: "
        f"**{at_risk['avg_days_between_orders'].mean():.0f} days** "
        f"between orders\n"
```

with:

```python
        f"{_at_risk_gap_line(at_risk)}"
```

Replace the return field (currently):

```python
        "at_risk_avg_gap_days": round(
            float(at_risk['avg_days_between_orders'].mean()), 1
        ),
```

with:

```python
        "at_risk_avg_gap": _at_risk_gap_value(at_risk),
```

Add these two small helpers just above `analyze_churn_risk`:

```python
def _at_risk_gap_line(at_risk):
    """One markdown line describing the at-risk group's churn signal, or ''."""
    col = tc.churn_gap_col(at_risk)
    if not col or len(at_risk) == 0:
        return ""
    return (f"- At-risk avg {tc.feature_label(col).lower()}: "
            f"**{at_risk[col].mean():.0f}**\n")


def _at_risk_gap_value(at_risk):
    """Numeric at-risk churn-signal average, or None if not computable."""
    col = tc.churn_gap_col(at_risk)
    if not col or len(at_risk) == 0:
        return None
    return round(float(at_risk[col].mean()), 1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: PASS — churn line prints.

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools.py tests/test_tools_canonical.py
git commit -m "feat: analyze_churn_risk reports the dataset's resolved churn column"
```

---

## Task 5: Re-anchor get_user_profile

**Files:**
- Modify: `src/agent/tools.py` (`get_user_profile`)
- Test: extend `tests/test_tools_canonical.py`

- [ ] **Step 1: Extend the test**

Append to `SCRIPT`:

```python
r["profile"] = tools.get_user_profile(1)
```

Add assertions:

```python
assert r["profile"]["status"] == "success", f"profile failed: {r['profile']}"
p = r["profile"]["profile"]
assert p["user_id"] == 1 and "segment" in p, "profile: id + segment"
assert "frequency" in p, "profile: includes an available canonical feature"
assert "total_orders" not in p, "profile: does not fabricate Instacart columns"
print("test_tools_canonical: get_user_profile OK on canonical data")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: FAIL — captured `KeyError: 'total_orders'` from the hardcoded profile dict.

- [ ] **Step 3: Re-anchor `get_user_profile`**

In `src/agent/tools.py`, replace the hardcoded `profile = { ... }` dict (currently the block reading `row['total_orders']` … `row['total_items']` with the fixed `segment`) with a dynamic build over present features:

```python
    import numpy as np
    profile = {"user_id": int(user_id)}
    for c in tc.present_feature_cols(features):
        val = row[c]
        if isinstance(val, (int, float, np.integer, np.floating)):
            profile[c] = round(float(val), 3)
        else:
            profile[c] = str(val)
    profile["segment"] = "Power User" if user_id in power_user_ids else "Regular User"
```

And the profile table construction (currently building `profile_df` with `k.replace('_', ' ').title()`) should use the shared label:

```python
    import pandas as pd
    profile_df = pd.DataFrame([{
        "Field": tc.feature_label(k) if k not in ("user_id", "segment")
                 else k.replace('_', ' ').title(),
        "Value": str(v)
    } for k, v in profile.items()])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: PASS — profile line prints.

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools.py tests/test_tools_canonical.py
git commit -m "feat: get_user_profile builds from available features, not fixed Instacart columns"
```

---

## Task 6: Re-anchor search_users

**Files:**
- Modify: `src/agent/tools.py` (`search_users`)
- Test: extend `tests/test_tools_canonical.py`

- [ ] **Step 1: Extend the test**

Append to `SCRIPT`:

```python
r["search"] = tools.search_users(min_orders=2, limit=5)
```

Add assertions:

```python
assert r["search"]["status"] in ("success", "no_results"), f"search failed: {r['search']}"
print("test_tools_canonical: search_users OK on canonical data")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: FAIL — captured `KeyError: 'total_orders'` from `df[df['total_orders'] >= min_orders]` and/or the hardcoded `display_cols`.

- [ ] **Step 3: Re-anchor `search_users`**

In `src/agent/tools.py`, inside `search_users`, replace the order-count filters (currently `if min_orders is not None: df = df[df['total_orders'] >= min_orders]` and the `max_orders` twin) with resolved-column versions:

```python
    order_col = tc.order_count_col(df)
    if min_orders is not None and order_col:
        df = df[df[order_col] >= min_orders]
    if max_orders is not None and order_col:
        df = df[df[order_col] <= max_orders]
```

Replace the two `reorder_rate` filters to guard on presence:

```python
    if min_reorder_rate is not None and 'reorder_rate' in df.columns:
        df = df[df['reorder_rate'] >= min_reorder_rate]
    if max_reorder_rate is not None and 'reorder_rate' in df.columns:
        df = df[df['reorder_rate'] <= max_reorder_rate]
```

Replace the hardcoded `display_cols` block (currently `['user_id', 'total_orders', 'reorder_rate', 'dept_diversity', 'avg_basket_size', 'segment']` + the `loyalty_score` insert) with dynamic columns:

```python
    feat_cols = [c for c in tc.present_feature_cols(features)
                 if c in result.columns][:5]
    display_cols = ['user_id'] + feat_cols + ['segment']
    if 'loyalty_score' in result.columns and 'loyalty_score' not in display_cols:
        display_cols.insert(-1, 'loyalty_score')
```

Replace the summary `avg_orders` field (currently `round(float(df['total_orders'].mean()), 1)`) with a guarded resolved-column version:

```python
        "avg_orders": (round(float(df[order_col].mean()), 1)
                       if order_col and len(df) else None),
```

And guard the `avg_reorder_rate` field similarly:

```python
        "avg_reorder_rate": (round(float(df['reorder_rate'].mean()), 3)
                             if 'reorder_rate' in df.columns and len(df) else None),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: PASS — search line prints.

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools.py tests/test_tools_canonical.py
git commit -m "feat: search_users filters/displays resolved columns, not Instacart names"
```

---

## Task 7: Re-anchor simulate_campaign onto active levers

**Files:**
- Modify: `src/agent/tools.py` (`simulate_campaign`)
- Test: extend `tests/test_tools_canonical.py`

- [ ] **Step 1: Extend the test**

Append to `SCRIPT` (after scoring has set `weights`/`top_pct`; add a weights line to be safe):

```python
st.session_state.setdefault("weights", None)
r["sim_bad"] = tools.simulate_campaign("total_items", 10)   # not an active lever here
r["sim_ok"] = tools.simulate_campaign("frequency", 10)      # an active canonical lever
```

Add assertions:

```python
assert "error" in r["sim_bad"], "sim rejects a lever absent from this dataset"
assert r["sim_ok"].get("conversions") is not None, f"sim ran on an active lever: {r['sim_ok']}"
print("test_tools_canonical: simulate_campaign OK on canonical data")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: FAIL — `simulate_campaign` validates `feature` against `simulation.LEVERS` (Instacart five), so `"frequency"` is rejected as "not simulatable" (the `sim_ok` assertion fails), and `"total_items"` is wrongly accepted then crashes in the engine on the missing column.

- [ ] **Step 3: Re-anchor `simulate_campaign`**

In `src/agent/tools.py`, inside `simulate_campaign`, replace the lever set used for validation and the engine call. Change the validation block (currently `if feature not in simulation.LEVERS:` … listing `simulation.LEVERS`) to use the dataset's active levers:

```python
    active = st.session_state.get('active_levers') or simulation.LEVERS
    if feature not in active:
        return {
            "error": f"'{feature}' is not a simulatable lever for this dataset.",
            "instruction": (
                "Tell the user simulation only supports these levers: "
                + ", ".join(active) + "."
            ),
        }
```

And pass the active levers to the engine (currently `simulation.simulate_campaign(features, weights, top_pct, feature, lift_pct)`):

```python
    result = simulation.simulate_campaign(
        features, weights, top_pct, feature, lift_pct, levers=active
    )
```

(`weights` here is the session `weights`; on canonical it is the dynamic active-lever weights from Phase 4. The `if features is None or weights is None …` guard above already handles an unscored state.)

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: PASS — simulate line prints.

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools.py tests/test_tools_canonical.py
git commit -m "feat: simulate_campaign validates against dataset active levers"
```

---

## Task 8: Re-anchor deliverables.select_target_users

**Files:**
- Modify: `src/agent/deliverables.py` (`select_target_users`, `_TARGET_COLS`)
- Test: extend `tests/test_tools_canonical.py`

- [ ] **Step 1: Extend the test**

Append to `SCRIPT`:

```python
r["target"] = tools.export_target_list(segment="power", limit=10)
```

Add assertions:

```python
assert r["target"]["status"] in ("success", "no_results"), f"export failed: {r['target']}"
print("test_tools_canonical: export_target_list OK on canonical data")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: FAIL — `select_target_users` returns `df[_TARGET_COLS]` where `_TARGET_COLS` names Instacart columns → captured `KeyError`.

- [ ] **Step 3: Re-anchor `select_target_users`**

In `src/agent/deliverables.py`, add the helper import at the top (after `import pandas as pd`):

```python
from src.agent import tool_context as tc
```

Delete the module-level `_TARGET_COLS` list. Replace the filter + column-selection body of `select_target_users` so it resolves columns:

```python
def select_target_users(features, scored_df, power_user_ids,
                        segment=None, min_orders=None,
                        churn_days=None, limit=500):
    """Filter the feature matrix into a target list DataFrame.

    Column-agnostic: filters use the dataset's resolved order-count / churn
    columns and the export includes whatever features are present.
    """
    df = features.copy()
    if scored_df is not None:
        df = df.merge(
            scored_df[['user_id', 'loyalty_score']], on='user_id', how='left'
        )
    order_col = tc.order_count_col(df)
    if min_orders is not None and order_col:
        df = df[df[order_col] >= min_orders]
    gap_col = tc.churn_gap_col(df)
    if churn_days is not None and gap_col:
        df = df[df[gap_col] >= churn_days]
    if segment is not None:
        s = str(segment).lower()
        if 'power' in s:
            df = df[df['user_id'].isin(power_user_ids)]
        elif 'regular' in s:
            df = df[~df['user_id'].isin(power_user_ids)]

    df = df.copy()
    df['segment'] = df['user_id'].apply(
        lambda u: 'Power User' if u in power_user_ids else 'Regular User'
    )
    feat_cols = [c for c in tc.present_feature_cols(df) if c != 'segment']
    cols = ['user_id'] + [c for c in feat_cols if c != 'user_id'] + ['segment']
    return df[cols].head(int(limit)).round(3).reset_index(drop=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Expected: PASS — export line prints.

Also run the existing deliverables unit test to confirm the pure builder still works on Instacart-shaped input:

Run: `..\venv\Scripts\python.exe tests\test_deliverables.py`
Expected: PASS (existing checks). If it asserted on the old fixed `_TARGET_COLS` ordering, update those assertions to check membership (`'user_id' in cols`, `'segment' in cols`) rather than exact list equality.

- [ ] **Step 5: Commit**

```bash
git add src/agent/deliverables.py tests/test_tools_canonical.py
git commit -m "feat: select_target_users exports resolved columns for any dataset"
```

---

## Task 9: Generic intervention-template fallback

**Files:**
- Modify: `src/analysis/interventions.py` (add `template_for`)
- Modify: `src/agent/tools.py` (`run_interventions` uses `template_for`)
- Modify: `src/agent/deliverables.py` (`campaign_emails_markdown`, `action_plan_markdown` use `template_for`)
- Test: `tests/test_interventions_generic.py` (create) + extend `tests/test_tools_canonical.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_interventions_generic.py — standalone script
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.analysis.interventions import template_for, INTERVENTION_TEMPLATES

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

# a canonical lever with no hand-authored template still gets a usable one
t = template_for("monetary")
ok(set(("icon", "title", "what", "who", "action", "message")).issubset(t), "generic has all fields")
ok("Total Spend" in t["title"], "generic title uses the lever label")
# the format placeholders the consumers pass must not blow up
_ = t["what"].format(ru=1.0, pu=2.0)
_ = t["who"].format(mid=1.5, count=10, ru=1.0, pu=2.0)
ok(True, "generic template survives the consumers' .format kwargs")

# a known Instacart column returns its specific template unchanged
if "reorder_rate" in INTERVENTION_TEMPLATES:
    ok(template_for("reorder_rate") is INTERVENTION_TEMPLATES["reorder_rate"],
       "known column keeps its specific template")

print(f"test_interventions_generic: {checks} checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_interventions_generic.py`
Expected: FAIL — `ImportError: cannot import name 'template_for'`.

- [ ] **Step 3: Add `template_for` and wire the consumers**

In `src/analysis/interventions.py`, add at the bottom:

```python
from src.data.levers import LEVER_LABELS


def template_for(col, templates=None):
    """Return a campaign template for a feature column.

    Uses the hand-authored INTERVENTION_TEMPLATES when one exists, else a generic
    template built from the lever's label so campaigns/emails/action-plans work on
    any dataset's levers (not just the Instacart columns).
    """
    templates = INTERVENTION_TEMPLATES if templates is None else templates
    if col in templates:
        return templates[col]
    label = LEVER_LABELS.get(col, col.replace("_", " ").title())
    low = label.lower()
    return {
        "icon": "📈",
        "title": f"Grow {label}",
        "what": f"Power users show markedly higher {low} than regular customers.",
        "who": "Target {count} regular users below the midpoint.",
        "action": f"Run a campaign that nudges customers to increase their {low}.",
        "message": f"A small lift in {low} moves regulars toward power-user value.",
    }
```

In `src/agent/tools.py` `run_interventions`, change the loop so it always resolves a template (remove the `col not in INTERVENTION_TEMPLATES` skip). Add the import near the top:

```python
from src.analysis.interventions import template_for
```

Replace the guard + lookup (currently `if shown >= 4 or col not in INTERVENTION_TEMPLATES: continue` then `t = INTERVENTION_TEMPLATES[col]`) with:

```python
        if shown >= 4:
            continue
        t = template_for(col)
```

In `src/agent/deliverables.py`, import `template_for` at the top:

```python
from src.analysis.interventions import template_for
```

In `campaign_emails_markdown`, replace `if shown >= max_campaigns or col not in templates: continue` + `t = templates[col]` with:

```python
        if shown >= max_campaigns:
            continue
        t = template_for(col, templates)
```

In `action_plan_markdown`, replace `if shown >= max_items or col not in templates: continue` + `t = templates[col]` with:

```python
        if shown >= max_items:
            continue
        t = template_for(col, templates)
```

- [ ] **Step 4: Extend the canonical test + run everything**

In `tests/test_tools_canonical.py`, append to `SCRIPT`:

```python
r["interventions"] = tools.run_interventions()
r["emails"] = tools.draft_campaign_emails()
r["plan"] = tools.build_action_plan(20)
```

Add assertions:

```python
assert r["interventions"]["status"] == "success", f"interventions failed: {r['interventions']}"
assert r["interventions"]["campaigns_generated"] >= 1, "interventions produced content on canonical levers"
assert r["emails"]["status"] == "success", f"emails failed: {r['emails']}"
assert r["plan"]["status"] == "success", f"plan failed: {r['plan']}"
print("test_tools_canonical: interventions/emails/plan OK on canonical data")
```

Run: `..\venv\Scripts\python.exe tests\test_interventions_generic.py`
Then: `..\venv\Scripts\python.exe tests\test_tools_canonical.py`
Then: `..\venv\Scripts\python.exe tests\test_deliverables.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add src/analysis/interventions.py src/agent/tools.py src/agent/deliverables.py tests/test_interventions_generic.py tests/test_tools_canonical.py
git commit -m "feat: generic intervention template fallback so campaigns work on any levers"
```

---

## Task 10: Genericize SYSTEM_PROMPT

**Files:**
- Modify: `src/config.py` (`SYSTEM_PROMPT`)
- Test: `tests/test_system_prompt.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_system_prompt.py — standalone script
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

sp = config.SYSTEM_PROMPT
ok("Instacart" not in sp, "prompt names no specific dataset")
ok("206,209" not in sp, "prompt hardcodes no dataset row count")
ok("department" not in sp.lower(), "prompt assumes no Instacart-only department field")
# still describes the tools + grounding
for tool_name in ("run_scoring_analysis", "analyze_churn_risk", "get_current_stats"):
    ok(tool_name in sp, f"prompt still lists the {tool_name} tool")
ok("loyalty_score" in sp, "prompt still explains the loyalty score")

print(f"test_system_prompt: {checks} checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_system_prompt.py`
Expected: FAIL — the current prompt contains "Instacart", "206,209", and "department".

- [ ] **Step 3: Genericize `SYSTEM_PROMPT`**

In `src/config.py`, replace the `SYSTEM_PROMPT = """ … """` value with a dataset-agnostic version. Keep the tool catalog and the tools-vs-answer guidance verbatim; only the top "DATA AVAILABLE" framing changes:

```python
SYSTEM_PROMPT = """
You are the Customer Loyalty Intelligence Agent for an e-commerce business.
You analyze the loaded customer dataset — which varies by client — and turn it
into loyalty insight and action.

DATA AVAILABLE:
One row per customer, with loyalty-relevant behavioral features. Which features
exist depends on the dataset, and may include: order frequency, total spend,
average order value, recency (days since last order), tenure, and — when
product-level data is present — category diversity, basket size, and reorder
rate. After scoring, each customer also has loyalty_score (0-100).

Do NOT assume a feature exists. The tools compute over whatever the dataset
actually has and will tell you when a feature is unavailable; relay that plainly
rather than inventing a number.

Segments: "power users" = top N% by loyalty score. "regular users" = everyone else.

YOUR TOOLS:
1. run_scoring_analysis(top_percentile)
   Use when: user wants to score, rank, or find top customers.

2. run_segmentation()
   Use when: user asks what makes top customers different,
   behavioral gaps, feature comparisons.

3. run_happy_path(lookback_orders)
   Use when: user asks about customer journeys, conversion
   paths, what sequence of behaviors leads to loyalty.

4. run_interventions()
   Use when: user asks about campaigns, what to do next,
   marketing actions, growth tactics, how to convert users.

5. analyze_churn_risk(churn_days)
   Use when: user asks about churn, at-risk users,
   win-back, retention, inactive customers.

6. get_user_profile(user_id)
   Use when: user mentions a specific user_id or wants
   to understand an individual customer.

7. search_users(min_orders, max_orders, min_reorder_rate,
   max_reorder_rate, segment, limit)
   Use when: user asks to find or list customers matching
   specific behavioral conditions.

8. get_current_stats()
   Use when: user asks what has been analyzed, current
   results, or a status update.

WHEN TO USE TOOLS VS ANSWER DIRECTLY:
Use a tool when user asks to RUN, FIND, SHOW, or CALCULATE.

Answer directly (no tool) when:
- User asks a conceptual question (e.g. "what is reorder rate?")
- User asks to interpret a result already shown
- User asks for a recommendation on what to do next
- User asks to explain a term or methodology

If a question is ambiguous, ask ONE clarifying question.

RESPONSE FORMAT:
- After an analysis: 3 bullet insights with bold numbers,
  then 1 suggested next step.
- For direct Q&A: 2-3 sentences, specific, tied to an action.
- Never say "I don't have access to that" without first
  checking whether a tool could retrieve it.

TONE: Expert business consultant. Every number connects
to an action. Never vague.
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_system_prompt.py`
Expected: PASS — `test_system_prompt: 6 checks passed`

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_system_prompt.py
git commit -m "feat: dataset-agnostic system prompt (no hardcoded Instacart framing)"
```

---

## Task 11: Full suite + boot + journal

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run every no-network suite**

```
..\venv\Scripts\python.exe tests\test_tool_context.py
..\venv\Scripts\python.exe tests\test_tools_canonical.py
..\venv\Scripts\python.exe tests\test_interventions_generic.py
..\venv\Scripts\python.exe tests\test_system_prompt.py
..\venv\Scripts\python.exe tests\test_deliverables.py
..\venv\Scripts\python.exe tests\test_tool_specs.py
..\venv\Scripts\python.exe tests\test_tool_loop.py
..\venv\Scripts\python.exe tests\test_providers.py
..\venv\Scripts\python.exe tests\test_config.py
..\venv\Scripts\python.exe tests\test_call_agent_boot.py
..\venv\Scripts\python.exe tests\test_persistence.py
..\venv\Scripts\python.exe tests\test_levers.py
..\venv\Scripts\python.exe tests\test_app_data.py
..\venv\Scripts\python.exe tests\test_metrics.py
..\venv\Scripts\python.exe tests\test_scoring.py
..\venv\Scripts\python.exe tests\test_simulation.py
..\venv\Scripts\python.exe tests\test_canonical.py
..\venv\Scripts\python.exe tests\test_demo_adapter.py
..\venv\Scripts\python.exe tests\test_router.py
..\venv\Scripts\python.exe tests\test_reflexive.py
..\venv\Scripts\python.exe tests\test_orchestrator.py
..\venv\Scripts\python.exe tests\test_insights.py
..\venv\Scripts\python.exe tests\test_proactive.py
..\venv\Scripts\python.exe tests\test_watches.py
..\venv\Scripts\python.exe tests\test_memory.py
```
Expected: every script prints its pass line and exits 0.

- [ ] **Step 2: Boot smoke test**

Run: `..\venv\Scripts\python.exe tests\test_call_agent_boot.py`
Expected: PASS — app boots with 0 exceptions on canonical data.

- [ ] **Step 3: Add the journal entry**

Prepend to the Project Journal in `CLAUDE.md` a `### 2026-07-07 — Intelligence Layer / Chat-First, Phase 5: Re-anchor agent tools on canonical levers` entry summarizing: new pure `tool_context.py` (column resolution/labelling); the 6 re-anchored tools + `select_target_users`; the generic `template_for` fallback so campaigns/emails/action-plans work on any levers; the dataset-agnostic `SYSTEM_PROMPT`; the new `test_tools_canonical.py` proving no tool crashes on orders-only canonical data. Note that default (Instacart demo) behavior is unchanged and that this closes the Phase-4 caveat ("agent tools still Instacart-bound").

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: journal entry for Phase 5 tool re-anchoring"
```

---

## Self-Review notes (author)

- **Spec coverage:** re-anchor tools ✅ (T2–T8); minimal degradation messaging ✅ (resolved-column helpers return None / skip + relayable instructions, T3–T8; system prompt tells the LLM to relay unavailability, T10); campaigns work on any levers ✅ (T9); crash-proof proof on client-shaped data ✅ (T2's `test_tools_canonical.py`, grown each task). Out-of-scope items (rich copy, chat-first shell, query tool, recipes) explicitly deferred.
- **Type/signature consistency:** helper API (`feature_label`, `present_feature_cols`, `order_count_col`, `churn_gap_col`, `summary_stats`) defined in T1 and used unchanged in T3–T8; `template_for(col, templates=None)` defined in T9 and called with matching signatures in tools.py + deliverables.py; `simulation.simulate_campaign(..., levers=None)` already exists (Phase 4) and is passed `levers=active` in T7.
- **Risks flagged for execution:** (1) `AppTest.from_string` must exist in the installed Streamlit; if not, switch `test_tools_canonical.py` to write the SCRIPT to a temp file and use `AppTest.from_file`. (2) tiny-dataset scoring (4 customers, 50% split) must yield ≥1 power user — the fixture is sized so it does; adjust `top_percentile` if `get_power_users` rounds to zero. (3) `test_deliverables.py` may assert the old fixed `_TARGET_COLS`; T8 Step 4 updates those to membership checks.
```
