# Phase 4 — What-If Simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a grounded campaign simulator — the agent can project how many regular users a single-feature behavioral lift would convert into power users.

**Architecture:** Freeze the baseline scoring scaler (refactor `score_users` into `compute_scaler` + `apply_scoring`), then a pure `simulation.simulate_campaign` re-scores lifted regulars against the original cutoff to count conversions. A thin `simulate_campaign` tool exposes it to chat (`ALL_TOOLS`) and Autopilot (`TOOL_REGISTRY`). The LLM only narrates; the engine computes every number.

**Tech Stack:** Python, pandas, Streamlit (tool layer only), standalone test scripts (not pytest), Gemini function-calling. No new dependencies.

---

## Conventions (read once)

- **Tests are standalone scripts**, not pytest. Each defines `check(name, cond)` that prints `PASS`/`FAIL` and `sys.exit(1)` on failure (copy the harness shown in Task 1).
- **Run tests** from the inner project dir (`customer-loyalty-agent/customer-loyalty-agent/`):
  `..\venv\Scripts\python.exe tests/test_simulation.py`
- **Keep `src/analysis/` Streamlit-free** (pure pandas). The tool layer (`src/agent/tools.py`) uses Streamlit and needs the runtime, so it is syntax-checked + registration-verified rather than unit-tested (same approach Phase 3 used for `tools.py`).
- **No "Co-Authored-By: Claude" trailer** on any commit (repo convention). Attribute solely to the user.
- **The 5 weighted scoring features** (the only valid levers): `total_orders`, `reorder_rate`, `dept_diversity`, `avg_basket_size`, `total_items`. `avg_days_between_orders` is intentionally excluded.
- **Existing scoring math** (`src/analysis/scoring.py`): per-feature cap at the 95th percentile, clip to cap, normalize to 0–100, weighted sum = `raw_score`, then `loyalty_score = raw_score / max(raw_score) * 100` rounded to 2 dp, sorted descending. The refactor must preserve this exactly.

---

## File Structure

- **Modify** `src/analysis/scoring.py` — extract `compute_scaler` + `apply_scoring`; `score_users` delegates (behavior-identical).
- **Create** `tests/test_scoring.py` — guards the refactor + the frozen-scaler property.
- **Create** `src/analysis/simulation.py` — `LEVERS` constant + `simulate_campaign` engine (pure).
- **Create** `tests/test_simulation.py` — engine behavior.
- **Modify** `src/agent/tools.py` — `simulate_campaign` tool; add to `ALL_TOOLS`.
- **Modify** `src/agent/orchestrator.py` — register the tool in `TOOL_REGISTRY`.
- **Modify** `CLAUDE.md` — dated Project Journal entry.

---

## Task 1: Refactor scoring into a freezable scaler

Split the scaler out so the simulator can reuse the baseline's caps + normalizer. `score_users` must behave identically.

**Files:**
- Modify: `src/analysis/scoring.py`
- Test: `tests/test_scoring.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_scoring.py`:

```python
"""Standalone tests for src/analysis/scoring.py scaler refactor. No network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.analysis.scoring import (
    compute_scaler, apply_scoring, score_users, get_power_users,
)

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


WEIGHTS = {"total_orders": 0.30, "reorder_rate": 0.25, "dept_diversity": 0.20,
           "avg_basket_size": 0.15, "total_items": 0.10}


def _features():
    return pd.DataFrame({
        "user_id":         list(range(1, 11)),
        "total_orders":    [50, 45, 40, 35, 30, 25, 20, 15, 10, 5],
        "reorder_rate":    [0.9, 0.85, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
        "dept_diversity":  [18, 16, 15, 13, 11, 9, 7, 6, 4, 3],
        "avg_basket_size": [14, 13, 12, 11, 10, 8, 7, 6, 5, 4],
        "total_items":     [600, 500, 450, 380, 300, 240, 180, 120, 70, 30],
    })


def main():
    f = _features()

    # compute_scaler returns caps for each weighted feature + a max_raw
    scaler = compute_scaler(f, WEIGHTS)
    check("scaler has caps", set(scaler["caps"].keys()) == set(WEIGHTS.keys()))
    check("scaler has positive max_raw", scaler["max_raw"] > 0)

    # score_users == apply_scoring(compute_scaler(...)) exactly
    su = score_users(f, WEIGHTS).set_index("user_id")["loyalty_score"]
    ap = apply_scoring(f, WEIGHTS, compute_scaler(f, WEIGHTS)).set_index("user_id")["loyalty_score"]
    check("score_users equals apply_scoring", (su == ap).all())

    # regression tripwire: top scorer normalizes to exactly 100
    check("top score is 100", su.max() == 100.0)

    # frozen-scaler property: lifting one user does NOT change an untouched user's score
    base = apply_scoring(f, WEIGHTS, scaler).set_index("user_id")["loyalty_score"]
    g = f.copy()
    g.loc[g["user_id"] == 9, "total_orders"] = 999      # bump only user 9
    lifted = apply_scoring(g, WEIGHTS, scaler).set_index("user_id")["loyalty_score"]
    check("untouched user score unchanged under frozen scaler",
          base.loc[1] == lifted.loc[1])
    check("bumped user score increased", lifted.loc[9] > base.loc[9])

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run, confirm it FAILS** (no `compute_scaler`/`apply_scoring` yet):

Run: `..\venv\Scripts\python.exe tests/test_scoring.py`
Expected: FAIL — `ImportError: cannot import name 'compute_scaler'`.

- [ ] **Step 3: Implement the refactor** in `src/analysis/scoring.py`. Replace the existing `score_users` function (lines defining `def score_users(...)` through its `return`) with these THREE functions (leave `get_power_users` and `get_thresholds` untouched):

```python
def compute_scaler(features: pd.DataFrame, weights: dict):
    """Fit the scoring scaler from a baseline population.

    Returns {"caps": {col: 95th-pctile cap}, "max_raw": float} — the parameters
    that make loyalty scores comparable. Freeze these to score a hypothetical
    population on the same yardstick (see src/analysis/simulation.py).
    """
    df = features.copy()
    caps = {}
    raw = pd.Series(0.0, index=df.index)
    for col, weight in weights.items():
        if col in df.columns:
            cap = df[col].quantile(0.95)
            caps[col] = cap
            if cap > 0:
                normalized = (df[col].clip(upper=cap) / cap) * 100
            else:
                normalized = pd.Series(0.0, index=df.index)
            raw += normalized * float(weight)
    return {"caps": caps, "max_raw": float(raw.max())}


def apply_scoring(features: pd.DataFrame, weights: dict, scaler: dict):
    """Score users with a *provided* scaler (caps + max_raw).

    Same math as the original score_users, but using the frozen scaler instead of
    deriving it from `features`. Returns the df with `raw_score`/`loyalty_score`,
    sorted by loyalty_score descending.
    """
    df = features.copy()
    df['raw_score'] = 0.0
    caps = scaler.get("caps", {})
    for col, weight in weights.items():
        if col in df.columns:
            cap = caps.get(col)
            if cap is None:
                cap = df[col].quantile(0.95)
            if cap and cap > 0:
                normalized = (df[col].clip(upper=cap) / cap) * 100
            else:
                normalized = pd.Series(0.0, index=df.index)
            df['raw_score'] += normalized * float(weight)

    max_raw = scaler.get("max_raw")
    if max_raw and max_raw > 0:
        df['loyalty_score'] = (df['raw_score'] / max_raw * 100).round(2)
    else:
        df['loyalty_score'] = 0.0

    return df.sort_values('loyalty_score', ascending=False)


def score_users(features: pd.DataFrame, weights: dict):
    """Score every user 0-100 using weighted features.

    Thin wrapper: fit the scaler from this population, then apply it. Behavior is
    identical to the original single-function implementation.
    """
    scaler = compute_scaler(features, weights)
    return apply_scoring(features, weights, scaler)
