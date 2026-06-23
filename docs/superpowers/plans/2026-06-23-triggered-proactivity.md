# Triggered Proactivity (Watches & Alerts) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the user set threshold "watches" on real loyalty metrics; on every app interaction, fired watches surface as a banner at the top of any tab.

**Architecture:** A pure, Streamlit-free `src/agent/watches.py` holds a metric registry (each metric computes a deterministic value from an analysis snapshot dict), the fire-evaluation logic, and a best-effort JSON store at `.app_state/watches.json` (mirroring `src/agent/memory.py`). The sidebar gets a form to add/list/delete watches; `app.py` assembles a snapshot from `session_state` and renders fired alerts above the tabs. No LLM in the path — alert messages are templated.

**Tech Stack:** Python, pandas, Streamlit. Tests are standalone scripts (no pytest), no network, no Streamlit — matching the existing `tests/test_*.py` idiom.

---

## File Structure

- **Create** `src/agent/watches.py` — metric registry, `evaluate_metric`, `evaluate_watches`, and JSON persistence (`load_watches`, `add_watch`, `remove_watch`, `_save`). Pure / Streamlit-free.
- **Create** `tests/test_watches.py` — standalone test script for the above.
- **Modify** `src/ui/sidebar.py` — add a "🔔 Watches" section (form + list + delete).
- **Modify** `app.py` — add `render_watch_alerts()` + snapshot builder; call it above the tabs.
- **Modify** `CLAUDE.md` — add a dated Project Journal entry.

Reference conventions: `src/agent/insights.py` (pure metric module importing analysis funcs), `src/agent/memory.py` (best-effort JSON store), `tests/test_memory.py` (standalone test idiom).

---

## Task 1: Metric registry + evaluation (pure logic)

**Files:**
- Create: `src/agent/watches.py`
- Test: `tests/test_watches.py`

Analysis functions used (verified signatures):
- `calculate_churn_risk(features, power_user_ids, churn_days=30)` → `(at_risk_df, at_risk_power_df)`; `at_risk` = rows where `features['avg_days_between_orders'] > churn_days`; `at_risk_power` = those whose `user_id` is in `power_user_ids`.
- `compute_segment_gaps(power, regular)` → list of `{feature, power_user_avg, regular_user_avg, ratio}` sorted by `ratio` desc; needs columns `total_orders, reorder_rate, dept_diversity, avg_basket_size`.

- [ ] **Step 1: Write the failing test** (create `tests/test_watches.py`)

