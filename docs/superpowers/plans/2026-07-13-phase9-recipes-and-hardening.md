# Phase 9 — Recipes + Finishing/Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a user save a good grounded-query answer as a named, one-click "recipe" that deterministically recomputes on live data (no LLM in the replay), then finish the project with a trust/hardening pass (pin the Claude dep, presentable README, browser-smoke, non-Instacart BYOD dry-run).

**Architecture:** A new pure best-effort JSON store `src/agent/recipes.py` (same shape/guarantees as `watches.py`) holds `{id,name,query,created}` records — `query` is the arg dict `run_grounded_query` already echoes. The Phase-8 tool stashes its last successful query into `session_state`; the chat body shows a "Save as recipe" form and recipe chips; the sidebar shows a "🍳 Recipes" list. Running a recipe calls `run_grounded_query(**query)` directly (bypasses router + LLM) and re-renders via `st.rerun()`. The dispatch `recipe_fn` rung stays inert.

**Tech Stack:** Python, Streamlit (`session_state`, `AppTest`, forms/buttons), pandas. Standalone-script tests (not pytest), run with `..\venv\Scripts\python.exe`.

**Spec:** `docs/superpowers/specs/2026-07-13-phase9-recipes-and-hardening-design.md`

**Key facts confirmed against the codebase (do not re-derive):**
- Store pattern to mirror: `src/agent/watches.py` — `.app_state/*.json`, `load_*` returns `[]` on missing/corrupt, `_save` swallows I/O errors, `path=` kwarg for testability.
- `run_grounded_query` lives in `src/agent/tools.py`; on success `result["query"]` is the arg dict, and there is a single `kind = result["kind"]` line after the `if not result.get("ok"): return ...` guard — the stash goes right there.
- Chat body: `src/ui/tabs/chat.py` — `render_chat(features, orders)` renders the `ui_history` loop, then starter chips (only when no user message), then `st.chat_input`, then Full numbers / deliverables / New conversation. `_submit(prompt)` routes through `dispatch`. Recipes must NOT go through `dispatch`.
- Sidebar: `src/ui/sidebar.py` — the Watches section (`sidebar.py:174-207`) is the exact pattern to copy for a Recipes section (header, caption, list rows with buttons, "No … yet." empty state). `render_sidebar` runs BEFORE `render_chat` in `app.py`, so a sidebar button can set `session_state["run_recipe_id"]` that the chat consumes in the same run.
- Canonical test fixture: an orders-only DataFrame (`customer_id, order_id, order_date, order_amount`) → `build_feature_matrix` → `features_from_matrix` yields `features` with RFM columns `frequency`, `monetary`, `recency_days` (see `tests/test_tools_canonical.py`).
- `anthropic` is ALREADY listed in `requirements.txt` but unpinned; the file is UTF-16 encoded — edits must preserve that encoding.

---

### Task 1: Recipe store + `describe_query` (`src/agent/recipes.py`)

**Files:**
- Create: `src/agent/recipes.py`
- Test: `tests/test_recipes.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_recipes.py`:

```python
# tests/test_recipes.py — standalone script (pure store, no network, no Streamlit)
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent.recipes import (
    load_recipes, add_recipe, remove_recipe, describe_query,
)

def _tmp():
    d = tempfile.mkdtemp()
    return os.path.join(d, "recipes.json")

# describe_query --------------------------------------------------------------
assert describe_query({"table": "customers", "operation": "aggregate",
                       "metric": "frequency", "agg": "mean"}) == \
    "Mean of frequency (customers)", "scalar label"
assert describe_query({"table": "orders", "operation": "aggregate",
                       "metric": "order_amount", "agg": "mean",
                       "group_by": "category"}) == \
    "Mean of order amount by category (orders)", "grouped label"
assert describe_query({"table": "customers", "operation": "correlate",
                       "column_a": "frequency", "column_b": "monetary"}) == \
    "Correlation: frequency vs monetary (customers)", "correlation label"
assert describe_query({"table": "customers", "operation": "aggregate",
                       "metric": "frequency", "agg": "count",
                       "filter_column": "recency_days", "filter_op": ">"}) == \
    "Count of frequency (customers), filtered", "filtered label"
print("test_recipes: describe_query OK")

# round-trip ------------------------------------------------------------------
p = _tmp()
assert load_recipes(path=p) == [], "empty store -> []"
q = {"table": "customers", "operation": "aggregate", "metric": "frequency", "agg": "mean"}
rec = add_recipe("My avg freq", q, path=p)
assert rec["id"] and rec["name"] == "My avg freq" and rec["query"] == q, rec
assert "created" in rec, "timestamped"
got = load_recipes(path=p)
assert len(got) == 1 and got[0]["id"] == rec["id"], got
# second recipe appends
rec2 = add_recipe("Second", q, path=p)
assert len(load_recipes(path=p)) == 2
# remove
assert remove_recipe(rec["id"], path=p) is True
left = load_recipes(path=p)
assert len(left) == 1 and left[0]["id"] == rec2["id"], left
assert remove_recipe("nope", path=p) is False, "removing unknown id -> False"
print("test_recipes: round-trip OK")

# blank name falls back to derived label -------------------------------------
p2 = _tmp()
r = add_recipe("   ", q, path=p2)
assert r["name"] == "Mean of frequency (customers)", r
print("test_recipes: blank-name fallback OK")

# corrupt / non-list store tolerated -----------------------------------------
p3 = _tmp()
with open(p3, "w", encoding="utf-8") as f:
    f.write("{ this is not valid json ]")
assert load_recipes(path=p3) == [], "corrupt JSON -> []"
p4 = _tmp()
with open(p4, "w", encoding="utf-8") as f:
    json.dump({"not": "a list"}, f)
assert load_recipes(path=p4) == [], "non-list JSON -> []"
# entries missing a dict query are dropped
p5 = _tmp()
with open(p5, "w", encoding="utf-8") as f:
    json.dump([{"id": "a", "name": "x"}, {"id": "b", "name": "y", "query": {"k": 1}}], f)
kept = load_recipes(path=p5)
assert len(kept) == 1 and kept[0]["id"] == "b", kept
print("test_recipes: corrupt-store tolerance OK")

print("test_recipes: ALL PASSED")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_recipes.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.recipes'`.

- [ ] **Step 3: Write minimal implementation** — create `src/agent/recipes.py`:

```python
"""Recipes — saved, replayable grounded-query actions.

Pure Python (no Streamlit, no LLM), same best-effort JSON-store shape as
`watches.py`. A recipe stores only the `run_grounded_query` argument dict plus a
name — never raw data, numbers, or code. Replaying a recipe re-runs the
deterministic Phase-8 engine on the current dataset, so numbers are always fresh
and the trust invariant holds.
"""

import json
import os
import uuid
from datetime import datetime

STATE_DIR = ".app_state"
RECIPES_FILE = os.path.join(STATE_DIR, "recipes.json")


def describe_query(query):
    """A deterministic human label for a grounded-query arg dict (no data access)."""
    q = query or {}
    table = q.get("table", "")

    def sp(s):
        return str(s).replace("_", " ")

    if q.get("operation") == "correlate":
        base = f"Correlation: {sp(q.get('column_a', ''))} vs {sp(q.get('column_b', ''))}"
    else:
        agg = str(q.get("agg", "")).title()
        metric = sp(q.get("metric", ""))
        group_by = q.get("group_by", "")
        base = (f"{agg} of {metric} by {sp(group_by)}" if group_by
                else f"{agg} of {metric}")
    if table:
        base += f" ({table})"
    if q.get("filter_column") and q.get("filter_op"):
        base += ", filtered"
    return base


# NOTE: path defaults to None and resolves to the MODULE-LEVEL RECIPES_FILE at
# call time (not as a bound default). This lets a test monkeypatch
# `recipes.RECIPES_FILE` and have the UI (which calls with no path) pick it up —
# a plain `path=RECIPES_FILE` default would bind once at def time and ignore the
# monkeypatch.
def load_recipes(path=None):
    """Stored recipes, or [] if absent/corrupt. Drops entries without a dict query."""
    path = path or RECIPES_FILE
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            return []
        return [r for r in data
                if isinstance(r, dict) and isinstance(r.get("query"), dict)]
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return []


def _save(data, path):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def add_recipe(name, query, path=None):
    """Persist a recipe; a blank name falls back to the derived label. Returns it."""
    path = path or RECIPES_FILE
    name = (name or "").strip() or describe_query(query)
    rec = {
        "id": uuid.uuid4().hex[:8],
        "name": name,
        "query": dict(query or {}),
        "created": datetime.now().isoformat(timespec="seconds"),
    }
    data = load_recipes(path=path)
    data.append(rec)
    _save(data, path)
    return rec


def remove_recipe(recipe_id, path=None):
    """Drop a recipe by id; return True if one was removed."""
    path = path or RECIPES_FILE
    data = load_recipes(path=path)
    kept = [r for r in data if r.get("id") != recipe_id]
    if len(kept) == len(data):
        return False
    _save(kept, path)
    return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_recipes.py`
