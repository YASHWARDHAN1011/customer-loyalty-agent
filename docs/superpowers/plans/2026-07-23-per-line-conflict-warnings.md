# Per-Line Customer/Date Conflict Warnings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When collapsing a line-grained upload to one row per order, surface (never hide) a discarded `customer_id` or `order_date` conflict as an operator warning, while keeping the existing keep-first behavior unchanged.

**Architecture:** Add two `groupby("order_id").nunique()` checks and two conditional warnings inside `build_canonical` in `src/data/ingest/builder.py`, beside the existing amount-conflict logic. No new module, no UI, no validator change. Warnings-only; the collapse result is byte-for-byte identical to today.

**Tech Stack:** Python, pandas. Tests are standalone scripts (no pytest), run with the project venv.

Spec: `docs/superpowers/specs/2026-07-23-per-line-conflict-warnings-design.md`.

Run tests from the inner `customer-loyalty-agent/` dir with either `python tests/<file>.py` (python is on PATH) or `..\venv\Scripts\python.exe tests/<file>.py`.

---

## File Structure

- **Modify** `src/data/ingest/builder.py` — inside `build_canonical`, after the existing `amt_nunique` line and before/around the groupby-agg, compute `customer_id` and `order_date` per-order nunique and append two conditional warnings to the already-copied `warnings` list.
- **Modify** `tests/test_ingest.py` — add one test function with three checks (customer conflict fires, date conflict fires, clean file silent) and register it in the `main()` runner.
- **Modify** `CLAUDE.md` — add a dated journal entry.

---

## Task 1: Conflict-warning detection in `build_canonical`

**Files:**
- Modify: `src/data/ingest/builder.py` (inside `build_canonical`, the collapse block ~lines 71-104)
- Test: `tests/test_ingest.py` (append a test + register it)

Context for the implementer — the relevant existing code in `build_canonical` looks like this (the `warnings` list is already a copy of `result.warnings`, so appending to it is safe and does not mutate the `ValidationResult`):

```python
    # Copy warnings so we never mutate the ValidationResult's list.
    warnings = list(result.warnings)

    rows_per_order = result.orders.groupby("order_id").size()
    amt_nunique = result.orders.groupby("order_id")["order_amount"].nunique()

    if grain == "line_item":
        ...
    elif grain == "order_level":
        ...
    else:
        ...

    orders = (result.orders
              .groupby("order_id", sort=False)
              .agg(customer_id=("customer_id", "first"),
                   order_date=("order_date", "first"),
                   order_amount=("order_amount", amount_agg))
              .reset_index())
```

### Step 1: Write the failing test

Append this test to `tests/test_ingest.py`, immediately before the `def main():` line:

```python
def test_build_canonical_warns_on_customer_and_date_conflicts():
    from src.data.ingest.builder import build_canonical
    mapping = {"customer_id": "cust", "order_id": "ord",
               "order_date": "when", "order_amount": "amt"}

    # (a) One order_id spanning TWO customers -> strong customer warning, first kept.
    df_cust = pd.DataFrame({
        "cust": ["c1", "c2", "c3"],
        "ord":  ["o1", "o1", "o2"],
        "when": ["2025-01-01", "2025-01-01", "2025-01-02"],
        "amt":  ["10", "10", "20"]})
    res = build_canonical(df_cust, mapping)
    assert res["ok"] is True
    assert any("more than one customer" in w.lower() for w in res["warnings"]), \
        res["warnings"]
    assert any("order id" in w.lower() for w in res["warnings"]), res["warnings"]
    kept = dict(zip(res["orders"]["order_id"], res["orders"]["customer_id"]))
    assert kept["o1"] == "c1"   # first customer kept, unchanged behavior

    # (b) One order_id spanning TWO dates -> soft date warning.
    df_date = pd.DataFrame({
        "cust": ["c1", "c1", "c2"],
        "ord":  ["o1", "o1", "o2"],
        "when": ["2025-01-01", "2025-01-05", "2025-02-01"],
        "amt":  ["10", "10", "20"]})
    res = build_canonical(df_date, mapping)
    assert res["ok"] is True
    assert any("different dates" in w.lower() for w in res["warnings"]), \
        res["warnings"]
    # A pure date conflict must NOT raise the customer warning.
    assert not any("more than one customer" in w.lower() for w in res["warnings"]), \
        res["warnings"]

    # (c) Clean order-grained file (one row per order) -> neither warning.
    df_clean = pd.DataFrame({
        "cust": ["c1", "c2"],
        "ord":  ["o1", "o2"],
        "when": ["2025-01-01", "2025-01-02"],
        "amt":  ["10", "20"]})
    res = build_canonical(df_clean, mapping)
    assert res["ok"] is True
    assert not any("more than one customer" in w.lower() for w in res["warnings"]), \
        res["warnings"]
    assert not any("different dates" in w.lower() for w in res["warnings"]), \
        res["warnings"]
```