```python
"""Standalone tests for src/agent/watches.py. No network, no Streamlit."""
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import watches as w

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def _snapshot():
    # 5 customers; 2 are "at risk" (avg_days_between_orders > 30): u1, u2.
    features = pd.DataFrame({
        "user_id": [1, 2, 3, 4, 5],
        "avg_days_between_orders": [40, 35, 10, 5, 20],
    })
    # power_user_ids = {1} -> 1 at-risk power user (u1).
    power = pd.DataFrame({
        "total_orders": [50.0], "reorder_rate": [0.8],
        "dept_diversity": [12.0], "avg_basket_size": [10.0],
    })
    regular = pd.DataFrame({
        "total_orders": [10.0], "reorder_rate": [0.4],
        "dept_diversity": [6.0], "avg_basket_size": [5.0],
    })
    return {
        "features": features, "power": power, "regular": regular,
        "power_user_ids": {1}, "cutoff": 0.62, "churn_days": 30,
    }


def main():
    snap = _snapshot()

    # --- registry shape ---
    ids = [m["id"] for m in w.WATCHABLE_METRICS]
    check("4 metrics registered", len(w.WATCHABLE_METRICS) == 4)
    check("churn_pct present", "churn_pct" in ids)
    check("at_risk_power present", "at_risk_power" in ids)
    check("power_cutoff present", "power_cutoff" in ids)
    check("top_segment_gap present", "top_segment_gap" in ids)

    # --- metric computations ---
    check("churn_pct = 40.0", abs(w.evaluate_metric("churn_pct", snap) - 40.0) < 1e-6)
    check("at_risk_power = 1", w.evaluate_metric("at_risk_power", snap) == 1.0)
    check("power_cutoff = 0.62", abs(w.evaluate_metric("power_cutoff", snap) - 0.62) < 1e-6)
    # gaps ratios: total_orders 5.0, reorder 2.0, dept 2.0, basket 2.0 -> max 5.0
    check("top_segment_gap = 5.0", abs(w.evaluate_metric("top_segment_gap", snap) - 5.0) < 1e-6)
    check("unknown metric -> None", w.evaluate_metric("nope", snap) is None)

    # --- None on empty/missing inputs ---
    empty = {"features": pd.DataFrame(), "power": None, "regular": None}
    check("churn_pct None on empty", w.evaluate_metric("churn_pct", empty) is None)
    check("at_risk_power None on empty", w.evaluate_metric("at_risk_power", empty) is None)
    check("power_cutoff None when absent", w.evaluate_metric("power_cutoff", {}) is None)
    check("top_segment_gap None when absent", w.evaluate_metric("top_segment_gap", empty) is None)

    # --- evaluate_watches: fire logic ---
    fire = w.evaluate_watches(
        [{"id": "a", "metric": "churn_pct", "direction": "above", "threshold": 15.0}], snap)
    check("above fires (40 > 15)", len(fire) == 1)
    check("fired carries current", abs(fire[0]["current"] - 40.0) < 1e-6)
    check("churn above -> error severity", fire[0]["severity"] == "error")
    check("message mentions label", "Churn risk" in fire[0]["message"])
    check("message mentions percent", "40%" in fire[0]["message"])

    no_fire = w.evaluate_watches(
        [{"id": "b", "metric": "churn_pct", "direction": "above", "threshold": 40.0}], snap)
    check("equality does NOT fire (40 > 40 false)", no_fire == [])

    below = w.evaluate_watches(
        [{"id": "c", "metric": "power_cutoff", "direction": "below", "threshold": 0.7}], snap)
    check("below fires (0.62 < 0.7)", len(below) == 1)
    check("non-error metric -> warning", below[0]["severity"] == "warning")

    # --- unavailable metric never fires ---
    none_fire = w.evaluate_watches(
        [{"id": "d", "metric": "churn_pct", "direction": "above", "threshold": 1.0}], empty)
    check("unavailable metric never fires", none_fire == [])

    # --- ordering preserved ---
    multi = w.evaluate_watches([
        {"id": "x", "metric": "at_risk_power", "direction": "above", "threshold": 0},
        {"id": "y", "metric": "churn_pct", "direction": "above", "threshold": 0},
    ], snap)
    check("two fire", len(multi) == 2)
    check("order preserved", multi[0]["watch_id"] == "x" and multi[1]["watch_id"] == "y")

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_watches.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.watches'`.

- [ ] **Step 3: Write minimal implementation** (create `src/agent/watches.py`)

