# Phase 8 — Grounded Data-Query Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one constrained `run_grounded_query` tool so the chat can answer novel aggregate / group-by / correlation questions no purpose-built tool covers — with every number computed deterministically from real data, never invented by the LLM.

**Architecture:** Two units matching the repo convention — a pure, Streamlit-free engine (`src/analysis/query.py`, one `run_query()` entry point that NEVER raises and returns a plain result dict) and a thin Streamlit tool wrapper (`run_grounded_query` in `src/agent/tools.py`, added to `ALL_TOOLS`). The wrapper assembles the canonical tables from `session_state`, calls the engine, renders the result into `ui_history`, and returns a "narrate only these numbers" instruction. Auto-registration through `spec_from_function` means no hand-written schema — every param is a scalar with a default.

**Tech Stack:** Python, pandas (`pandas.api.types.is_numeric_dtype`), Streamlit `session_state` + `AppTest` for the runtime test. Standalone-script tests (not pytest), run with the venv interpreter.

**Spec:** `docs/superpowers/specs/2026-07-12-phase8-grounded-query-design.md`

**Key facts confirmed against the codebase (do not re-derive):**
- Tables in `session_state`: `features` (customers), `orders` (orders), `full_data` (order_items; `None` on the cloud artifact path). Confirmed in `app.py:37-39`.
- `spec_from_function` (`src/agent/tool_specs.py:29-30`) uses **only the first line** of the docstring as the model-facing description, and derives the schema from the typed signature. So `run_grounded_query`'s docstring first line must be a complete, self-contained sentence, and every parameter must be a scalar (`str`/`int`) with a default so it becomes optional.
- `TOOL_SPECS` is built once at import from `ALL_TOOLS`; adding the function to `ALL_TOOLS` (`src/agent/tools.py:827-840`) is all that's needed to register it.
- `ui_history` entry shapes (from `src/agent/tools.py`): text = `{"role","type":"text","content"}`; table = `{"role","type":"table","title","data"}`; bar chart = `{"role","type":"chart","chart_type":"bar","title","data","x","y"}`.
- Tests are standalone scripts: `sys.path.insert(...)`, `assert`, `print`, non-zero exit on failure. Run from the inner project dir with `..\venv\Scripts\python.exe tests/<file>.py`.

---

### Task 1: Pure query engine (`src/analysis/query.py`)

**Files:**
- Create: `src/analysis/query.py`
- Test: `tests/test_query.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_query.py`:

```python
# tests/test_query.py — standalone script (pure engine, no network, no Streamlit)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.analysis.query import run_query

# Hand-computable fixtures ----------------------------------------------------
customers = pd.DataFrame({
    "customer_id": [1, 2, 3, 4, 5],
    "frequency":   [10, 20, 30, 40, 50],   # mean 30, sum 150, median 30
    "monetary":    [100.0, 400.0, 900.0, 1600.0, 2500.0],
    "recency_days":[5, 50, 95, 120, 200],
    "region":      ["N", "N", "S", "S", "S"],  # N: freq 10,20 ; S: 30,40,50
})
orders = pd.DataFrame({
    "order_id":     [1, 2, 3, 4],
    "order_amount": [10.0, 20.0, 30.0, 40.0],
    "category":     ["a", "a", "b", "b"],
})
tables = {"customers": customers, "orders": orders, "order_items": None}

def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol

# 1) scalar aggregates: every agg -------------------------------------------
r = run_query(tables, table="customers", operation="aggregate", metric="frequency", agg="mean")
assert r["ok"] and r["kind"] == "scalar" and approx(r["value"], 30.0), r
assert r["n"] == 5 and r["query"]["metric"] == "frequency", r
assert run_query(tables, metric="frequency", agg="sum")["value"] == 150.0
assert run_query(tables, metric="frequency", agg="median")["value"] == 30.0
assert run_query(tables, metric="frequency", agg="min")["value"] == 10.0
assert run_query(tables, metric="frequency", agg="max")["value"] == 50.0
assert run_query(tables, metric="region", agg="count")["value"] == 5   # count works on text
print("test_query: scalar aggregates OK")

# 2) group-by ----------------------------------------------------------------
g = run_query(tables, table="customers", operation="aggregate",
              metric="frequency", agg="mean", group_by="region")
assert g["ok"] and g["kind"] == "table" and g["n_groups"] == 2, g
by = {row["group"]: row["value"] for row in g["rows"]}
assert approx(by["N"], 15.0) and approx(by["S"], 40.0), g   # N=(10+20)/2, S=(30+40+50)/3
# sorted descending by value: S (40) before N (15)
assert g["rows"][0]["group"] == "S", g
assert g["truncated"] is False, g
print("test_query: group-by OK")

# 3) limit cap + truncated ---------------------------------------------------
many = pd.DataFrame({"g": list(range(60)), "v": list(range(60))})
gt = run_query({"customers": many}, metric="v", agg="sum", group_by="g", limit=100)
assert len(gt["rows"]) == 50 and gt["truncated"] is True and gt["n_groups"] == 60, gt
gsmall = run_query({"customers": many}, metric="v", agg="sum", group_by="g", limit=5)
assert len(gsmall["rows"]) == 5 and gsmall["truncated"] is True, gsmall
print("test_query: limit cap + truncated OK")

# 4) filters: every op -------------------------------------------------------
f = run_query(tables, metric="frequency", agg="count",
              filter_column="recency_days", filter_op=">", filter_value="90")
assert f["value"] == 3, f   # 95, 120, 200
assert run_query(tables, metric="frequency", agg="count",
                 filter_column="recency_days", filter_op="<", filter_value="90")["value"] == 2
assert run_query(tables, metric="frequency", agg="count",
                 filter_column="recency_days", filter_op=">=", filter_value="95")["value"] == 3
assert run_query(tables, metric="frequency", agg="count",
                 filter_column="recency_days", filter_op="<=", filter_value="50")["value"] == 2
assert run_query(tables, metric="frequency", agg="count",
                 filter_column="frequency", filter_op="==", filter_value="30")["value"] == 1
btw = run_query(tables, metric="frequency", agg="count", filter_column="recency_days",
                filter_op="between", filter_value="50", filter_value2="120")
assert btw["value"] == 3, btw   # 50, 95, 120
# string-equality filter
seq = run_query(tables, metric="frequency", agg="sum",
                filter_column="region", filter_op="==", filter_value="S")
assert seq["value"] == 120.0, seq   # 30+40+50
print("test_query: filters OK")

# 5) correlation -------------------------------------------------------------
c = run_query(tables, table="customers", operation="correlate",
              column_a="frequency", column_b="monetary")
assert c["ok"] and c["kind"] == "correlation", c
assert 0.9 <= c["r"] <= 1.0 and c["n"] == 5, c   # monetary = (freq/10)^2 * 100, strongly +
print("test_query: correlation OK")

# 6) guards: never raise, always {"ok": False, "error": str} ----------------
def bad(**kw):
    out = run_query(tables, **kw)
    assert out["ok"] is False and isinstance(out.get("error"), str) and out["error"], out
    return out["error"]

assert "table" in bad(table="widgets").lower()
assert "operation" in bad(operation="frobnicate").lower()
assert "aggregation" in bad(metric="frequency", agg="stddev").lower()
assert "no such column" in bad(metric="nope").lower()
assert "no such column" in bad(metric="frequency", group_by="nope").lower()
assert "numeric" in bad(metric="region", agg="mean").lower()          # sum/mean on text
assert "numeric" in bad(operation="correlate", column_a="region", column_b="frequency").lower()
assert "product-level" in bad(table="order_items").lower()            # None degradation
# empty filtered population -> no divide-by-zero, clear message
empty = run_query(tables, metric="frequency", agg="mean",
                  filter_column="frequency", filter_op=">", filter_value="9999")
assert empty["ok"] is False and "no rows" in empty["error"].lower(), empty
# correlation needs >= 2 non-null pairs
one = run_query({"customers": pd.DataFrame({"a": [1.0], "b": [2.0]})},
                operation="correlate", column_a="a", column_b="b")
assert one["ok"] is False and "at least 2" in one["error"].lower(), one
# between with a missing bound
mb = run_query(tables, metric="frequency", agg="count", filter_column="recency_days",
               filter_op="between", filter_value="50")
assert mb["ok"] is False and "between" in mb["error"].lower(), mb
print("test_query: guards OK")

print("test_query: ALL PASSED")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_query.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.analysis.query'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/analysis/query.py`:

```python
"""Grounded data-query engine (pure, Streamlit-free).

One entry point, run_query(), computes constrained aggregates / group-bys /
correlations over the canonical tables. It NEVER raises: every guard failure
returns {"ok": False, "error": <plain message>}. This is the firewall that keeps
the tool safe on arbitrary client data — the LLM picks the query, code does the
math, and every referenced column is validated against the real dataframe.
"""

import pandas as pd
from pandas.api.types import is_numeric_dtype

TABLES = ("customers", "orders", "order_items")
OPERATIONS = ("aggregate", "correlate")
AGGS = ("count", "sum", "mean", "median", "min", "max")
_NUMERIC_AGGS = ("sum", "mean", "median", "min", "max")
FILTER_OPS = (">", "<", ">=", "<=", "==", "between")
_HARD_LIMIT = 50


def _err(msg):
    return {"ok": False, "error": msg}


def _cols_msg(df):
    return "Available columns: " + ", ".join(map(str, df.columns)) + "."


def _resolve_table(tables, table):
    """Return (df, None) on success or (None, error_dict) on any problem."""
    if table not in TABLES:
        return None, _err(f"No such table '{table}'. Choose one of: {', '.join(TABLES)}.")
    df = (tables or {}).get(table)
    if df is None:
        if table == "order_items":
            return None, _err("That needs product-level data, which isn't loaded for this dataset.")
        return None, _err(f"The '{table}' table isn't loaded for this dataset.")
    if len(df) == 0:
        return None, _err(f"The '{table}' table has no rows.")
    return df, None


def _coerce(df, col, raw):
    """Coerce a raw filter value to the column's type. Returns (value, None) or (None, error)."""
    if is_numeric_dtype(df[col]):
        try:
            return float(raw), None
        except (TypeError, ValueError):
            return None, _err(f"Filter value '{raw}' is not numeric, but column '{col}' is.")
    return str(raw), None


def _apply_filter(df, column, op, value, value2):
    """Apply one filter condition. Returns (df, None) or (None, error). No filter -> unchanged."""
    if not column and not op:
        return df, None
    if not column or not op:
        return None, _err("A filter needs both a column and an operator.")
    if column not in df.columns:
        return None, _err(f"No such column '{column}'. {_cols_msg(df)}")
    if op not in FILTER_OPS:
        return None, _err(f"No such filter operator '{op}'. Choose one of: {', '.join(FILTER_OPS)}.")
    if op == "between":
        if value in ("", None) or value2 in ("", None):
            return None, _err("'between' needs two bounds (filter_value and filter_value2).")
        lo, err = _coerce(df, column, value)
        if err:
            return None, err
        hi, err = _coerce(df, column, value2)
        if err:
            return None, err
        return df[(df[column] >= lo) & (df[column] <= hi)], None
    val, err = _coerce(df, column, value)
    if err:
        return None, err
    if op == "==":
        return df[df[column] == val], None
    if not is_numeric_dtype(df[column]):
        return None, _err(f"Operator '{op}' needs a numeric column, but '{column}' is text.")
    cmp = {">": df[column] > val, "<": df[column] < val,
           ">=": df[column] >= val, "<=": df[column] <= val}[op]
    return df[cmp], None


def _compute(series, agg):
    if agg == "count":
        return int(series.count())
    return float(getattr(series, agg)())


def _aggregate(df, metric, agg, group_by, limit):
    if agg not in AGGS:
        return _err(f"No such aggregation '{agg}'. Choose one of: {', '.join(AGGS)}.")
    if not metric:
        return _err("An aggregate needs a metric column.")
    if metric not in df.columns:
        return _err(f"No such column '{metric}'. {_cols_msg(df)}")
    if agg in _NUMERIC_AGGS and not is_numeric_dtype(df[metric]):
        return _err(f"'{agg}' needs a numeric column, but '{metric}' is text. Use 'count' instead.")
    if len(df) == 0:
        return _err("No rows matched — nothing to aggregate.")
    if group_by:
        if group_by not in df.columns:
            return _err(f"No such column '{group_by}'. {_cols_msg(df)}")
        grouped = df.groupby(group_by)[metric].agg(agg).sort_values(ascending=False)
        cap = max(1, min(int(limit or 20), _HARD_LIMIT))
        truncated = len(grouped) > cap
        rows = [{"group": str(k),
                 "value": (int(v) if agg == "count" else round(float(v), 4))}
                for k, v in grouped.head(cap).items()]
        return {"ok": True, "kind": "table", "rows": rows,
                "n_groups": int(len(grouped)), "truncated": truncated}
    value = _compute(df[metric], agg)
    return {"ok": True, "kind": "scalar",
            "value": (round(value, 4) if isinstance(value, float) else value),
            "n": int(len(df))}


def _correlate(df, column_a, column_b):
    for c in (column_a, column_b):
        if not c:
            return _err("Correlation needs two columns (column_a and column_b).")
        if c not in df.columns:
            return _err(f"No such column '{c}'. {_cols_msg(df)}")
        if not is_numeric_dtype(df[c]):
            return _err(f"Correlation needs numeric columns, but '{c}' is text.")
    pair = df[[column_a, column_b]].dropna()
    if len(pair) < 2:
        return _err("Not enough overlapping numeric values to correlate (need at least 2).")
    r = pair[column_a].corr(pair[column_b])
    if pd.isna(r):
        return _err("Correlation is undefined (one column has no variation).")
    return {"ok": True, "kind": "correlation", "r": round(float(r), 4), "n": int(len(pair))}


def run_query(tables, *, table="customers", operation="aggregate",
              metric="", agg="mean", group_by="",
              filter_column="", filter_op="", filter_value="", filter_value2="",
              column_a="", column_b="", limit=20):
    """Constrained aggregate / group-by / correlation over the canonical tables.

    Returns a plain result dict and NEVER raises. On success the dict carries the
    resolved `query` echo (Phase-9-ready); on any guard failure it is
    {"ok": False, "error": <plain message>}.
    """
    query = {"table": table, "operation": operation, "metric": metric, "agg": agg,
             "group_by": group_by, "filter_column": filter_column,
             "filter_op": filter_op, "filter_value": filter_value,
             "filter_value2": filter_value2, "column_a": column_a,
             "column_b": column_b, "limit": limit}
    try:
        if operation not in OPERATIONS:
            return _err(f"No such operation '{operation}'. Choose one of: {', '.join(OPERATIONS)}.")
        df, err = _resolve_table(tables, table)
        if err:
            return err
        df, err = _apply_filter(df, filter_column, filter_op, filter_value, filter_value2)
        if err:
            return err
        result = (_aggregate(df, metric, agg, group_by, limit)
                  if operation == "aggregate"
                  else _correlate(df, column_a, column_b))
        if result.get("ok"):
            result["query"] = query
        return result
    except Exception as e:  # belt-and-suspenders: the tool must never crash the chat
        return _err(f"Query failed: {type(e).__name__}: {e}")
```

