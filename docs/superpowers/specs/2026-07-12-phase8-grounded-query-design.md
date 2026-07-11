# Phase 8 — Grounded Data-Query Tool: Design

**Date:** 2026-07-12
**Status:** Approved (design); implementation not yet planned.
**Roadmap:** `docs/superpowers/specs/2026-07-05-chat-first-agent-roadmap-design.md` §Phase 8
**Builds on:** Phase 7 chat-first shell + dispatch ladder (the inert `grounded_fn`
rung), Phase 5 canonical-anchored tools, Phase 4.5 provider-agnostic tool loop.

---

## 1. Purpose

Give the agent an **out-of-box escape hatch**: one constrained tool that computes
real aggregations, group-bys, and correlations over the canonical tables, so the
chat can answer novel questions that no purpose-built tool (`run_scoring_analysis`,
`analyze_churn_risk`, `search_users`, …) covers — without ever letting the LLM
invent a number.

### Trust invariant (must hold)

> Every figure the user sees is computed deterministically by code over real data.
> The LLM only chooses the query and narrates the computed result — it never
> computes or fabricates a value.

This is why the design is a **constrained query surface**, not runtime code
generation.

---

## 2. Locked decisions (from brainstorming, 2026-07-12)

| Decision | Choice | Why |
|---|---|---|
| Invocation | **Normal tool only** — one `run_grounded_query` in `ALL_TOOLS` | Reuses the Phase-4.5 tool loop (Gemini→Claude failover, auto-derived schema); no new LLM-plumbing. The dispatch `grounded_fn` rung stays inert (documented hook for later). |
| Capability scope | **Aggregate + group-by + correlate** | Covers the novel questions existing tools lack; `search_users` already covers simple filtering. |
| Query shape | **Flat scalar params** | Fits the existing auto-derived tool schema; per-field validation; a Phase-9 recipe is literally the saved arg dict. One filter condition per query in v1. |
| Tables | **All 3 (customers / orders / order_items), degrade `order_items`** | Full power locally and on real uploads; honest graceful message on the cloud artifact path where `order_items` is `None`. |

---

## 3. Architecture

Two units, matching the repo convention (pure analysis engine + thin Streamlit
tool wrapper).

### 3.1 `src/analysis/query.py` (NEW — pure, Streamlit-free)

One entry point:

```python
def run_query(
    tables,                 # {"customers": DataFrame, "orders": DataFrame,
                            #  "order_items": DataFrame | None}
    *,
    table="customers",      # customers | orders | order_items
    operation="aggregate",  # aggregate | correlate
    metric="", agg="mean",  # aggregate: column + count|sum|mean|median|min|max
    group_by="",            # optional dimension column
    filter_column="", filter_op="", filter_value="", filter_value2="",
    column_a="", column_b="",   # correlate: two numeric columns
    limit=20,
) -> dict:
    ...
```

Returns a plain result dict, **never raises**:

```python
# scalar aggregate
{"ok": True, "kind": "scalar", "value": 47.3, "n": 1284, "query": {...}}
# grouped aggregate
{"ok": True, "kind": "table", "rows": [{"category": "Produce", "value": 51.2}, ...],
 "n_groups": 12, "truncated": False, "query": {...}}
# correlation
{"ok": True, "kind": "correlation", "r": 0.62, "n": 1284, "query": {...}}
# any guard failure
{"ok": False, "error": "No such column 'foo'. Available columns: ..."}
```

`query` echoes the resolved, validated arguments — this is exactly what Phase 9
freezes into a recipe (no extra Phase-8 work).

### 3.2 `src/agent/tools.py` → `run_grounded_query(...)` (NEW tool)

Thin wrapper added to `ALL_TOOLS`, auto-registered by `tool_specs`
(`spec_from_function`) because every parameter is a scalar with a default:

```python
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
    """Run a constrained aggregate / group-by / correlation over the canonical
    tables for a question no other tool covers. Every number is computed here,
    not by you — narrate only the returned figures."""
```

Responsibilities:
1. Assemble `tables` from `session_state`:
   `{"customers": features, "orders": orders, "order_items": full_data}`
   (confirmed keys: feature matrix = `features`, orders = `orders`,
   order_items = `full_data`, which is `None` on the artifact path).