```python
"""
Watches — deterministic threshold alerts (triggered proactivity).

Pure Python (no Streamlit, no LLM), per the src/agent/insights.py convention.
The user defines watch conditions on real loyalty metrics; this module computes
each metric's current value from an analysis snapshot dict and reports which
watches have fired. Every number comes from the analysis layer; alert messages
are templated, so nothing here can hallucinate.
"""

import json
import math
import os
import uuid
from datetime import datetime

from src.analysis.metrics import calculate_churn_risk
from src.analysis.segmentation import compute_segment_gaps

CHURN_DAYS = 30


# --- Metric registry -------------------------------------------------------

def _churn_pct(snap):
    features = snap.get("features")
    if features is None or len(features) == 0:
        return None
    at_risk, _ = calculate_churn_risk(
        features, snap.get("power_user_ids") or set(),
        snap.get("churn_days", CHURN_DAYS),
    )
    return 100.0 * len(at_risk) / len(features)


def _at_risk_power(snap):
    features = snap.get("features")
    if features is None or len(features) == 0:
        return None
    _, at_risk_power = calculate_churn_risk(
        features, snap.get("power_user_ids") or set(),
        snap.get("churn_days", CHURN_DAYS),
    )
    return float(len(at_risk_power))


def _power_cutoff(snap):
    cutoff = snap.get("cutoff")
    if cutoff is None:
        return None
    return float(cutoff)


def _top_segment_gap(snap):
    power = snap.get("power")
    regular = snap.get("regular")
    if power is None or regular is None or len(power) == 0 or len(regular) == 0:
        return None
    gaps = compute_segment_gaps(power, regular)
    if not gaps:
        return None
    return float(max(g["ratio"] for g in gaps))


WATCHABLE_METRICS = [
    {"id": "churn_pct", "label": "Churn risk (% of customers)", "unit": "%",
     "compute": _churn_pct},
    {"id": "at_risk_power", "label": "At-risk power users", "unit": "",
     "compute": _at_risk_power},
    {"id": "power_cutoff", "label": "Power-user loyalty cutoff", "unit": "",
     "compute": _power_cutoff},
    {"id": "top_segment_gap", "label": "Largest power-vs-regular gap", "unit": "x",
     "compute": _top_segment_gap},
]

_METRICS_BY_ID = {m["id"]: m for m in WATCHABLE_METRICS}

# Metrics where exceeding the threshold upward is "bad" -> red error banner.
_ERROR_WHEN_ABOVE = {"churn_pct", "at_risk_power"}


def evaluate_metric(metric_id, snapshot):
    """Current value of a metric for the snapshot, or None if unavailable."""
    m = _METRICS_BY_ID.get(metric_id)
    if m is None:
        return None
    return m["compute"](snapshot)


def _fmt(value, unit):
    """Format a metric value: whole numbers without a decimal, else 1 dp."""
    if abs(value - round(value)) < 1e-9:
        num = f"{int(round(value))}"
    else:
        num = f"{value:.1f}"
    if unit == "%":
        return f"{num}%"
    if unit == "x":
        return f"{num}x"
    return num


def _fires(direction, current, threshold):
    if direction == "above":
        return current > threshold
    if direction == "below":
        return current < threshold
    return False


def evaluate_watches(watches, snapshot):
    """Return fired alerts (in `watches` order).

    Each alert: {watch_id, metric, label, direction, threshold, current,
    severity, message}. A watch whose metric is unavailable (compute -> None)
    never fires. Severity is "error" for an upward breach of an always-bad
    metric, else "warning".
    """
    fired = []
    for watch in watches or []:
        metric_id = watch.get("metric")
        m = _METRICS_BY_ID.get(metric_id)
        if m is None:
            continue
        current = m["compute"](snapshot)
        if current is None:
            continue
        direction = watch.get("direction")
        threshold = watch.get("threshold")
        try:
            threshold = float(threshold)
        except (TypeError, ValueError):
            continue
        if not _fires(direction, current, threshold):
            continue
        severity = (
            "error" if direction == "above" and metric_id in _ERROR_WHEN_ABOVE
            else "warning"
        )
        icon = "🚨" if severity == "error" else "⚠️"
        message = (
            f"{icon} {m['label']} is {_fmt(current, m['unit'])}, "
            f"{direction} your {_fmt(threshold, m['unit'])} watch."
        )
        fired.append({
            "watch_id": watch.get("id"),
            "metric": metric_id,
            "label": m["label"],
            "direction": direction,
            "threshold": threshold,
            "current": current,
            "severity": severity,
            "message": message,
        })
    return fired
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_watches.py`
Expected: PASS — all checks, ends with "N checks passed."

- [ ] **Step 5: Commit**

```bash
git add src/agent/watches.py tests/test_watches.py
git commit -m "Phase 6: watch metric registry + fire evaluation (pure)"
```

---

## Task 2: Persistence (load / add / remove)

**Files:**
- Modify: `src/agent/watches.py` (append persistence section)
- Test: `tests/test_watches.py` (add persistence checks)

- [ ] **Step 1: Add the failing persistence test** — in `tests/test_watches.py`, add this function and call it from `main()` (add `_persistence()` just before the final `print` line in `main`).