Note on `groupby(...).agg("count")`: pandas `SeriesGroupBy.agg("count")` counts non-null per group, matching the scalar `count` path.

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_query.py`
Expected: PASS — prints `test_query: ALL PASSED` and exits 0.

- [ ] **Step 5: Commit**

```bash
git add src/analysis/query.py tests/test_query.py
git commit -m "feat(phase8): pure grounded-query engine (aggregate/group-by/correlate) + guards"
```

---

### Task 2: `run_grounded_query` tool wrapper + register in `ALL_TOOLS`

**Files:**
- Modify: `src/agent/tools.py` (add import, the wrapper + helpers, extend `ALL_TOOLS`)
- Test: `tests/test_tools_canonical.py` (extend the existing AppTest script)

- [ ] **Step 1: Write the failing test**

Extend `tests/test_tools_canonical.py`. First, add these calls inside the `SCRIPT` string, immediately after the `r["happy"] = tools.run_happy_path(3)` line (line 48):

```python
# Phase 8 grounded query — scalar aggregate, correlation, order_items degrade.
r["gq_scalar"] = tools.run_grounded_query(
    table="customers", operation="aggregate", metric="frequency", agg="mean")
r["gq_corr"] = tools.run_grounded_query(
    table="customers", operation="correlate", column_a="frequency", column_b="monetary")
r["gq_badcol"] = tools.run_grounded_query(
    table="customers", operation="aggregate", metric="does_not_exist", agg="mean")
r["gq_items"] = tools.run_grounded_query(
    table="order_items", operation="aggregate", metric="anything", agg="count")
```

Then add these assertions at the END of the file (after the happy_path assertions, line 106):

```python
# --- Phase 8: run_grounded_query on canonical (orders-only) data ---
assert r["gq_scalar"]["status"] == "success", f"grounded scalar failed: {r['gq_scalar']}"
assert isinstance(r["gq_scalar"].get("value"), (int, float)), "grounded scalar returned a real number"
assert r["gq_scalar"]["n"] >= 1, "grounded scalar counted real rows"
print("test_tools_canonical: run_grounded_query scalar OK on canonical data")