Expected: PASS — prints `test_recipes: ALL PASSED`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/agent/recipes.py tests/test_recipes.py
git commit -m "feat(phase9): recipe store + describe_query (pure, best-effort)"
```

---

### Task 2: Stash the last successful grounded query (`src/agent/tools.py`)

**Files:**
- Modify: `src/agent/tools.py` (import + one stash line in `run_grounded_query`)
- Test: `tests/test_tools_canonical.py` (one new assertion)

- [ ] **Step 1: Write the failing test** — in `tests/test_tools_canonical.py`, append at the END of the file (after the existing Phase 8 assertions):

```python
# --- Phase 9: successful grounded query stashes last_grounded_query ---
lgq = at.session_state.get("last_grounded_query")
assert lgq and isinstance(lgq.get("query"), dict), f"last_grounded_query stashed: {lgq}"
assert lgq["query"]["operation"] == "correlate", "stash holds the LAST successful query"
assert isinstance(lgq.get("label"), str) and lgq["label"], "stash carries a human label"
print("test_tools_canonical: last_grounded_query stash OK")
```

(The SCRIPT runs `gq_scalar` then `gq_corr` — both succeed — then `gq_badcol`/`gq_items` fail; so the stash must hold the correlation query, proving failures don't overwrite it.)

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_tools_canonical.py`
Expected: FAIL — `AssertionError: last_grounded_query stashed: None`.

- [ ] **Step 3: Write minimal implementation** — in `src/agent/tools.py`:

(a) Add the import near the other agent imports (after `from src.agent import tool_context as tc`):

```python
from src.agent import recipes as _recipes
```

(b) In `run_grounded_query`, immediately AFTER the `if not result.get("ok"): return {...}` error-guard block and BEFORE the `kind = result["kind"]` line, insert:

```python
    st.session_state["last_grounded_query"] = {
        "query": result["query"],
        "label": _recipes.describe_query(result["query"]),
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_tools_canonical.py`
Expected: PASS — prints all prior lines plus `last_grounded_query stash OK`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools.py tests/test_tools_canonical.py
git commit -m "feat(phase9): stash last successful grounded query for save-as-recipe"
```

---

### Task 3: Save form + recipe chips + run handler (chat) and "🍳 Recipes" sidebar

**Files:**
- Modify: `src/ui/tabs/chat.py` (imports, consume run flag, save form, chips, `_run_recipe`)
- Modify: `src/ui/sidebar.py` (imports + Recipes section)
- Test: `tests/test_recipes_ui.py` (NEW, AppTest)

- [ ] **Step 1: Write the failing test** — create `tests/test_recipes_ui.py`:

```python
# tests/test_recipes_ui.py — AppTest (real Streamlit runtime, no network)
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from streamlit.testing.v1 import AppTest
from src.agent import recipes