```

- [ ] **Step 4: Run, confirm ALL checks PASS:**

Run: `..\venv\Scripts\python.exe tests/test_scoring.py`
Expected: PASS — "7 checks passed."

- [ ] **Step 5: Run the downstream suites to prove the refactor broke nothing:**

```
..\venv\Scripts\python.exe tests/test_insights.py
..\venv\Scripts\python.exe tests/test_orchestrator.py
..\venv\Scripts\python.exe tests/test_reflexive.py
```
Expected: all PASS.

- [ ] **Step 6: Commit:**

```bash
git add src/analysis/scoring.py tests/test_scoring.py
git commit -m "Phase 4: refactor scoring into freezable compute_scaler + apply_scoring"
```

---

## Task 2: The simulation engine

Pure engine that lifts one feature for regular users and counts conversions against the frozen baseline cutoff.

**Files:**
- Create: `src/analysis/simulation.py`
- Test: `tests/test_simulation.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_simulation.py`:

```python
"""Standalone tests for src/analysis/simulation.py. No network, no Streamlit."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.analysis import simulation as sim

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


WEIGHTS = {"total_orders": 0.30, "reorder_rate": 0.25, "dept_diversity": 0.20,
           "avg_basket_size": 0.15, "total_items": 0.10}


def _features():
    return pd.DataFrame({
        "user_id":         list(range(1, 11)),
        "total_orders":    [50, 45, 40, 35, 30, 25, 20, 15, 10, 5],
        "reorder_rate":    [0.9, 0.85, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
        "dept_diversity":  [18, 16, 15, 13, 11, 9, 7, 6, 4, 3],
        "avg_basket_size": [14, 13, 12, 11, 10, 8, 7, 6, 5, 4],
        "total_items":     [600, 500, 450, 380, 300, 240, 180, 120, 70, 30],
    })


def main():
    f = _features()

    # --- LEVERS: exactly the 5 weighted features, excludes days-between-orders ---
    check("LEVERS has 5", len(sim.LEVERS) == 5)
    check("LEVERS excludes days", "avg_days_between_orders" not in sim.LEVERS)
    check("LEVERS == weight keys", set(sim.LEVERS) == set(WEIGHTS.keys()))

    # --- zero lift converts nobody; projected == baseline ---
    r0 = sim.simulate_campaign(f, WEIGHTS, 20, "total_orders", 0)
    check("zero lift -> 0 conversions", r0["conversions"] == 0)
    check("zero lift -> projected == baseline",
          r0["projected_power_count"] == r0["baseline_power_count"])
    check("result reports the feature", r0["feature"] == "total_orders")

    # --- a large lift converts at least one regular ---
    r100 = sim.simulate_campaign(f, WEIGHTS, 20, "total_orders", 100)
    check("big lift -> >=1 conversion", r100["conversions"] >= 1)
    check("projected == baseline + conversions",
          r100["projected_power_count"]
          == r100["baseline_power_count"] + r100["conversions"])
    check("after avg > before avg for positive lift",
          r100["feature_avg_after"] > r100["feature_avg_before"])

    # --- monotonicity: more lift never converts fewer ---
    seq = [sim.simulate_campaign(f, WEIGHTS, 20, "total_orders", p)["conversions"]
           for p in (0, 25, 50, 100)]
    check("conversions monotonic non-decreasing",
          all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1)))

    # --- reorder_rate is clipped to <= 1.0 even under a huge lift ---
    rr = sim.simulate_campaign(f, WEIGHTS, 20, "reorder_rate", 100)
    check("reorder_rate avg after stays <= 1.0", rr["feature_avg_after"] <= 1.0)

    # --- result dict shape ---
    for key in ("feature", "lift_pct", "target_count", "conversions",
                "baseline_power_count", "projected_power_count",
                "projected_power_pct", "feature_avg_before",
                "feature_avg_after", "cutoff"):
        check(f"result has {key}", key in r100)

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run, confirm it FAILS** (no module yet):

Run: `..\venv\Scripts\python.exe tests/test_simulation.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.simulation'`.

- [ ] **Step 3: Implement** — create `src/analysis/simulation.py`:

```python
"""
What-If Simulation — campaign behavioral-lift projection.