Then register it in the `main()` runner. Find the block of `test_build_canonical_*` calls inside `main()` and add this line after `test_build_canonical_threads_currency_end_to_end()`:

```python
    test_build_canonical_warns_on_customer_and_date_conflicts()
```

### Step 2: Run test to verify it fails

Run: `python tests/test_ingest.py`

Expected: FAIL — an `AssertionError` on the `"more than one customer"` assertion (the warning does not exist yet), raised from `test_build_canonical_warns_on_customer_and_date_conflicts` via `main()`.

### Step 3: Write minimal implementation

In `src/data/ingest/builder.py`, inside `build_canonical`, locate the line:

```python
    amt_nunique = result.orders.groupby("order_id")["order_amount"].nunique()
```

Immediately AFTER that line, add the two conflict counts:

```python
    cust_conflicts = int(
        (result.orders.groupby("order_id")["customer_id"].nunique(dropna=False) > 1).sum())
    date_conflicts = int(
        (result.orders.groupby("order_id")["order_date"].nunique(dropna=False) > 1).sum())
```

Then, immediately AFTER the `orders = (result.orders.groupby(...).agg(...).reset_index())`
block and its following `orders = orders[[...]]` reorder line — i.e. just before the
`# build_feature_matrix is exception-safe ...` comment — append the two conditional
warnings:

```python
    if cust_conflicts:
        warnings.append(
            f"{cust_conflicts} order(s) had more than one customer across their "
            f"rows; the first customer was kept. This usually means the Order ID "
            f"column isn't unique per order or is mapped to the wrong column — "
            f"verify the Order ID mapping.")
    if date_conflicts:
        warnings.append(
            f"{date_conflicts} order(s) had rows with different dates (e.g. partial "
            f"shipments); the first date was kept.")
```

(Placement note: the counts must be computed from `result.orders` — the
pre-collapse validated table — so they see every row. The warnings can be appended
anywhere after `warnings = list(result.warnings)` and before the success `return`;
appending them right before `build_feature_matrix` keeps them next to the collapse
they describe.)

### Step 4: Run test to verify it passes

Run: `python tests/test_ingest.py`

Expected: PASS — ends with `NNN checks passed.` and no traceback. (The new test uses
bare `assert`, so it does not change the printed check count; its passing is proven
by `main()` completing without an `AssertionError`.)

To prove the new test actually ran and passed, also run it in isolation:

Run: `python -c "import sys; sys.path.insert(0,'.'); import tests.test_ingest as t; t.test_build_canonical_warns_on_customer_and_date_conflicts(); print('conflict warnings: PASS')"`

Expected: prints `conflict warnings: PASS`, no traceback.

### Step 5: Commit

```bash
git add src/data/ingest/builder.py tests/test_ingest.py
git commit -m "feat: warn on per-order customer/date conflicts during collapse"
```

---

## Task 2: Regression sweep + journal + finish