```python
def _persistence():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "watches.json")

        # empty / missing file -> []
        check("missing file -> []", w.load_watches(path=path) == [])

        # add a valid watch
        watch = w.add_watch("churn_pct", "above", 15, path=path)
        check("add returns id", isinstance(watch.get("id"), str) and watch["id"])
        check("add persisted", len(w.load_watches(path=path)) == 1)
        loaded = w.load_watches(path=path)[0]
        check("threshold coerced to float", loaded["threshold"] == 15.0)
        check("created_at present", "created_at" in loaded)

        # invalid inputs raise ValueError
        for bad in [
            lambda: w.add_watch("nope", "above", 1, path=path),
            lambda: w.add_watch("churn_pct", "sideways", 1, path=path),
            lambda: w.add_watch("churn_pct", "above", float("inf"), path=path),
            lambda: w.add_watch("churn_pct", "above", "abc", path=path),
        ]:
            raised = False
            try:
                bad()
            except ValueError:
                raised = True
            check("invalid add raises ValueError", raised)
        check("invalid adds did not persist", len(w.load_watches(path=path)) == 1)

        # remove
        check("remove unknown -> False", w.remove_watch("missing", path=path) is False)
        check("remove real -> True", w.remove_watch(watch["id"], path=path) is True)
        check("removed persisted", w.load_watches(path=path) == [])

        # corrupt file -> []
        with open(path, "w", encoding="utf-8") as f:
            f.write("{ not json")
        check("corrupt file -> []", w.load_watches(path=path) == [])
```

Then in `main()`, immediately before `print(f"\n{_passed} checks passed.")`, add:

```python
    _persistence()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_watches.py`
Expected: FAIL — `AttributeError: module 'src.agent.watches' has no attribute 'load_watches'`.

- [ ] **Step 3: Append the persistence implementation** to `src/agent/watches.py`:

```python
# --- Persistence (best-effort, never raises on I/O) ------------------------

STATE_DIR = ".app_state"
WATCHES_FILE = os.path.join(STATE_DIR, "watches.json")
_VALID_DIRECTIONS = ("above", "below")


def load_watches(path=WATCHES_FILE):
    """Return the stored list of watches, or [] if absent/corrupt.

    Filters out entries whose metric is no longer known so the UI/evaluator
    never sees a dangling watch.
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [
            wch for wch in data
            if isinstance(wch, dict) and wch.get("metric") in _METRICS_BY_ID
        ]
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return []


def _save(data, path):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def add_watch(metric, direction, threshold, path=WATCHES_FILE):
    """Validate and persist a new watch; return it.

    Raises ValueError on unknown metric, bad direction, or a non-finite /
    non-numeric threshold. The file write itself is best-effort.
    """
    if metric not in _METRICS_BY_ID:
        raise ValueError(f"unknown metric: {metric}")
    if direction not in _VALID_DIRECTIONS:
        raise ValueError(f"direction must be one of {_VALID_DIRECTIONS}")
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        raise ValueError("threshold must be a number")
    if not math.isfinite(threshold):
        raise ValueError("threshold must be finite")
    watch = {
        "id": uuid.uuid4().hex,
        "metric": metric,
        "direction": direction,
        "threshold": threshold,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    data = load_watches(path=path)
    data.append(watch)
    _save(data, path)
    return watch


def remove_watch(watch_id, path=WATCHES_FILE):
    """Drop a watch by id; return True if one was removed."""
    data = load_watches(path=path)
    kept = [wch for wch in data if wch.get("id") != watch_id]
    if len(kept) == len(data):
        return False
    _save(kept, path)
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_watches.py`
Expected: PASS — all checks including persistence.

- [ ] **Step 5: Commit**

```bash
git add src/agent/watches.py tests/test_watches.py
git commit -m "Phase 6: watch persistence (load/add/remove, best-effort JSON)"
```

---

## Task 3: Sidebar "🔔 Watches" section

**Files:**
- Modify: `src/ui/sidebar.py`

The sidebar body is one `with st.sidebar:` block ending in `return run_btn`. The existing structure uses `st.markdown("### …")` headers separated by `st.divider()` (API Status, Dataset, Settings, Progress, Export, then Replay/Reset/Forget buttons). Add the Watches section after the Export section's controls and before `return run_btn`.

- [ ] **Step 1: Add the import** at the top of `src/ui/sidebar.py` (with the other imports):

