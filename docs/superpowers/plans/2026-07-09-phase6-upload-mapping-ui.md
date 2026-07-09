# Phase 6 — Upload + Mapping-Confirm UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the app a front door — upload a CSV/Excel, confirm the LLM-proposed column mapping, and run the full analysis on that dataset — reusing the already-tested Phase-3 ingestion backend.

**Architecture:** Move the "active dataset" out of `app.py` module locals into `session_state` behind a single `set_active_dataset` swap helper (the seam). Add `src/ui/upload.py` whose orchestration is **pure functions** (profile→propose, apply-mapping) with thin Streamlit wrappers driving an `idle → confirm → build` state machine. Both upload and "back to demo" flow through the one swap helper.

**Tech Stack:** Python, Streamlit, pandas. Tests are standalone scripts (no pytest, no network); `streamlit.testing.v1.AppTest` for boot/wiring checks.

**Spec:** `docs/superpowers/specs/2026-07-09-phase6-upload-mapping-ui-design.md`

---

## File structure

- **Create `src/ui/dataset.py`** — `set_active_dataset(state, ...)`: the single dataset-swap helper. Pure (operates on a dict-like state); no Streamlit import needed.
- **Create `src/ui/upload.py`** — pure orchestration (`prepare_upload`, `apply_mapping`) + Streamlit render (`render_upload_section` for the sidebar, `render_confirm_gate` for the main area).
- **Create `tests/test_dataset_swap.py`** — unit tests for `set_active_dataset` on a plain dict.
- **Create `tests/test_upload_flow.py`** — unit tests for `prepare_upload` / `apply_mapping` with a fake `generate_fn` + temp store, and an `AppTest` boot check.
- **Modify `app.py`** — populate the active dataset via `set_active_dataset` on boot; read active data from `session_state`; render the upload confirm gate + upload section; dynamic header badge.
- **Modify `src/ui/sidebar.py`** — read the active dataset from `session_state` (no behavior change for the demo).

**Backend units reused as-is (do NOT modify):** `src/data/ingest/reader.read_table`, `profiler.profile_columns`, `mapper.propose_mapping` + `mapper.CANONICAL_FIELDS`, `builder.build_canonical`, `mapping_store.{fingerprint,load_mapping,save_mapping}`, `src/data/app_data.{load_demo_app_data,features_from_matrix}`, `src/data/levers.default_weights`, `src/agent/caller.generate`.

---

## Task 1: Dataset-swap helper (`set_active_dataset`)

**Files:**
- Create: `src/ui/dataset.py`
- Test: `tests/test_dataset_swap.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dataset_swap.py`:

```python
"""Unit tests for the active-dataset swap helper (no Streamlit, no network)."""
import sys, pandas as pd
from src.ui.dataset import set_active_dataset

def _demo_state():
    # Simulate a session_state with stale analysis from a previous dataset.
    return {
        "weights": {"old_lever": 1.0},
        "scored_df": pd.DataFrame({"x": [1]}),
        "power": pd.DataFrame({"x": [1]}), "regular": pd.DataFrame({"x": [1]}),
        "cutoff": 5.0, "thresholds_df": pd.DataFrame({"x": [1]}),
        "power_user_ids": {1, 2, 3},
    }

def _dataset():
    features = pd.DataFrame({"user_id": [1, 2], "frequency": [3, 5], "monetary": [10, 20]})
    orders = pd.DataFrame({"customer_id": [1, 1, 2], "order_id": [1, 2, 3],
                           "order_date": pd.to_datetime(["2024-01-01"] * 3),
                           "order_amount": [10.0, 5.0, 20.0]})
    return orders, None, features, {"frequency": True, "monetary": True}, ["frequency", "monetary"]

def test_sets_dataset_keys_and_label():
    state = _demo_state()
    orders, items, features, available, active = _dataset()
    set_active_dataset(state, orders=orders, order_items=items, features=features,
                       available=available, active_levers=active,
                       label="sales.csv", source="upload")
    assert state["features"] is features
    assert state["full_data"] is items
    assert state["orders"] is orders
    assert state["available"] == available
    assert state["active_levers"] == active
    assert state["dataset_label"] == "sales.csv"
    assert state["dataset_source"] == "upload"
    assert state["dataset_counts"] == {"customers": 2, "orders": 3}

def test_resets_weights_to_new_active_levers():
    state = _demo_state()
    orders, items, features, available, active = _dataset()
    set_active_dataset(state, orders=orders, order_items=items, features=features,
                       available=available, active_levers=active,
                       label="x", source="upload")
    # old_lever gone; weights are over the new active levers and sum to 1.0.
    assert set(state["weights"]) == {"frequency", "monetary"}
    assert abs(sum(state["weights"].values()) - 1.0) < 1e-9

def test_clears_stale_analysis():
    state = _demo_state()
    orders, items, features, available, active = _dataset()
    set_active_dataset(state, orders=orders, order_items=items, features=features,
                       available=available, active_levers=active,
                       label="x", source="upload")
    for k in ("scored_df", "power", "regular", "cutoff", "thresholds_df"):
        assert state[k] is None, f"{k} not cleared"
    assert state["power_user_ids"] == set()

if __name__ == "__main__":
    test_sets_dataset_keys_and_label()
    test_resets_weights_to_new_active_levers()
    test_clears_stale_analysis()
    print("test_dataset_swap: OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_dataset_swap.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ui.dataset'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/ui/dataset.py`:

```python
"""The single active-dataset swap seam.

Both an upload and "back to demo" call `set_active_dataset` to replace the
dataset the whole app reads from `session_state`. Pure: it operates on any
dict-like state (Streamlit's `session_state` or a plain dict in tests) and
imports no Streamlit. It resets the scoring weights to the new dataset's active
levers and clears any stale analysis results so a switch never mixes datasets.
"""

from src.data.levers import default_weights

# Analysis outputs that belong to the *previous* dataset and must be dropped.
_STALE_ANALYSIS = ("scored_df", "power", "regular", "cutoff", "thresholds_df")


def set_active_dataset(state, *, orders, order_items, features, available,
                       active_levers, label, source):
    """Replace the active dataset in `state`.

    `state` is a dict-like (session_state). `source` is "demo" or "upload".
    Writes the dataset keys + label/source/counts, resets `weights` to the new
    active levers, and clears stale analysis so the next `run_analysis` recomputes.
    """
    state["orders"] = orders
    state["full_data"] = order_items
    state["features"] = features
    state["available"] = available
    state["active_levers"] = active_levers
    state["dataset_label"] = label
    state["dataset_source"] = source
    state["dataset_counts"] = {"customers": int(len(features)),
                               "orders": int(len(orders))}
    state["weights"] = default_weights(active_levers)
    for k in _STALE_ANALYSIS:
        state[k] = None
    state["power_user_ids"] = set()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_dataset_swap.py`
Expected: `test_dataset_swap: OK`

- [ ] **Step 5: Commit**

```bash
git add src/ui/dataset.py tests/test_dataset_swap.py
git commit -m "feat(phase6): add set_active_dataset swap helper"
```

---

## Task 2: Wire the active-dataset seam into `app.py` (demo unchanged)

Refactor boot so the demo is loaded *through* `set_active_dataset`, and downstream reads the active dataset from `session_state`. No visible behavior change.

**Files:**
- Modify: `app.py:60-74` (boot/data load + defaults), `app.py:130,137,140,142` (sidebar/tab args)
- Test: `tests/test_upload_flow.py` (boot check added here; upload tests added in Task 4)

- [ ] **Step 1: Write the failing test (boot on demo, 0 exceptions)**

Create `tests/test_upload_flow.py` with just the boot check for now:

```python
"""Phase 6 upload flow + app-boot wiring tests (no network)."""
import os
from streamlit.testing.v1 import AppTest

def test_app_boots_on_demo_zero_exceptions():
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception, f"app raised: {at.exception}"
    # The active dataset is populated and labelled as the demo.
    assert at.session_state["dataset_source"] == "demo"
    assert at.session_state["dataset_label"]
    assert at.session_state["dataset_counts"]["customers"] > 0

if __name__ == "__main__":
    test_app_boots_on_demo_zero_exceptions()
    print("test_upload_flow(boot): OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_upload_flow.py`