**Files:**
- Modify: `CLAUDE.md` (journal entry)

### Step 1: Run the related no-network suites

Run each and confirm green (no traceback; each ends in a pass line):

```
python tests/test_ingest.py
python tests/test_canonical.py
python tests/test_upload_flow.py
python tests/test_mapping_persist.py
python tests/test_export.py
python tests/test_tools_canonical.py
```

Expected: `test_ingest` ends `NNN checks passed.`; `test_canonical` `52 checks passed.`;
`test_upload_flow` `test_upload_flow: OK`; `test_mapping_persist` `15 checks passed.`;
`test_export` `17 checks passed.`; `test_tools_canonical` prints its final
`run_grounded_query monetary scalar carries currency` line. Ignore Streamlit
`ScriptRunContext` / `No runtime` / pandas date-parse `UserWarning` noise.

### Step 2: Runtime-verify the app boots

Run: `python -c "import sys; sys.path.insert(0,'.'); from streamlit.testing.v1 import AppTest; at = AppTest.from_file('app.py', default_timeout=90).run(); assert not at.exception, at.exception; print('app boot: OK')"`

Expected: prints `app boot: OK`, no traceback. (The demo is order-grained, so no new
warnings appear — confirming the change is inert on clean data.)

### Step 3: Add the journal entry

Add a dated entry at the TOP of the Project Journal in `CLAUDE.md` (newest first),
matching the style of existing entries. It should summarize: the last collapse
dimension (customer_id / order_date "keep-first" during the line-item order collapse)
is now disclosed as an operator warning instead of silently discarded; the customer
warning is strongly worded (likely a broken/duplicated Order ID mapping) and the date
warning is soft (often benign partial shipments); keep-first behavior is unchanged and
order-grained files (incl. the Instacart demo) are unaffected; covered by
`test_build_canonical_warns_on_customer_and_date_conflicts` in `tests/test_ingest.py`
and an app-boot smoke. Reference the spec/plan under
`docs/superpowers/{specs,plans}/2026-07-23-per-line-conflict-warnings*`.

### Step 4: Commit

```bash
git add CLAUDE.md
git commit -m "docs: journal per-line conflict warnings"
```

### Step 5: Finish the branch

Use the `superpowers:finishing-a-development-branch` skill to decide merge/PR/push.
Prior pattern for this repo: code review → `--no-ff` merge to `main` → push.

---

## Self-Review

**Spec coverage:**
- Spec §4.1 (detection via per-order nunique on `result.orders`, `dropna=False`) → Task 1 Step 3. ✅
- Spec §4.2 (strong customer warning, soft date warning, appended to the copied `warnings` list) → Task 1 Step 3. ✅
- Spec §4.3 (fires for all grains; silent on order-grained files) → Task 1 test cases (b) uses default/auto grain, (c) order-grained silent; Task 2 Step 2 app-boot confirms demo is unaffected. ✅
- Spec §5 (keep-first unchanged) → Task 1 test asserts `kept["o1"] == "c1"`. ✅
- Spec §6 (three test cases + regression sweep + boot) → Task 1 + Task 2. ✅
- Spec §7 (files: builder.py, test_ingest.py, CLAUDE.md) → Tasks 1-2. ✅

**Placeholder scan:** No TBD/TODO; every code step shows complete code; the journal
step describes exact content to write. ✅

**Type/name consistency:** `cust_conflicts` / `date_conflicts` are defined and used
in the same task; warning substrings asserted in the test (`"more than one customer"`,
`"order id"`, `"different dates"`) exactly match the strings appended in the
implementation. `build_canonical` returns the existing dict shape with the same
`warnings` key the test reads. ✅

**Ordering note:** The two counts are computed from `result.orders` (pre-collapse) so
they are independent of the amount `grain` branch; the warnings are appended after the
collapse, before `build_feature_matrix`, and do not affect the returned `orders`.