2. Call `run_query(...)`.
3. Render into `ui_history` (same mechanism as `search_users`):
   - `scalar` → a metric / one-line result;
   - `table` → a sorted table (capped at `limit`), optionally a bar chart;
   - `correlation` → r, n, and a plain-language strength/direction label.
4. Return the "narrate only these numbers" instruction dict, including a short
   restatement of what was computed.

The docstring's first line becomes the tool description the model reads (per
`spec_from_function`), so it must clearly say "for novel questions no other tool
covers; numbers are computed here, not by you."

---

## 4. Data flow

1. A novel user question reaches the chat; the Phase-4.5 tool loop lets the LLM
   pick `run_grounded_query` and fill the scalar fields.
2. Wrapper builds `tables` from `session_state`, calls the pure engine.
3. Engine: resolve `table` → apply the single filter (value coerced to the
   column's type) → run `aggregate` (optionally `groupby`) or `correlate`
   (Pearson r) → return the result dict.
4. Wrapper renders the element into `ui_history` and returns the instruction.
5. The LLM narrates only the returned figures.

---

## 5. Safety / never-malfunctions guards

Every branch returns a clear `{"ok": False, "error": ...}` message — never a
stack trace. This is the firewall that keeps the tool safe on arbitrary client
data.

- **Whitelists:** `table ∈ {customers, orders, order_items}`;
  `operation ∈ {aggregate, correlate}`;
  `agg ∈ {count, sum, mean, median, min, max}`;
  `filter_op ∈ {>, <, >=, <=, ==, between}`. Off-list → error message.
- **Column existence:** every referenced column (`metric`, `group_by`,
  `filter_column`, `column_a`, `column_b`) must exist in the chosen table's real
  columns; otherwise "no such column; available columns are: …". Reading the
  actual columns (never assuming Instacart names) is what makes it dataset-safe.
- **Type checks:** numeric aggs (sum/mean/median/min/max) and correlation require
  numeric columns → else a plain message. `count` works on any column. Filter
  value is coerced to numeric when the column is numeric, else treated as string
  equality; `between` requires both bounds.
- **`order_items` degradation:** `table="order_items"` while `tables["order_items"]`
  is `None` → `{"ok": False, "error": "That needs product-level data, which isn't
  loaded for this dataset."}` (same honest pattern happy_path uses).
- **Bounds:** grouped results sorted and capped at `limit` (hard max 50, `truncated`
  flagged); correlation needs ≥2 non-null pairs; empty filtered population →
  "no rows matched" (no divide-by-zero). No `eval`, no arbitrary expressions —
  only whitelisted ops over named columns.

---

## 6. Testing (standalone scripts, repo convention — no network)

- **`tests/test_query.py`** (NEW) — the engine contract on hand-computable
  fixtures: each `agg`; group-by correctness; Pearson r vs a known value; every
  `filter_op` including `between`; string-equality filter; and every guard
  (bad table/op/agg/column, non-numeric metric, `order_items=None` degradation,
  empty population, `limit` cap + `truncated`).
- **`tests/test_tools_canonical.py`** (EXTEND) — drive `run_grounded_query`
  through a real Streamlit runtime (existing AppTest pattern) on orders-only
  canonical data: assert 0 exceptions; a scalar aggregate and a correlation both
  return real numbers; an `order_items` query degrades cleanly.
- Regression: full no-network suite stays green; app boots 0 exceptions.

---

## 7. Out of scope (v1 — YAGNI)

- Multiple / OR / nested filters (one condition per query; a second filter is a
  later extension).
- Joins the engine doesn't need: `order_items` questions read `order_items`
  directly; customer-level cross-column questions use the already-joined feature
  matrix.
- Raw-row listing (`search_users` owns that).
- Time-series / date bucketing.
- Saving recipes — that is **Phase 9**. Phase 8 only makes the query arguments
  cleanly recipe-shaped (the `query` echo in the result dict).
- Wiring the dispatch `grounded_fn` rung — stays inert; this tool is reached via
  normal function calling.

---

## 8. Success criteria

- The agent can answer at least these novel questions with real computed numbers:
  "average order value by category", "how many customers have recency over 90
  days", "is frequency correlated with monetary value?" — none of which an
  existing tool answers.
- Every referenced column is validated against the live dataset; a bad column,
  bad op, or absent `order_items` yields a clear message, never a crash.
- The returned `query` dict is a complete, replayable description of the
  computation (Phase-9-ready).
- All no-network suites green; app boots 0 exceptions.