# Isolate the store on a temp path so the test never touches real .app_state.
_TMP = os.path.join(tempfile.mkdtemp(), "recipes.json")
recipes.RECIPES_FILE = _TMP  # module-level default used by load/add/remove

SCRIPT = r'''
import streamlit as st
import pandas as pd
from src.agent import recipes
recipes.RECIPES_FILE = %r  # keep the child runtime on the same temp store
from src.data.canonical import build_feature_matrix
from src.data.app_data import features_from_matrix

orders = pd.DataFrame({
    "customer_id": [1, 1, 2, 2, 3, 3],
    "order_id":    [1, 2, 3, 4, 5, 6],
    "order_date": pd.to_datetime(["2024-01-01","2024-01-10","2024-02-01",
                                  "2024-02-20","2024-01-05","2024-03-01"]),
    "order_amount": [20.0, 25.0, 10.0, 12.0, 40.0, 45.0],
})
matrix = build_feature_matrix(orders)
features, available, active = features_from_matrix(matrix)
st.session_state["features"] = features
st.session_state["orders"] = orders
st.session_state["available"] = available
st.session_state["active_levers"] = active
st.session_state.setdefault("ui_history", [])
st.session_state.setdefault("chat_history", [])

from src.ui.tabs.chat import render_chat
render_chat(features, orders)
''' % _TMP


def _labels(buttons):
    return [b.label for b in buttons]


# A) Save form appears when a grounded query has just run.
at = AppTest.from_string(SCRIPT, default_timeout=60)
at.session_state["last_grounded_query"] = {
    "query": {"table": "customers", "operation": "aggregate",
              "metric": "frequency", "agg": "mean"},
    "label": "Mean of frequency (customers)",
}
at.run()
assert not at.exception, f"chat crashed: {[e.value for e in at.exception]}"
assert any("Save recipe" in (l or "") for l in _labels(at.button)), \
    f"save-recipe button present: {_labels(at.button)}"
print("test_recipes_ui: save form appears OK")

# B) A saved recipe renders a chip, and clicking it runs the query.
recipes.add_recipe("Avg frequency", {"table": "customers", "operation": "aggregate",
                                     "metric": "frequency", "agg": "mean"}, path=_TMP)
at2 = AppTest.from_string(SCRIPT, default_timeout=60).run()
assert not at2.exception, f"chat crashed with a recipe: {[e.value for e in at2.exception]}"
chips = [b for b in at2.button if (b.label or "").startswith("▶ Avg frequency")]
assert chips, f"recipe chip present: {_labels(at2.button)}"
chips[0].click()
at2.run()
assert not at2.exception, f"running recipe crashed: {[e.value for e in at2.exception]}"
hist = at2.session_state["ui_history"]
assert any((m.get("content") or "").startswith("▶ Avg frequency") for m in hist), \
    "recipe run appended a ▶ user marker"
assert any(m.get("type") in ("text", "table", "chart") and m.get("role") == "assistant"
           for m in hist), "recipe run rendered a result card"
print("test_recipes_ui: recipe chip runs OK")

print("test_recipes_ui: ALL PASSED")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_recipes_ui.py`
Expected: FAIL — the save-recipe button is absent (assertion `save-recipe button present` fails), because the chat has no recipe UI yet.

- [ ] **Step 3a: Implement chat changes** — in `src/ui/tabs/chat.py`:

(a) Add imports near the top (with the other `from src...` imports):

```python
from src.agent import recipes as recipe_store
from src.agent import tools
```

(b) At the very start of `render_chat` (before `_render_api_banner()`), consume a pending sidebar run request:

```python
    _pending = st.session_state.pop("run_recipe_id", None)
    if _pending:
        _rec = next((r for r in recipe_store.load_recipes()
                     if r["id"] == _pending), None)
        if _rec:
            _run_recipe(_rec)