assert r["gq_corr"]["status"] == "success", f"grounded correlation failed: {r['gq_corr']}"
assert isinstance(r["gq_corr"].get("r"), (int, float)), "grounded correlation returned a real r"
print("test_tools_canonical: run_grounded_query correlation OK on canonical data")

assert r["gq_badcol"]["status"] == "error", "grounded query reports a bad column as an error"
assert "no such column" in r["gq_badcol"]["error"].lower(), r["gq_badcol"]
print("test_tools_canonical: run_grounded_query bad-column degrades cleanly")

assert r["gq_items"]["status"] == "error", "order_items query degrades (not loaded on canonical)"
assert "product-level" in r["gq_items"]["error"].lower(), r["gq_items"]
print("test_tools_canonical: run_grounded_query order_items degrades cleanly")
```

Note: the fixture in this test builds `features` from an orders-only matrix, so `frequency` and `monetary` are present canonical core features (RFM). `orders`/`full_data` are NOT set in this fixture's `session_state`, so the wrapper's `.get('orders')` / `.get('full_data')` return `None` — which is exactly why `gq_items` must degrade. That is intended coverage.

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_tools_canonical.py`
Expected: FAIL — `AttributeError: module 'src.agent.tools' has no attribute 'run_grounded_query'` (surfaces as an AppTest exception assertion failure).

- [ ] **Step 3: Write minimal implementation**

In `src/agent/tools.py`, add the engine import near the other analysis imports (after line 31, `from src.analysis import simulation`):

```python
from src.analysis.query import run_query
```

Add these helpers and the tool function just before the `# All tools Gemini can call` block (line 826):

```python
def _gq_fmt(v):
    """Human number for a scalar result."""
    return f"{v:,.2f}" if isinstance(v, float) else f"{v:,}"


def _gq_corr_label(r):
    """Plain-language strength + direction for a Pearson r."""
    a = abs(r)
    if a < 0.1:
        return "no linear relationship"
    strength = ("a weak" if a < 0.3 else "a moderate" if a < 0.6 else "a strong")
    direction = "positive" if r > 0 else "negative"
    return f"{strength} {direction} relationship"


def run_grounded_query(
    table: str = "customers",
    operation: str = "aggregate",
    metric: str = "", agg: str = "mean",
    group_by: str = "",
    filter_column: str = "", filter_op: str = "",
    filter_value: str = "", filter_value2: str = "",
    column_a: str = "", column_b: str = "",
    limit: int = 20,
) -> dict:
    """Run a constrained aggregate, group-by, or correlation over the real data to answer a novel question no other tool covers — every number is computed here, not by you; narrate only the returned figures.

    Use this ONLY when no purpose-built tool fits (scoring, churn, search, simulate).
    Examples it can answer: "average order value by category" (table=orders,
    operation=aggregate, metric=order_amount, agg=mean, group_by=category);
    "how many customers have recency over 90 days" (table=customers, agg=count,
    metric=customer_id, filter_column=recency_days, filter_op=">", filter_value="90");
    "is frequency correlated with monetary value?" (operation=correlate,
    column_a=frequency, column_b=monetary).

    Args:
        table: which table to query — customers, orders, or order_items.
        operation: 'aggregate' (a number, optionally by group) or 'correlate' (two columns).
        metric: the column to aggregate (for operation=aggregate).
        agg: count, sum, mean, median, min, or max.
        group_by: optional column to break the aggregate down by.
        filter_column / filter_op / filter_value / filter_value2: one optional filter,
            e.g. recency_days > 90, or 'between' 50 and 120.
        column_a, column_b: the two numeric columns to correlate (for operation=correlate).
        limit: max groups returned for a group-by (hard max 50).
    """
    features = st.session_state.get('features')
    if features is None:
        return {"error": "Data not loaded yet."}

    tables = {
        "customers": features,
        "orders": st.session_state.get('orders'),
        "order_items": st.session_state.get('full_data'),
    }
    result = run_query(
        tables, table=table, operation=operation, metric=metric, agg=agg,
        group_by=group_by, filter_column=filter_column, filter_op=filter_op,
        filter_value=filter_value, filter_value2=filter_value2,
        column_a=column_a, column_b=column_b, limit=limit,
    )

    if not result.get("ok"):
        return {
            "status": "error",
            "error": result.get("error", "That query could not be run."),
            "instruction": (
                "Relay this message to the user plainly. Do NOT invent a number; "
                "if a column is unavailable, say so and suggest a valid one."
            ),
        }

    kind = result["kind"]

    if kind == "scalar":
        label = f"{agg.title()} of {metric.replace('_', ' ')}"
        st.session_state.ui_history.append({
            "role": "assistant", "type": "text",
            "content": (f"### 📐 {label}\n\n**{_gq_fmt(result['value'])}**  \n"
                        f"_computed over {result['n']:,} rows_"),
        })
        return {
            "status": "success", "kind": "scalar", "computed": label,
            "value": result["value"], "n": result["n"], "query": result["query"],
            "instruction": "State this computed figure in one sentence. Use ONLY this number.",
        }

    if kind == "table":
        dim = group_by or "group"
        val_col = f"{agg} of {metric}"
        tdf = pd.DataFrame([{dim: row["group"], val_col: row["value"]}
                            for row in result["rows"]])
        title = f"📊 {agg.title()} of {metric.replace('_', ' ')} by {group_by}"
        st.session_state.ui_history.append({
            "role": "assistant", "type": "table", "title": title, "data": tdf,
        })
        st.session_state.ui_history.append({
            "role": "assistant", "type": "chart", "chart_type": "bar",
            "title": title, "data": tdf, "x": dim, "y": val_col,
        })
        return {
            "status": "success", "kind": "table", "rows": result["rows"],
            "n_groups": result["n_groups"], "truncated": result["truncated"],
            "query": result["query"],
            "instruction": (
                "Summarize the top groups from this computed table in 2-3 sentences "
                "using ONLY these numbers. Mention if the list was truncated."
            ),
        }

    # correlation
    r = result["r"]
    strength = _gq_corr_label(r)
    st.session_state.ui_history.append({
        "role": "assistant", "type": "text",
        "content": (f"### 🔗 Correlation: {column_a} vs {column_b}\n\n"
                    f"**r = {r:.2f}** — {strength}  \n"
                    f"_computed over {result['n']:,} rows_"),
    })
    return {
        "status": "success", "kind": "correlation", "r": r, "n": result["n"],
        "strength": strength, "query": result["query"],
        "instruction": (
            "Explain in 1-2 sentences what this correlation means in plain language, "
            "using ONLY r and the strength/direction label. Correlation is not causation."
        ),
    }
```