Expected: FAIL — `KeyError: 'st.session_state has no key "dataset_source"'` (the seam isn't wired yet).

- [ ] **Step 3: Implement the seam in `app.py`**

Add the helper import next to the existing `from src.data.app_data import load_demo_app_data`:

```python
from src.ui.dataset import set_active_dataset
```

**Ordering matters:** the header badge (Task 4) reads `dataset_counts`, and the header `st.markdown` renders at the top of the file. So the active-dataset boot block + non-dataset defaults must run **before** the header block. Move them to run **immediately after `apply_theme()`** (currently `app.py:20`), i.e. above the header `st.markdown(...)` at line 22. Remove the old data-load line (`app.py:60`) and the old `defaults` block (`app.py:63-74`); replace with this single block placed right after `apply_theme()`:

```python
# --- Active dataset (demo on first boot; upload/back-to-demo swap it) ---
if "dataset_source" not in st.session_state:
    orders, order_items, features, available, active_levers = load_demo_app_data()
    set_active_dataset(
        st.session_state, orders=orders, order_items=order_items,
        features=features, available=available, active_levers=active_levers,
        label="Instacart", source="demo",
    )

# Remaining non-dataset defaults (dataset keys + weights are set above).
defaults = {
    'chat_history': [], 'ui_history': [], 'model_idx': 0, 'top_pct': 10,
    'artifacts': [],
    'active_model': MODEL_ARSENAL[0]['label'] if MODEL_ARSENAL else 'None',
}
for k, v in defaults.items():
    if k not in st.session_state: st.session_state[k] = v

# Read the active dataset from session_state for the rest of the script.
features = st.session_state['features']
orders = st.session_state['orders']
full_data = st.session_state['full_data']
```

Then make `run_analysis` read `features`/`weights` from `session_state` (so it uses the *active* dataset after a swap). Replace its body's data references:

```python
def run_analysis(top_pct):
    features = st.session_state['features']
    with st.status("Running analysis…", expanded=True) as status:
        st.write(f"⚖️ Scoring all {len(features):,} users…")
        scored = score_users(features, st.session_state['weights'])
        st.write(f"🏆 Selecting top {top_pct}%…")
        power, regular, cutoff = get_power_users(scored, top_pct)
        st.write("📊 Computing segment thresholds…")
        thresholds = get_thresholds(power, regular)
        st.session_state.update({
            'scored_df': scored, 'power': power, 'regular': regular, 'cutoff': cutoff,
            'thresholds_df': thresholds, 'power_user_ids': set(power['user_id']),
            'top_pct': top_pct
        })
        status.update(label=f"Analysis complete — {len(power):,} power users found",
                      state="complete", expanded=False)
    st.success(f"✅ Analysis complete — Found **{len(power):,}** power users")
```

(The sidebar/tab calls at the bottom already pass the local `features`/`orders`/`full_data`, which now come from `session_state` — no change needed there yet.)

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_upload_flow.py`
Expected: `test_upload_flow(boot): OK`

- [ ] **Step 5: Regression — existing suites still green**

Run: `..\venv\Scripts\python.exe tests/test_tools_canonical.py`
Expected: PASS (no exceptions; tools still run on the demo via session_state).

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_upload_flow.py
git commit -m "refactor(phase6): boot demo through set_active_dataset seam"
```

---

## Task 3: Upload orchestration — pure functions

The two pure functions the Streamlit layer will call. No Streamlit, no network (LLM injected).

**Files:**
- Create: `src/ui/upload.py` (pure functions only in this task)
- Test: `tests/test_upload_flow.py` (append)

- [ ] **Step 1: Write the failing tests (append to `tests/test_upload_flow.py`)**

Add above the `__main__` block:

```python
import io, json, tempfile, pandas as pd
from src.ui.upload import prepare_upload, apply_mapping

_GOOD_CSV = (
    "Cust,Ord,When,Paid\n"
    "1,100,2024-01-01,10.00\n"
    "1,101,2024-01-15,5.50\n"
    "2,102,2024-02-01,20.00\n"
)

def _fake_generate(_prompt):
    # Deterministic "LLM": returns the correct mapping JSON for _GOOD_CSV.
    return json.dumps({"customer_id": "Cust", "order_id": "Ord",
                       "order_date": "When", "order_amount": "Paid"})

def test_prepare_upload_proposes_mapping_no_saved_recipe():
    df = pd.read_csv(io.StringIO(_GOOD_CSV), dtype=str)
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        state = prepare_upload(df, generate_fn=_fake_generate, store_path=store)
    assert state["stage"] == "confirm"
    assert state["saved"] is False
    assert state["mapping"]["order_amount"] == "Paid"
    assert [p["name"] for p in state["profile"]] == ["Cust", "Ord", "When", "Paid"]

def test_prepare_upload_uses_saved_recipe_fast_path():
    df = pd.read_csv(io.StringIO(_GOOD_CSV), dtype=str)
    mapping = {"customer_id": "Cust", "order_id": "Ord",
               "order_date": "When", "order_amount": "Paid"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        from src.data.ingest.mapping_store import save_mapping
        save_mapping(list(df.columns), mapping, path=store)
        state = prepare_upload(df, generate_fn=_fake_generate, store_path=store)
    assert state["stage"] == "build"      # skips confirm
    assert state["saved"] is True
    assert state["mapping"] == mapping

def test_apply_mapping_success_builds_canonical():
    df = pd.read_csv(io.StringIO(_GOOD_CSV), dtype=str)
    mapping = {"customer_id": "Cust", "order_id": "Ord",
               "order_date": "When", "order_amount": "Paid"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        result = apply_mapping(df, mapping, store_path=store)
        assert result["ok"] is True
        assert result["matrix"] is not None
        # mapping was persisted for next time
        with open(store) as fh:
            assert json.load(fh)  # non-empty store

def test_apply_mapping_failure_returns_errors():
    bad = "Cust,Ord,When,Paid\n1,100,2024-01-01,notmoney\n2,101,2024-01-02,alsobad\n"
    df = pd.read_csv(io.StringIO(bad), dtype=str)
    mapping = {"customer_id": "Cust", "order_id": "Ord",
               "order_date": "When", "order_amount": "Paid"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        result = apply_mapping(df, mapping, store_path=store)
    assert result["ok"] is False
    assert result["errors"]          # human-readable messages present
    assert result["matrix"] is None
```

And extend the `__main__` block:

```python
if __name__ == "__main__":
    test_app_boots_on_demo_zero_exceptions()
    test_prepare_upload_proposes_mapping_no_saved_recipe()
    test_prepare_upload_uses_saved_recipe_fast_path()
    test_apply_mapping_success_builds_canonical()
    test_apply_mapping_failure_returns_errors()
    print("test_upload_flow: OK")
```

- [ ] **Step 2: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_upload_flow.py`
Expected: FAIL — `ImportError: cannot import name 'prepare_upload' from 'src.ui.upload'`.

- [ ] **Step 3: Implement the pure functions**

Create `src/ui/upload.py`:

```python
"""Upload + mapping-confirm flow.

Pure orchestration (`prepare_upload`, `apply_mapping`) over the Phase-3 ingestion
backend, plus thin Streamlit render functions. The pure functions take an injected
`generate_fn` and an explicit `store_path`, so they are unit-testable with no
Streamlit and no network. The render functions drive an `idle -> confirm -> build`
state machine kept in `st.session_state["upload_stage"]`.
"""

from src.data.ingest.profiler import profile_columns
from src.data.ingest.mapper import propose_mapping, CANONICAL_FIELDS
from src.data.ingest.builder import build_canonical
from src.data.ingest.mapping_store import (
    fingerprint, load_mapping, save_mapping, _STORE,
)


def prepare_upload(df, generate_fn, store_path=_STORE):
    """Profile the uploaded frame and resolve its column mapping.

    Returns a dict: {stage, mapping, source, profile, saved}.
    - If a saved recipe matches the header fingerprint -> stage "build",
      saved=True (fast path, skip confirm).
    - Else propose a mapping (LLM via generate_fn, deterministic fuzzy fallback
      inside propose_mapping) -> stage "confirm", saved=False.
    """
    profile = profile_columns(df)
    headers = list(df.columns)
    saved = load_mapping(headers, path=store_path)
    if saved:
        return {"stage": "build", "mapping": saved, "source": "saved",
                "profile": profile, "saved": True}
    proposed = propose_mapping(profile, generate_fn=generate_fn)
    return {"stage": "confirm", "mapping": proposed["mapping"],
            "source": proposed["source"], "profile": profile, "saved": False}


def apply_mapping(df, mapping, store_path=_STORE):
    """Validate + build canonical for a confirmed mapping.

    On success, persists the mapping recipe for next time. Returns the
    builder result dict {ok, errors, warnings, orders, order_items, matrix}.
    """
    result = build_canonical(df, mapping)
    if result["ok"]:
        save_mapping(list(df.columns), mapping, path=store_path)
    return result
```

- [ ] **Step 4: Run to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_upload_flow.py`
Expected: `test_upload_flow: OK`

- [ ] **Step 5: Commit**

```bash
git add src/ui/upload.py tests/test_upload_flow.py
git commit -m "feat(phase6): upload orchestration (prepare_upload, apply_mapping)"
```

---

## Task 4: Streamlit render — sidebar section, confirm gate, back-to-demo

Add the Streamlit layer to `src/ui/upload.py` and wire it into `app.py`.

**Files:**
- Modify: `src/ui/upload.py` (append render functions)
- Modify: `app.py` (render upload section + confirm gate; dynamic header badge)
- Test: `tests/test_upload_flow.py` (AppTest confirm-gate absence on demo boot already covered; add a state-machine boot assertion)

- [ ] **Step 1: Append render functions to `src/ui/upload.py`**

```python
import streamlit as st

from src.data.ingest.reader import read_table
from src.data.app_data import features_from_matrix, load_demo_app_data
from src.ui.dataset import set_active_dataset

_REQUIRED = [f for f, m in CANONICAL_FIELDS.items() if m["required"]]
_OPTIONAL = [f for f, m in CANONICAL_FIELDS.items() if not m["required"]]
_FIELD_LABEL = {
    "customer_id": "Customer ID", "order_id": "Order ID",
    "order_date": "Order date", "order_amount": "Order amount",
    "product": "Product (optional)", "category": "Category (optional)",
    "quantity": "Quantity (optional)",
}


def _mapping_generate_fn(prompt):
    """Adapter: the mapper calls generate_fn(prompt)->str; wrap the app's generate."""
    from src.agent.caller import generate
    return generate(prompt, system_instruction="You map spreadsheet columns to a schema.")


def render_upload_section(run_analysis):
    """Sidebar 'Your data' section: active-dataset indicator, uploader, back-to-demo."""
    st.markdown("### 📁 Your data")
    source = st.session_state.get("dataset_source", "demo")
    label = st.session_state.get("dataset_label", "Instacart")
    counts = st.session_state.get("dataset_counts", {})
    if source == "demo":
        st.caption(f"📊 Demo data · {label}")
    else:
        st.success(f"📊 Your data · {label}")
        st.caption(f"{counts.get('customers', 0):,} customers · {counts.get('orders', 0):,} orders")
        if st.button("↩ Back to demo data", use_container_width=True):
            o, it, f, av, al = load_demo_app_data()
            set_active_dataset(st.session_state, orders=o, order_items=it, features=f,
                               available=av, active_levers=al, label="Instacart", source="demo")
            st.session_state.pop("upload_stage", None)
            run_analysis(st.session_state["top_pct"])
            st.rerun()

    up = st.file_uploader("Upload CSV or Excel", type=["csv", "xlsx", "xls"],
                          key="dataset_uploader")
    if up is not None and st.session_state.get("upload_filename") != up.name:
        # New file dropped -> read + prepare (profile/propose or saved-recipe fast path).
        try:
            df = read_table(up, filename=up.name)
        except Exception as e:
            st.error(f"Couldn't read that file: {e}")
            return
        prep = prepare_upload(df, generate_fn=_mapping_generate_fn)
        st.session_state["upload_df"] = df
        st.session_state["upload_filename"] = up.name
        st.session_state["upload_mapping"] = prep["mapping"]
        st.session_state["upload_profile"] = prep["profile"]
        st.session_state["upload_saved"] = prep["saved"]
        # Saved-recipe fast path: build+analyze immediately, but leave a review hook.
        if prep["stage"] == "build":
            _build_and_activate(up.name, df, prep["mapping"], run_analysis)
        else:
            st.session_state["upload_stage"] = "confirm"
        st.rerun()


def _build_and_activate(filename, df, mapping, run_analysis):
    """Run apply_mapping; on success swap the active dataset + analyze."""
    result = apply_mapping(df, mapping)
    if not result["ok"]:
        st.session_state["upload_stage"] = "confirm"
        st.session_state["upload_errors"] = result["errors"]
        return
    feats, available, active = features_from_matrix(result["matrix"])
    set_active_dataset(st.session_state, orders=result["orders"],
                       order_items=result["order_items"], features=feats,
                       available=available, active_levers=active,
                       label=filename, source="upload")
    st.session_state["upload_stage"] = None
    st.session_state["upload_warnings"] = result.get("warnings", [])
    run_analysis(st.session_state["top_pct"])


def render_confirm_gate(run_analysis):
    """Main-area confirm screen. Renders only when upload_stage == 'confirm'.
    Returns True if the gate rendered (caller should skip the tabs)."""
    if st.session_state.get("upload_stage") != "confirm":
        return False
    df = st.session_state["upload_df"]
    mapping = st.session_state["upload_mapping"]
    columns = list(df.columns)
    fname = st.session_state.get("upload_filename", "your file")

    st.markdown(f"## 📋 Confirm column mapping — `{fname}`")
    if st.session_state.get("upload_saved"):
        st.info("Using your saved mapping for this file. Review below or confirm.")
    st.caption("Tell us which of your columns is which. We check the data before "
               "running anything.")
    for errs in [st.session_state.pop("upload_errors", [])]:
        for e in errs:
            st.error(e)

    chosen = {}
    none_opt = "— none —"
    for field in _REQUIRED + _OPTIONAL:
        opts = columns if field in _REQUIRED else [none_opt] + columns
        cur = mapping.get(field)
        idx = opts.index(cur) if cur in opts else 0
        chosen[field] = st.selectbox(_FIELD_LABEL[field], opts, index=idx,
                                     key=f"map_{field}")
    chosen = {f: (None if v == none_opt else v) for f, v in chosen.items()}

    st.markdown("**Preview** (first rows of the columns you chose):")
    picked = [c for c in chosen.values() if c]
    if picked:
        st.dataframe(df[picked].head(5), use_container_width=True)

    c1, c2 = st.columns(2)
    if c1.button("✅ Confirm & analyze", type="primary", use_container_width=True):
        _build_and_activate(fname, df, chosen, run_analysis)
        st.rerun()
    if c2.button("Cancel", use_container_width=True):
        for k in ("upload_stage", "upload_df", "upload_filename", "upload_mapping",
                  "upload_profile", "upload_saved"):
            st.session_state.pop(k, None)
        st.rerun()
    return True
```

- [ ] **Step 2: Wire into `app.py`**

Add the import near the other UI imports:

```python
from src.ui.upload import render_upload_section, render_confirm_gate
```

Render the upload section inside the sidebar. In `src/ui/sidebar.py`, at the end of the `with st.sidebar:` block (after the Watches section), add — passing the callback through. Simplest: render it from `app.py` right after `render_sidebar(...)` by opening the sidebar context:

```python
render_sidebar(features, orders, run_analysis)
with st.sidebar:
    render_upload_section(run_analysis)
```

Gate the tabs behind the confirm screen (replace the header-badge + tabs section):

```python
if not render_confirm_gate(run_analysis):
    render_watch_alerts()
    maybe_show_onboarding(run_analysis)
    tabs = st.tabs(["📊 Overview", "⚖️ Scoring", "👥 Segments", "🗺️ Happy Path", "🎯 Interventions", "🤖 AI Chat"])
    with tabs[0]: render_overview(features, orders)
    with tabs[1]: render_scoring()
    with tabs[2]: render_segments()
    with tabs[3]: render_happy_path(full_data)
    with tabs[4]: render_interventions()
    with tabs[5]: render_chat(features, orders)
```

- [ ] **Step 3: Dynamic header badge**

Replace the hardcoded badge line (`app.py:55`, the `Instacart &nbsp;//&nbsp; 206,209 customers …` string) so it reflects the active dataset. Build the badge text just before the `st.markdown` header block:

```python
_c = st.session_state.get("dataset_counts", {}) if "dataset_counts" in st.session_state else {}
_badge = (f"{st.session_state.get('dataset_label', 'Instacart')} &nbsp;//&nbsp; "
          f"{_c.get('customers', 0):,} customers &nbsp;//&nbsp; {_c.get('orders', 0):,} orders")
```

and substitute `{_badge}` into the badge `<div>` (make the header block an f-string, escaping the existing `{`/`}` in the inline CSS by doubling them, OR simpler: split the static CSS from the dynamic text by injecting only the badge text via a small `.format`). Since the block has many CSS braces, use a placeholder replace instead of an f-string:

```python
_HEADER_HTML = """<div style="...">...<div style="...">__BADGE__</div>...</div>"""
st.markdown(_HEADER_HTML.replace("__BADGE__", _badge), unsafe_allow_html=True)
```

Keep the rest of the header HTML byte-for-byte; only the badge inner text becomes `__BADGE__`.

- [ ] **Step 4: Add an AppTest wiring assertion**

Append to `tests/test_upload_flow.py` (before `__main__`) and call it in `__main__`:

```python
def test_confirm_gate_absent_on_demo_boot():
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception
    # No confirm gate pending on a clean demo boot -> all 6 tabs render.
    assert at.session_state.get("upload_stage") in (None,)
```

- [ ] **Step 5: Run tests**

Run: `..\venv\Scripts\python.exe tests/test_upload_flow.py`
Expected: `test_upload_flow: OK` (boot, pure-function, and gate assertions all pass).

- [ ] **Step 6: Commit**

```bash
git add src/ui/upload.py app.py
git commit -m "feat(phase6): upload sidebar section + confirm gate + dynamic badge"
```

---

## Task 5: Regression sweep + journal entry

**Files:**
- Modify: `CLAUDE.md` (journal entry)

- [ ] **Step 1: Run the full no-network suite**

Run each and confirm PASS (no network):

```
..\venv\Scripts\python.exe tests/test_dataset_swap.py
..\venv\Scripts\python.exe tests/test_upload_flow.py
..\venv\Scripts\python.exe tests/test_canonical.py
..\venv\Scripts\python.exe tests/test_demo_adapter.py
..\venv\Scripts\python.exe tests/test_ingest.py
..\venv\Scripts\python.exe tests/test_mapping_persist.py
..\venv\Scripts\python.exe tests/test_tools_canonical.py
..\venv\Scripts\python.exe tests/test_levers.py
..\venv\Scripts\python.exe tests/test_app_data.py
```

Expected: every script prints its OK line and exits 0.

- [ ] **Step 2: Manual smoke (optional but recommended)**

Run the app, upload a small CSV, confirm the mapping, verify analysis runs and "Back to demo" restores the demo:

```
..\venv\Scripts\python.exe -m streamlit run app.py
```

- [ ] **Step 3: Add the journal entry**

Prepend a dated entry to the Project Journal in `CLAUDE.md` summarizing Phase 6 (new `src/ui/dataset.py` + `src/ui/upload.py`, active-dataset seam, upload/confirm/back-to-demo, dynamic badge, tests). Follow the existing entry format.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(phase6): journal entry for upload + mapping-confirm UI"
```

---

## Self-review notes

- **Spec coverage:** seam (§3.1)→T1/T2; upload+confirm state machine (§3.2)→T3/T4; saved-recipe fast path (Q3)→`prepare_upload` build-stage + review note (T3/T4); validate-on-confirm (Q2)→`apply_mapping`/`_build_and_activate` (T3/T4); auto-run after confirm (Q1)→`_build_and_activate` calls `run_analysis` (T4); back-to-demo + indicator + dynamic badge (§3.3)→T4; error handling (§4)→`apply_mapping` failure test + read-failure guard (T3/T4); testing (§6)→T1/T3/T5.
- **LLM unavailable path:** `propose_mapping` already falls back to `fuzzy_map` internally, so `_mapping_generate_fn` raising (no keys/quota) still yields a proposal — no extra handling needed.
- **`generate` signature:** requires `system_instruction` kwarg → provided in `_mapping_generate_fn`.