```python
from src.agent.watches import (
    WATCHABLE_METRICS, load_watches, add_watch, remove_watch,
)
```

- [ ] **Step 2: Add the Watches UI** — inside the `with st.sidebar:` block, immediately before `return run_btn`, insert:

```python
        st.divider()
        st.markdown("### 🔔 Watches")
        st.caption("Get a banner when a metric crosses a line you set.")

        _metric_labels = {m["id"]: m["label"] for m in WATCHABLE_METRICS}
        with st.form("add_watch_form", clear_on_submit=True):
            metric_id = st.selectbox(
                "Metric",
                options=[m["id"] for m in WATCHABLE_METRICS],
                format_func=lambda mid: _metric_labels[mid],
            )
            direction = st.radio(
                "Alert when value is", options=["above", "below"], horizontal=True,
            )
            threshold = st.number_input("Threshold", value=0.0, step=1.0)
            if st.form_submit_button("➕ Add watch", use_container_width=True):
                try:
                    add_watch(metric_id, direction, threshold)
                    st.success("Watch added.")
                except ValueError as e:
                    st.error(str(e))

        _watches = load_watches()
        if _watches:
            for wch in _watches:
                label = _metric_labels.get(wch["metric"], wch["metric"])
                thr = wch["threshold"]
                thr_txt = int(thr) if float(thr).is_integer() else thr
                row, btn = st.columns([5, 1])
                row.markdown(f"**{label}** {wch['direction']} {thr_txt}")
                if btn.button("🗑", key=f"del_watch_{wch['id']}"):
                    remove_watch(wch["id"])
                    st.rerun()
        else:
            st.caption("No watches yet.")
```

- [ ] **Step 3: Verify the module imports cleanly**

Run: `..\venv\Scripts\python.exe -c "import src.ui.sidebar"`
Expected: no output, exit 0 (imports without error).

- [ ] **Step 4: Commit**

```bash
git add src/ui/sidebar.py
git commit -m "Phase 6: sidebar Watches section (add/list/delete)"
```

---

## Task 4: Banner in app.py

**Files:**
- Modify: `app.py`

Goal: render fired alerts above the tabs on every rerun. `app.py` initializes `session_state`, restores chat, shows onboarding, renders the sidebar, then renders the 6 tabs. The banner must render after the sidebar call (so newly added/removed watches are reflected) and before/above the tabs.

- [ ] **Step 1: Add the import** near the top of `app.py` (with the other `from src...` imports):

```python
from src.agent.watches import load_watches, evaluate_watches
```

- [ ] **Step 2: Add the banner helper** — define this function in `app.py` (top level, after imports, before it is called):

```python
def render_watch_alerts():
    """Render any fired watch banners above the tabs (best-effort, never crashes)."""
    scored_df = st.session_state.get("scored_df")
    if scored_df is None or len(scored_df) == 0:
        return  # analysis not run yet -> nothing to evaluate
    snapshot = {
        "features": st.session_state.get("features"),
        "power": st.session_state.get("power"),
        "regular": st.session_state.get("regular"),
        "power_user_ids": st.session_state.get("power_user_ids") or set(),
        "cutoff": st.session_state.get("cutoff"),
        "churn_days": 30,
    }
    try:
        fired = evaluate_watches(load_watches(), snapshot)
    except Exception:
        return
    for alert in fired:
        if alert["severity"] == "error":
            st.error(alert["message"])
        else:
            st.warning(alert["message"])
```

- [ ] **Step 3: Call it above the tabs** — in `app.py`, find where the sidebar is rendered and the tabs are created (search for `st.tabs(`). Insert the call between the sidebar render and the tab creation:

```python
    render_watch_alerts()
```

(It must come after `render_sidebar(...)` so add/delete take effect on the same run, and before `st.tabs(...)` so the banner sits above the tab strip.)

- [ ] **Step 4: Verify app boots headless**

Run:
```
..\venv\Scripts\python.exe -m streamlit run app.py --server.headless true --server.port 8599 & 
```
Wait ~8 seconds, then check it serves:
```
..\venv\Scripts\python.exe -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8599').status)"
```
Expected: `200`. Then stop the server process.