Pure Python (no Streamlit, no LLM), per the src/analysis convention. Lifts a
single feature for regular (non-power) users and counts how many would cross the
baseline power-user cutoff, using a FROZEN baseline scaler so scores stay
comparable (see compute_scaler/apply_scoring in scoring.py). Every number is
deterministic; the LLM only narrates the result.
"""

from src.analysis.scoring import compute_scaler, apply_scoring, get_power_users

# The only simulatable levers: the 5 weighted scoring features. Higher = better
# for all of them. avg_days_between_orders is excluded (no scoring weight; it is
# the only "lower = better" feature and belongs to churn, not loyalty score).
LEVERS = ["total_orders", "reorder_rate", "dept_diversity",
          "avg_basket_size", "total_items"]


def simulate_campaign(features, weights, top_pct, feature, lift_pct):
    """Project a single-feature campaign lift on regular users.

    Returns a deterministic dict of conversions + key deltas. Assumes `feature`
    is a valid lever (validated at the tool layer) and `features` is one row per
    user with a `user_id` column.
    """
    # 1. Freeze the baseline scaler + cutoff.
    scaler = compute_scaler(features, weights)
    baseline = apply_scoring(features, weights, scaler)
    power, regular, cutoff = get_power_users(baseline, top_pct)

    total_users = len(features)
    baseline_power_count = len(power)
    regular_ids = set(regular["user_id"])

    # 2. Apply the lift to regular users only.
    lifted = features.copy()
    mask = lifted["user_id"].isin(regular_ids)
    before_avg = float(lifted.loc[mask, feature].mean()) if mask.any() else 0.0
    lifted.loc[mask, feature] = lifted.loc[mask, feature] * (1 + lift_pct / 100.0)
    if feature == "reorder_rate":
        lifted.loc[mask, feature] = lifted.loc[mask, feature].clip(upper=1.0)
    after_avg = float(lifted.loc[mask, feature].mean()) if mask.any() else 0.0

    # 3. Re-score with the FROZEN scaler so scores stay comparable.
    lifted_scored = apply_scoring(lifted, weights, scaler)

    # 4. Conversions = regulars whose new score clears the original cutoff.
    conv_mask = (lifted_scored["user_id"].isin(regular_ids)
                 & (lifted_scored["loyalty_score"] >= cutoff))
    conversions = int(conv_mask.sum())
    projected_power_count = baseline_power_count + conversions
    projected_power_pct = (round(projected_power_count / total_users * 100, 1)
                           if total_users else 0.0)

    return {
        "feature": feature,
        "lift_pct": lift_pct,
        "target_count": int(mask.sum()),
        "conversions": conversions,
        "baseline_power_count": baseline_power_count,
        "projected_power_count": projected_power_count,
        "projected_power_pct": projected_power_pct,
        "feature_avg_before": round(before_avg, 4),
        "feature_avg_after": round(after_avg, 4),
        "cutoff": round(float(cutoff), 2),
    }
```

- [ ] **Step 4: Run, confirm ALL checks PASS:**

Run: `..\venv\Scripts\python.exe tests/test_simulation.py`
Expected: PASS — all checks pass.

- [ ] **Step 5: Commit:**

```bash
git add src/analysis/simulation.py tests/test_simulation.py
git commit -m "Phase 4: campaign simulation engine (simulate_campaign)"
```

---

## Task 3: The `simulate_campaign` agent tool

Thin Streamlit wrapper: validate inputs, call the engine, render a card, return a narration instruction.

**Files:**
- Modify: `src/agent/tools.py`

- [ ] **Step 1: Add the import.** In `src/agent/tools.py`, near the other analysis imports at the top (e.g. after `from src.analysis.metrics import calculate_churn_risk`), add:

```python
from src.analysis import simulation
```

- [ ] **Step 2: Add the tool function.** Insert this function ABOVE the `# All tools Gemini can call` / `ALL_TOOLS = [` block near the end of the file:

```python
def simulate_campaign(feature: str, lift_pct: float) -> dict:
    """
    Projects a what-if campaign: lift ONE behavioral feature for regular users by
    a percentage and count how many would cross the loyalty bar into power-user
    status. Deterministic — re-scores against the frozen baseline.

    Use this when the user asks "what if", to forecast/simulate/project the impact
    of a campaign, or asks how many regular users a behavioral improvement would
    convert.

    Args:
        feature: which feature to lift. One of: total_orders, reorder_rate,
                 dept_diversity, avg_basket_size, total_items.
        lift_pct: percentage increase to apply (0-200), e.g. 15 for +15%.
    """
    features = st.session_state.get('features')
    weights = st.session_state.get('weights')
    if features is None or weights is None:
        return {
            "error": "Data not loaded yet.",
            "instruction": "Tell the user to load data / run scoring first.",
        }

    if feature not in simulation.LEVERS:
        return {
            "error": f"'{feature}' is not a simulatable feature.",
            "instruction": (
                "Tell the user simulation only supports these features: "
                + ", ".join(simulation.LEVERS) + "."
            ),
        }

    if lift_pct is None or lift_pct < 0 or lift_pct > 200:
        return {
            "error": "lift_pct must be between 0 and 200.",
            "instruction": "Ask the user for a lift percentage between 0 and 200.",
        }

    top_pct = st.session_state.get('top_pct', 10)
    result = simulation.simulate_campaign(
        features, weights, top_pct, feature, lift_pct
    )

    pretty = feature.replace('_', ' ')
    card = (
        f"### 🔮 Campaign Simulation — {pretty} +{lift_pct:.0f}%\n\n"
        f"- Target: **{result['target_count']:,}** regular users\n"
        f"- Projected conversions: **{result['conversions']:,}** cross the "
        f"loyalty bar\n"
        f"- Power users: {result['baseline_power_count']:,} → "
        f"**{result['projected_power_count']:,}** "
        f"({result['projected_power_pct']}%)\n"
        f"- {pretty} avg (regulars): {result['feature_avg_before']} → "
        f"**{result['feature_avg_after']}**\n"
    )
    st.session_state.ui_history.append({
        "role": "assistant", "type": "text", "content": card,
    })

    result["instruction"] = (
        "Summarize this campaign projection in 2-3 sentences using ONLY these "
        "numbers. Lead with the projected conversions and the new power-user "
        "percentage. Do not invent any figure not present here."
    )
    return result
```

- [ ] **Step 3: Register in `ALL_TOOLS`.** In the `ALL_TOOLS = [ ... ]` list, add `simulate_campaign,` as the last entry (after `build_action_plan,`):

```python
    build_action_plan,
    simulate_campaign,
]
```

- [ ] **Step 4: Verify it parses and is registered:**

Run: `..\venv\Scripts\python.exe -c "import ast; ast.parse(open('src/agent/tools.py').read()); print('tools.py parses')"`
Expected: prints `tools.py parses`.

Run: `..\venv\Scripts\python.exe -c "src=open('src/agent/tools.py').read(); print('def', src.count('def simulate_campaign(')); print('import', 'from src.analysis import simulation' in src); print('registered', 'simulate_campaign,' in src.split('ALL_TOOLS')[1])"`
Expected: `def 1`, `import True`, `registered True`.

- [ ] **Step 5: Commit:**

```bash
git add src/agent/tools.py
git commit -m "Phase 4: add simulate_campaign agent tool"
```

---

## Task 4: Register the tool for Autopilot

Add `simulate_campaign` to `TOOL_REGISTRY` so the Autopilot planner can choose it.

**Files:**
- Modify: `src/agent/orchestrator.py`

- [ ] **Step 1: Add the registry entry.** In `src/agent/orchestrator.py`, inside the `TOOL_REGISTRY = { ... }` dict, add this entry immediately after the `"build_action_plan": { ... },` entry (the last one before the closing `}`):

```python
    "simulate_campaign": {
        "func": T.simulate_campaign,
        "desc": "Project a what-if campaign: lift one feature for regular users by a percent and count how many become power users (needs scoring first).",
        "args": {"feature": "str", "lift_pct": "float"},
    },
```

- [ ] **Step 2: Verify it parses and is registered:**

Run: `..\venv\Scripts\python.exe -c "import ast; ast.parse(open('src/agent/orchestrator.py').read()); print('orchestrator.py parses')"`
Expected: prints `orchestrator.py parses`.

Run: `..\venv\Scripts\python.exe -c "src=open('src/agent/orchestrator.py').read(); print('in registry', 'simulate_campaign' in src.split('TOOL_REGISTRY')[1].split('DEFAULT_PLAN')[0])"`
Expected: `in registry True`.

- [ ] **Step 3: Run the orchestrator/reflexive suites to confirm nothing broke:**

```
..\venv\Scripts\python.exe tests/test_orchestrator.py
..\venv\Scripts\python.exe tests/test_reflexive.py
```
Expected: all PASS.

- [ ] **Step 4: Commit:**

```bash
git add src/agent/orchestrator.py
git commit -m "Phase 4: register simulate_campaign in the Autopilot tool catalog"
```

---

## Task 5: Journal entry + full verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the Project Journal entry.** At the TOP of the `## 📓 Project Journal` section in `CLAUDE.md` (above the 2026-06-18 entry), add:

```markdown
### 2026-06-19 — Proactive Analyst, Phase 4: What-If Simulation
Gave the agent a grounded campaign simulator — it can now project the impact of a
behavioral lift before you run the campaign.
- **`src/analysis/scoring.py`**: refactored into `compute_scaler` (fit caps +
  max_raw) and `apply_scoring` (score with a *provided* scaler); `score_users`
  now delegates to them and is behavior-identical. This lets a hypothetical
  population be scored on the baseline's frozen yardstick.
- **`src/analysis/simulation.py`** (NEW, pure): `LEVERS` (the 5 weighted scoring
  features) + `simulate_campaign(features, weights, top_pct, feature, lift_pct)`
  — lifts one feature for regular users only, re-scores with the frozen scaler,
  and counts how many clear the original cutoff. Returns conversions +
  projected power count/% + the feature's before→after average. `reorder_rate`
  is clipped to ≤ 1.0.
- **`src/agent/tools.py`**: `simulate_campaign(feature, lift_pct)` tool — validates
  the lever + range, calls the engine, renders a 🔮 card, returns a
  narrate-only-these-numbers instruction. Added to `ALL_TOOLS`.
- **`src/agent/orchestrator.py`**: registered in `TOOL_REGISTRY` so Autopilot can
  plan it.
- Grounding unchanged: the engine computes every number; the LLM only narrates.
- Tests: `tests/test_scoring.py` (refactor + frozen-scaler property),
  `tests/test_simulation.py` (conversions, monotonicity, clip, shape). No network.
  Full suite green; app boots headless HTTP 200.
- Scope: single-feature lever, regulars only, % lift, conversions + deltas only —
  no churn modelling, no new tab. Gemini-only; provider abstraction is Phase 5.
```

- [ ] **Step 2: Run the full no-network test suite.** Each must print its passing summary:

```
..\venv\Scripts\python.exe tests/test_scoring.py
..\venv\Scripts\python.exe tests/test_simulation.py
..\venv\Scripts\python.exe tests/test_memory.py
..\venv\Scripts\python.exe tests/test_proactive.py
..\venv\Scripts\python.exe tests/test_insights.py
..\venv\Scripts\python.exe tests/test_orchestrator.py
..\venv\Scripts\python.exe tests/test_reflexive.py
..\venv\Scripts\python.exe tests/test_deliverables.py
..\venv\Scripts\python.exe tests/test_persistence.py
```
Expected: all PASS.

- [ ] **Step 3: Boot the app headless and confirm HTTP 200** (PowerShell):

```powershell
$p = Start-Process -PassThru -NoNewWindow ..\venv\Scripts\python.exe `
  -ArgumentList "-m","streamlit","run","app.py","--server.headless","true","--server.port","8599"
Start-Sleep -Seconds 14
try { (Invoke-WebRequest http://localhost:8599 -UseBasicParsing).StatusCode } finally { Stop-Process -Id $p.Id -Force }
```
Expected: `200`. (If port 8599 is busy, pick another free port.)

- [ ] **Step 4: Commit:**

```bash
git add CLAUDE.md
git commit -m "Phase 4: journal entry for What-If Simulation"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- `compute_scaler` + `apply_scoring` + behavior-identical `score_users` → Task 1. ✓
- Frozen-scaler comparability + refactor-safety tests → Task 1. ✓
- `simulation.py` with `LEVERS` + `simulate_campaign`, fixed-bar conversions (Approach A), regulars-only lift, reorder_rate clip, full result dict → Task 2. ✓
- Engine tests (known conversion, monotonicity, zero-lift, clip, shape, LEVERS excludes days) → Task 2. ✓
- `simulate_campaign` tool: validation (lever via `simulation.LEVERS`, range 0–200 rejected), card, instruction, `ALL_TOOLS` → Task 3. ✓
- `TOOL_REGISTRY` registration for Autopilot → Task 4. ✓
- Journal + full suite + HTTP 200 → Task 5. ✓

**Placeholder scan:** none — every code/test step shows complete content. ✓

**Type consistency:** `compute_scaler` returns `{"caps", "max_raw"}`; `apply_scoring(features, weights, scaler)` reads those keys; `simulate_campaign(features, weights, top_pct, feature, lift_pct)` signature is identical in engine, tests, tool call, and `TOOL_REGISTRY` args (`feature: str`, `lift_pct: float`); result dict keys used in the tool card (`target_count`, `conversions`, `baseline_power_count`, `projected_power_count`, `projected_power_pct`, `feature_avg_before`, `feature_avg_after`) all match Task 2's return. ✓

**Note:** `score_users`/`get_power_users`/`get_thresholds` public signatures are unchanged, so `insights.py`, `tools.py`, and `orchestrator.py` callers keep working; Task 1 Step 5 explicitly runs the downstream suites as a regression gate.