```

(c) In `render_chat`, immediately AFTER the starter-chips block and BEFORE `if prompt := st.chat_input(...)`, add:

```python
    _render_save_recipe()
    _render_recipe_chips()
```

(d) Add these three module-level functions (e.g. just below `_submit`):

```python
def _run_recipe(recipe):
    """Deterministic replay of a saved grounded query — no router, no LLM."""
    name = recipe.get("name", "recipe")
    st.session_state.ui_history.append(
        {"role": "user", "type": "text", "content": f"▶ {name}"})
    with st.status(f"🍳 Running “{name}”…", expanded=False) as status:
        result = tools.run_grounded_query(**recipe.get("query", {}))
        status.update(label="Done", state="complete")
    if result.get("status") == "error":
        st.session_state.ui_history.append({
            "role": "assistant", "type": "text",
            "content": f"⚠️ {result.get('error', 'Could not run that recipe.')}"})
    save_session()
    st.rerun()


def _render_save_recipe():
    lgq = st.session_state.get("last_grounded_query")
    if not lgq:
        return
    # Plain widgets (not st.form): a form_submit_button doesn't surface in
    # AppTest.button, and a keyed text_input would show a stale name on the next
    # query. The whole expander disappears once last_grounded_query is cleared,
    # so an unkeyed value= re-seeds correctly each time.
    with st.expander("💾 Save as recipe", expanded=False):
        name = st.text_input("Recipe name", value=lgq.get("label", ""))
        if st.button("Save recipe", key="save_recipe_btn",
                     use_container_width=True):
            recipe_store.add_recipe(name, lgq["query"])
            st.session_state.pop("last_grounded_query", None)
            st.toast("Recipe saved.")
            st.rerun()


def _render_recipe_chips():
    recs = recipe_store.load_recipes()
    if not recs:
        return
    st.caption("🍳 Your recipes:")
    cols = st.columns(min(len(recs), 4))
    for i, rec in enumerate(recs):
        col = cols[i % len(cols)]
        if col.button(f"▶ {rec['name']}", key=f"recipe_chip_{rec['id']}",
                      use_container_width=True):
            _run_recipe(rec)
```

- [ ] **Step 3b: Implement sidebar changes** — in `src/ui/sidebar.py`:

(a) Add the import near the other agent imports at the top:

```python
from src.agent.recipes import load_recipes, remove_recipe
```

(b) At the END of the sidebar body (after the Watches section's `else: st.caption("No watches yet.")` block, still inside the same `with st.sidebar:` / column context the Watches section uses), add:

```python
        st.divider()
        st.markdown("### 🍳 Recipes")
        st.caption("Saved one-click questions. Run recomputes on current data.")
        _recipes = load_recipes()
        if _recipes:
            for rec in _recipes:
                row, runb, delb = st.columns([4, 1, 1])
                row.markdown(f"**{rec['name']}**")
                if runb.button("▶", key=f"run_recipe_{rec['id']}"):
                    st.session_state["run_recipe_id"] = rec["id"]
                    st.rerun()
                if delb.button("🗑", key=f"del_recipe_{rec['id']}"):
                    remove_recipe(rec["id"])
                    st.rerun()
        else:
            st.caption("No recipes yet.")
```

(Match the exact indentation of the surrounding Watches code — copy its leading whitespace.)

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_recipes_ui.py`
Expected: PASS — prints `save form appears OK`, `recipe chip runs OK`, `ALL PASSED`, exit 0.

If the click test is flaky on the status/rerun cycle, do NOT weaken it — verify `_run_recipe` appends the marker before `st.rerun()` and that `tools.run_grounded_query` renders into `ui_history` (it does for a scalar), and re-run.

- [ ] **Step 5: Commit**

```bash
git add src/ui/tabs/chat.py src/ui/sidebar.py tests/test_recipes_ui.py
git commit -m "feat(phase9): save-as-recipe form, chat chips, sidebar list + deterministic run"
```