(On Windows PowerShell, start it with `Start-Process` or run in a background terminal; the key check is HTTP 200 from the local URL.)

- [ ] **Step 5: Commit**

```bash
git add app.py
git commit -m "Phase 6: watch-alert banner above tabs (any-tab proactivity)"
```

---

## Task 5: Full-suite check + journal

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run the no-network test suite**

Run each and confirm non-zero exit on failure / all PASS:
```
..\venv\Scripts\python.exe tests/test_watches.py
..\venv\Scripts\python.exe tests/test_insights.py
..\venv\Scripts\python.exe tests/test_proactive.py
..\venv\Scripts\python.exe tests/test_memory.py
..\venv\Scripts\python.exe tests/test_router.py
..\venv\Scripts\python.exe tests/test_simulation.py
..\venv\Scripts\python.exe tests/test_scoring.py
```
Expected: every script prints PASS lines and exits 0.

- [ ] **Step 2: Add a Project Journal entry** — at the TOP of the `## 📓 Project Journal` section in `CLAUDE.md` (newest first), insert:

```markdown
### 2026-06-23 — Proactive Analyst, Phase 6: Triggered Proactivity (Watches)
Completed the roadmap: the agent now watches metrics you care about and speaks
up only when a line you set is crossed.
- **`src/agent/watches.py`** (NEW, pure / Streamlit-free): `WATCHABLE_METRICS`
  (churn risk %, at-risk power users, power-user cutoff, largest segment gap —
  each computes a deterministic value from an analysis snapshot dict via the
  existing analysis funcs), `evaluate_watches(watches, snapshot)` (fires on
  strict above/below; templated message; `error` severity for upward breaches
  of churn/at-risk-power, else `warning`; an unavailable metric never fires),
  and a best-effort JSON store at `.app_state/watches.json`
  (`load_watches`/`add_watch`/`remove_watch`, like `memory.py`). Watches
  persist across restart; no LLM in the path.
- **`src/ui/sidebar.py`**: a "🔔 Watches" section — a form to add one (metric /
  above-below / threshold) plus a list of current watches each with a delete
  button.
- **`app.py`**: `render_watch_alerts()` assembles a snapshot from
  `session_state` and renders fired watches as `st.error`/`st.warning` banners
  above the tabs, so an alert shows on whatever tab you're on. Guards on
  analysis readiness; best-effort (never crashes).
- Grounding unchanged: every number is deterministic; alert text is templated.
- Tests: `tests/test_watches.py` (metric math, fire logic incl. strict
  inequality + unavailable-metric, persistence round-trip + bad-input guards).
  No network. Full suite green; app boots headless HTTP 200.
- Scope: 4 metrics, structured-form input, banner surface — no NL parsing, no
  background scheduling, no alert history, no new tab. Phase 6 completes the
  Proactive Analyst roadmap.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "Phase 6: journal entry — Triggered Proactivity complete"
```

---

## Manual verification (after all tasks)

Not automatable; do in the browser once:
1. Run Full Analysis. Add a watch whose threshold is already crossed (e.g. *Churn risk above 1%*) → a banner appears. Switch tabs → banner still shows on each.
2. Delete the watch → banner disappears.
3. Restart the app → the watch you added is still listed (persistence).

---

## Self-Review notes

- **Spec coverage:** 4 metrics (Task 1), fire logic + templated message + severity (Task 1), persistence incl. survive-restart (Task 2), sidebar form/list/delete (Task 3), any-tab banner + readiness guard (Task 4), tests + journal (Tasks 1/2/5). All spec sections covered.
- **Spec refinement:** the segment-gap metric is expressed as a **ratio (×)** — the native output of `compute_segment_gaps` (`ratio` key) — rather than a derived "%". Label/unit reflect this ("Largest power-vs-regular gap", unit `x`). Same metric, clearer unit.
- **Type consistency:** `WATCHABLE_METRICS` items carry `{id,label,unit,compute}`; watches carry `{id,metric,direction,threshold,created_at}`; fired alerts carry `{watch_id,metric,label,direction,threshold,current,severity,message}` — used consistently across tasks.
- **No placeholders:** every code/test step shows complete code.