Then add `run_grounded_query` to the `ALL_TOOLS` list (after `simulate_campaign,` at line 839):

```python
    simulate_campaign,
    run_grounded_query,
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_tools_canonical.py`
Expected: PASS — prints the four new `run_grounded_query ...` OK lines and exits 0.

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools.py tests/test_tools_canonical.py
git commit -m "feat(phase8): run_grounded_query tool wrapper + register in ALL_TOOLS"
```

---

### Task 3: Full regression sweep, app-boot check, journal + spec status

**Files:**
- Modify: `CLAUDE.md` (add a dated journal entry at the top of the Project Journal)
- Modify: `docs/superpowers/specs/2026-07-12-phase8-grounded-query-design.md` (flip Status line)

- [ ] **Step 1: Run the no-network regression suite**

Run each and confirm each exits 0 (prints its own OK/PASSED lines):

```powershell
..\venv\Scripts\python.exe tests/test_query.py
..\venv\Scripts\python.exe tests/test_tools_canonical.py
..\venv\Scripts\python.exe tests/test_tool_specs.py
..\venv\Scripts\python.exe tests/test_dispatch.py
..\venv\Scripts\python.exe tests/test_chat_shell.py
..\venv\Scripts\python.exe tests/test_full_numbers.py
```

Expected: every script exits 0. `test_tool_specs.py` and `test_chat_shell.py` transitively confirm the new tool auto-registers (it is now in `ALL_TOOLS` → `TOOL_SPECS`) and the app still boots 0 exceptions. If a script errors, STOP and fix before continuing (do not edit tests to pass — fix the code).

- [ ] **Step 2: Verify the tool is registered in the derived specs**

Run:
```powershell
..\venv\Scripts\python.exe -c "from src.agent.tool_specs import TOOL_SPECS; s=[x for x in TOOL_SPECS if x['name']=='run_grounded_query'][0]; print(s['description'][:60]); print(sorted(s['input_schema']['properties'])); print(s['input_schema']['required'])"
```
Expected: prints the first docstring line (starts "Run a constrained aggregate…"), the 12 scalar property names, and an EMPTY `required` list (every param has a default → all optional).

- [ ] **Step 3: Add the journal entry**

Prepend to the Project Journal in `CLAUDE.md` (immediately below `## 📓 Project Journal`, above the 2026-07-11 Phase 7 entry):