---

### Task 4: Pin `anthropic` + README pass (Part B — polish)

**Files:**
- Modify: `requirements.txt` (UTF-16 — preserve encoding)
- Modify/Create: `README.md`

- [ ] **Step 1: Detect the installed anthropic version**

Run: `..\venv\Scripts\pip show anthropic`
Note the `Version:` line (call it `<V>`, e.g. `0.69.0`).

- [ ] **Step 2: Pin it (preserve UTF-16)**

Read `requirements.txt`, find the line that is exactly `anthropic` (or `anthropic` with trailing whitespace), and change it to `anthropic>=<V>` using the installed version from Step 1. The file is UTF-16; write it back as UTF-16 (in Python: `open(path, encoding="utf-16")` to read, `encoding="utf-16"` to write). Do not alter any other line or the encoding.

- [ ] **Step 3: Verify the requirements file still parses**

Run: `..\venv\Scripts\pip install -r requirements.txt --dry-run`
Expected: it resolves without a parse error (it may report "Requirement already satisfied" for everything — that's success).

- [ ] **Step 4: Write the README** — overwrite `README.md` at the project root with:

```markdown
# Customer Loyalty Intelligence Agent

A chat-first analytics agent for e-commerce customer loyalty. Ask questions in
plain language; every number you see is computed deterministically from real
data — the LLM chooses the analysis and narrates the result, it never invents a
figure.

## What it does

- **Chat-first.** One conversation is the whole app. Ask it to score customers,
  compare power users vs. regulars, find the "happy path" to loyalty, flag churn
  risk, simulate a campaign, or draft target lists / emails / action plans.
- **Grounded data queries.** For novel questions no built-in analysis covers
  ("average order value by category", "how many customers have recency over 90
  days", "is frequency correlated with spend?"), a constrained query tool computes
  the real answer over your data.
- **Recipes.** Save a good query as a named, one-click action; it recomputes on
  current data every time — and works even if the LLM is rate-limited.
- **Bring your own data.** Upload your own CSV/Excel; the app proposes a column
  mapping, you confirm it, and it runs the full analysis on your dataset. A
  built-in Instacart demo flows through the same pipeline.
- **Trust by construction.** All analysis is deterministic Python over a canonical
  data model; the app degrades with a clear message (never a crash or a made-up
  number) when a feature isn't available for a dataset.

## Run locally

The virtualenv lives in the outer directory; launch from this inner directory so
data paths resolve correctly:

```powershell
# From customer-loyalty-agent/customer-loyalty-agent/
..\venv\Scripts\python.exe -m streamlit run app.py
```

On first run it reads the committed canonical demo artifacts under
`data/artifacts/canonical/` (fast). Add API keys in a `.env` in this directory:

```
GEMINI_KEY_1=your_key           # up to GEMINI_KEY_10
ANTHROPIC_API_KEY=your_key      # optional: enables Gemini→Claude failover
```

Get a free Gemini key at https://aistudio.google.com/apikey.

## Deploy (Streamlit Community Cloud)

1. Push to GitHub.
2. New app → point at this repo, main file `app.py`.
3. In the app's **Secrets**, add `GEMINI_KEY_1 = "..."` (and optionally
   `ANTHROPIC_API_KEY`). The committed parquet artifacts supply the demo data —
   no raw CSV upload needed.

## How it works

- **Canonical data model** (`src/data/`): every dataset — the demo or an upload —
  becomes one `orders` + optional `order_items` shape and a per-customer feature
  matrix, with each feature tagged available/unavailable so nothing downstream
  breaks on a missing column.
- **Analysis** (`src/analysis/`): pure, Streamlit-free scoring / segmentation /
  churn / simulation / grounded query — independently testable.
- **Agent** (`src/agent/`): a provider-agnostic tool loop (Gemini, failing over to
  Claude) drives typed tools; a dispatch ladder routes each message to a saved
  recipe, a known tool, or a multi-step goal.
- **LLM backends**: `GEMINI_KEY_*` rotate across model buckets; an optional
  `ANTHROPIC_API_KEY` adds a Claude failover tier for text/reasoning calls.

## Tests

Standalone scripts (no network), each exits non-zero on failure, e.g.:

```powershell
..\venv\Scripts\python.exe tests/test_query.py
..\venv\Scripts\python.exe tests/test_recipes.py
..\venv\Scripts\python.exe tests/test_tools_canonical.py
```

See `CLAUDE.md` for the full architecture reference and project journal.
```

- [ ] **Step 5: Commit**

```bash
git add requirements.txt README.md
git commit -m "chore(phase9): pin anthropic; presentable README"
```

---

### Task 5: Regression sweep + journal + spec status

**Files:**
- Modify: `CLAUDE.md` (journal entry at top)
- Modify: `docs/superpowers/specs/2026-07-13-phase9-recipes-and-hardening-design.md` (status line)

- [ ] **Step 1: Run the no-network regression suite** — each must exit 0:

```powershell
..\venv\Scripts\python.exe tests/test_recipes.py
..\venv\Scripts\python.exe tests/test_recipes_ui.py
..\venv\Scripts\python.exe tests/test_tools_canonical.py
..\venv\Scripts\python.exe tests/test_query.py
..\venv\Scripts\python.exe tests/test_tool_specs.py
..\venv\Scripts\python.exe tests/test_dispatch.py
..\venv\Scripts\python.exe tests/test_chat_shell.py
..\venv\Scripts\python.exe tests/test_full_numbers.py
```

If any errors, STOP and fix the root cause (do not edit tests to force a pass).

- [ ] **Step 2: Add the journal entry** — prepend to the Project Journal in `CLAUDE.md`, immediately below `## 📓 Project Journal` and above the 2026-07-13 Phase 8 entry:

```markdown
### 2026-07-13 — Intelligence Layer / Chat-First, Phase 9: Recipes + finishing pass
The last roadmap item. A good grounded-query answer can now be saved as a named,
one-click "recipe" that recomputes on live data — closing the chat-first roadmap.
- **`src/agent/recipes.py`** (NEW, pure / Streamlit-free): best-effort JSON store
  at `.app_state/recipes.json` (same shape/guarantees as `watches.py`) holding
  `{id,name,query,created}` — `query` is exactly the `run_grounded_query` arg dict.
  No raw data, numbers, or code at rest. `load_recipes`/`add_recipe`
  (blank name → derived label)/`remove_recipe` + pure `describe_query` (scalar /
  grouped / correlation / filtered labels).
- **`src/agent/tools.py`**: `run_grounded_query` now stashes
  `session_state["last_grounded_query"] = {query, label}` on every SUCCESS (failures
  never overwrite it) — the one seam the save form reads.
- **`src/ui/tabs/chat.py`**: a "💾 Save as recipe" form (name pre-filled with the
  derived label) after a grounded answer; a "🍳 Your recipes" chip row; and
  `_run_recipe` — deterministic replay that calls `run_grounded_query(**query)`
  directly (NOT through `dispatch`, NO LLM), so recipes work even with Gemini quota
  exhausted. `render_chat` consumes a `run_recipe_id` flag set by the sidebar.
- **`src/ui/sidebar.py`**: a "🍳 Recipes" section (mirrors Watches) — list each
  saved recipe with ▶ Run (sets the flag) and 🗑 delete.
- Dispatch `recipe_fn` rung STAYS inert — recipes are chip-triggered with known
  args, no NL matching. Recipes are dataset-agnostic: replaying one whose column is
  absent on a swapped dataset yields the engine's clean "No such column" message,
  never a crash.
- **Finishing pass:** pinned `anthropic` in `requirements.txt`; rewrote `README.md`
  (what it is / run / deploy / trust + data-portability story); browser-smoked the
  live chat → grounded query → save recipe → run recipe flow; dry-ran a
  non-Instacart CSV through upload → mapping-confirm → analyze.
- **Testing:** `tests/test_recipes.py` (store round-trip, describe_query, corrupt
  store, blank-name), `tests/test_recipes_ui.py` (AppTest: save form appears; chip
  renders and running it produces a card, 0 exceptions), extended
  `tests/test_tools_canonical.py` (stash assertion). Full no-network sweep green;
  app boots 0 exceptions. **Roadmap 4→9 complete.**
```

- [ ] **Step 3: Flip the spec status** — in
`docs/superpowers/specs/2026-07-13-phase9-recipes-and-hardening-design.md`, change:
```
**Status:** Approved (design); implementation not yet planned.
```
to:
```
**Status:** Implemented 2026-07-13 (plan: docs/superpowers/plans/2026-07-13-phase9-recipes-and-hardening.md).
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-07-13-phase9-recipes-and-hardening-design.md
git commit -m "docs(phase9): journal entry + mark recipes/hardening spec implemented"
```

---

### Task 6: Browser-smoke + non-Instacart BYOD dry-run (Part B — manual verification)

**This task is controller-run (real browser + real Streamlit server), not a fresh TDD subagent.** No code changes; capture evidence.

- [ ] **Step 1: Launch the app**

Run (background): `..\venv\Scripts\python.exe -m streamlit run app.py`
Open the local URL. Confirm the chat loads with 0 tracebacks.

- [ ] **Step 2: Smoke the recipe flow**
  - Run a normal analysis (e.g. "score customers"); confirm cards render.
  - Ask a grounded question (e.g. "what is the average monetary value?"); confirm a computed metric card appears.
  - Open "💾 Save as recipe", keep the name, Save; confirm the toast and that a "🍳 Your recipes" chip + a sidebar "🍳 Recipes" row appear.
  - Click the chip AND the sidebar ▶; confirm each re-runs and shows a fresh card. Delete via 🗑; confirm it disappears everywhere.
  - Note results (screenshots or a short written confirmation). 0 tracebacks required.

- [ ] **Step 3: Non-Instacart BYOD dry-run**

Create a tiny synthetic non-Instacart CSV (own headers, real money + dates), e.g. `C:\Users\yashw\Desktop\byod_smoke.csv`:

```
cust,invoice,when,total
alice,1001,2024-01-05,42.50
alice,1002,2024-02-10,18.00
bob,1003,2024-01-20,99.99
bob,1004,2024-03-01,12.25
carol,1005,2024-02-15,55.00
```

  - In the sidebar uploader, upload it; on the confirm screen map `cust→customer_id`, `invoice→order_id`, `when→order_date`, `total→order_amount`; Confirm.
  - Confirm the app swaps datasets (badge updates), runs analysis without a crash, and that a grounded question works on the new data.
  - Return to demo via "Back to demo". Note results.

- [ ] **Step 4: Record the outcome**

Add a one-line confirmation to the Phase 9 journal entry in `CLAUDE.md` if anything needed fixing; otherwise the existing "browser-smoked … dry-ran a non-Instacart CSV" line stands. Commit only if you changed a file:

```bash
git add CLAUDE.md
git commit -m "docs(phase9): record browser-smoke + BYOD dry-run outcome"
```

---

## Success criteria (from spec §9)

- After a grounded answer, the user can save it (one click, editable name); the
  recipe persists across restart in `.app_state/recipes.json` (no raw data at rest).
- A saved recipe runs from a chat chip and the sidebar, recomputes on current data,
  and works with the LLM quota exhausted.
- A recipe run on a dataset missing a referenced column shows a clean message.
- Deleting a recipe removes it everywhere.
- Browser-smoke + a non-Instacart BYOD dry-run pass; `anthropic` is pinned; README
  is presentable.
- All no-network suites green; app boots 0 exceptions. Roadmap 4→9 complete.
```