```markdown
### 2026-07-13 — Intelligence Layer / Chat-First, Phase 8: Grounded data-query tool
The agent got an out-of-box escape hatch: one constrained tool that computes real
aggregates, group-bys, and correlations over the canonical tables, so the chat can
answer novel questions no purpose-built tool covers — without ever letting the LLM
invent a number.
- **`src/analysis/query.py`** (NEW, pure / Streamlit-free): `run_query(tables, ...)`
  — the engine. Flat scalar params; whitelisted `table` / `operation` / `agg` /
  `filter_op`; validates every referenced column against the REAL dataframe columns
  (never assumes Instacart names); coerces the one optional filter value to the
  column's type; runs a scalar or grouped aggregate (sorted, capped at `limit`, hard
  max 50, `truncated` flagged) or a Pearson correlation (needs ≥2 non-null pairs).
  NEVER raises — every guard returns `{"ok": False, "error": <plain message>}`, and
  the whole body is wrapped so a bad query degrades into relayable text, never a
  crash. On success it echoes the resolved `query` dict (exactly what Phase 9 will
  freeze into a recipe).
- **`src/agent/tools.py`** → `run_grounded_query(...)` (NEW tool, added to
  `ALL_TOOLS`): assembles `{"customers": features, "orders": orders,
  "order_items": full_data}` from `session_state`, calls the engine, and renders the
  result into `ui_history` — a metric card for a scalar, a sorted table + bar chart
  for a group-by, an r + plain-language strength/direction label for a correlation —
  then returns a "narrate ONLY these numbers" instruction. Auto-registers through
  `spec_from_function` (all-scalar signature); its first docstring line tells the
  model this is for novel questions and that numbers are computed here, not by it.
- **Trust invariant held:** the LLM only picks the query and narrates; code computes
  every figure over real data. On the artifact/cloud path `full_data` is `None`, so
  `order_items` questions degrade with an honest "product-level data isn't loaded"
  message. The dispatch `grounded_fn` rung stays inert — this tool is reached via
  normal function calling.
- **Testing:** `tests/test_query.py` (NEW) — engine contract on hand-computable
  fixtures: every agg, group-by correctness + sort, Pearson r, every `filter_op`
  incl. `between` and string-equality, `limit` cap + `truncated`, and every guard
  (bad table/op/agg/column, non-numeric metric, `order_items=None`, empty
  population, <2 correlation pairs). `tests/test_tools_canonical.py` (EXTENDED) —
  drives `run_grounded_query` through a real Streamlit runtime on orders-only
  canonical data: a scalar and a correlation return real numbers; bad-column and
  `order_items` queries degrade cleanly (0 exceptions). Full no-network sweep green;
  app boots 0 exceptions.
- **Out of scope (v1):** multiple/OR filters, joins, raw-row listing (search_users
  owns that), time-series, and saving recipes (Phase 9 — Phase 8 only makes the
  args recipe-shaped via the `query` echo).
```

- [ ] **Step 4: Flip the spec status**

In `docs/superpowers/specs/2026-07-12-phase8-grounded-query-design.md`, change line 4 from:

```markdown
**Status:** Approved (design); implementation not yet planned.
```
to:
```markdown
**Status:** Implemented 2026-07-13 (plan: docs/superpowers/plans/2026-07-13-phase8-grounded-query.md).
```

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-07-12-phase8-grounded-query-design.md
git commit -m "docs(phase8): journal entry + mark grounded-query spec implemented"
```

---

## Success criteria (from spec §8)

- The agent can answer "average order value by category", "how many customers have
  recency over 90 days", and "is frequency correlated with monetary value?" with real
  computed numbers — none of which an existing tool answers.
- Every referenced column is validated against the live dataset; a bad column, bad op,
  or absent `order_items` yields a clear message, never a crash.
- The returned `query` dict is a complete, replayable description (Phase-9-ready).
- All no-network suites green; app boots 0 exceptions.
