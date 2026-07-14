# Confirm-Screen Locale & Grain Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the operator see and override the inferred date locale and order grain on the upload confirm screen, before any analysis computes.

**Architecture:** Thread optional override params (`dayfirst`, `grain`) through the pure ingestion backend (`validate` → `build_canonical` → `apply_mapping`), defaulting to `None` = today's auto behavior. The confirm screen computes detection live via pure helpers (`_infer_dayfirst`, new `detect_grain`) and passes the operator's radio choice down. Detection helpers are reused for both display and the auto path so they can't drift.

**Tech Stack:** Python, pandas, Streamlit. Tests are **standalone scripts** (no pytest). `tests/test_ingest.py` uses a `check(name, cond)` helper (prints PASS/FAIL, `sys.exit(1)` on failure). `tests/test_upload_flow.py` uses plain `assert` and drives Streamlit UI via `streamlit.testing.v1.AppTest`.

**Test runners:**
```
../venv/Scripts/python.exe tests/test_ingest.py
../venv/Scripts/python.exe tests/test_upload_flow.py
```
Exit 0 on success. Ignore harmless Streamlit "No runtime found" stderr warnings.

**Spec:** `docs/superpowers/specs/2026-07-14-confirm-screen-locale-grain-design.md`

**Note on the UI display (refinement of the spec):** the spec shows the detected value *inside* the Auto radio label. The plan instead uses **stable radio options** (`Auto` / explicit choices) plus a separate `st.caption("Detected: …")`. Identical semantics, but it avoids a Streamlit bug where a keyed radio throws when its persisted value (an option string) no longer matches the options after the detected label changes.

---

## Task 1: `validate` accepts a `dayfirst` override

**Files:**
- Modify: `src/data/ingest/validator.py` (the date block inside `validate`; add a `dayfirst=None` param)
- Test: `tests/test_ingest.py` (add `test_validate_dayfirst_override`, register in `main()`)

- [ ] **Step 1: Write the failing test.** Add to `tests/test_ingest.py` after `test_validate_au_dates`:

```python
def test_validate_dayfirst_override():
    from src.data.ingest.validator import validate
    import pandas as pd
    m = {"customer_id": "c", "order_id": "o", "order_date": "when", "order_amount": "t"}
    # All components <= 12 -> auto would be ambiguous; force each locale explicitly.
    df = pd.DataFrame({"c": ["c1", "c1"], "o": ["o1", "o2"],
                       "when": ["06/07/2025", "08/09/2025"], "t": ["10", "20"]})
    r_us = validate(df, m, dayfirst=False)  # month-first: 06/07/2025 = MM=06(June) DD=07 -> 2025-06-07
    check("force month-first: 06/07 -> 7 June",
          r_us.orders.set_index("order_id").loc["o1", "order_date"] == pd.Timestamp("2025-06-07"))
    check("forced choice suppresses ambiguity warning",
          not any("ambiguous" in w.lower() for w in r_us.warnings))
    r_au = validate(df, m, dayfirst=True)   # day-first: DD=06, MM=07 -> 6 July
    check("force day-first: 06/07 -> 6 July",
          r_au.orders.set_index("order_id").loc["o1", "order_date"] == pd.Timestamp("2025-07-06"))
```

Register in `main()` after `test_validate_au_dates()`: add `test_validate_dayfirst_override()`.

- [ ] **Step 2: Run to verify it fails.** `../venv/Scripts/python.exe tests/test_ingest.py` — expected FAIL: `validate() got an unexpected keyword argument 'dayfirst'`.

- [ ] **Step 3: Add the param.** In `src/data/ingest/validator.py`, change the signature:

```python
def validate(df: pd.DataFrame, mapping: dict, dayfirst=None) -> ValidationResult:
```

Replace the current date-inference block:

```python
    raw_dates = df[mapping["order_date"]]
    dayfirst, ambiguous = _infer_dayfirst(raw_dates)
    dates = pd.to_datetime(raw_dates, errors="coerce", dayfirst=dayfirst)
    if ambiguous:
        warnings.append(
            f"Dates in column '{mapping['order_date']}' use an ambiguous "
            f"D/M/Y format (all values <= 12) and were read as day-first "
            f"(DD/MM/YYYY). Verify the date column if your data is US-style "
            f"(MM/DD/YYYY).")
```

with (note the local is renamed to `resolved` so it doesn't shadow the new param):

```python
    raw_dates = df[mapping["order_date"]]
    if dayfirst is None:
        resolved, ambiguous = _infer_dayfirst(raw_dates)
    else:
        resolved, ambiguous = dayfirst, False
    dates = pd.to_datetime(raw_dates, errors="coerce", dayfirst=resolved)
    if ambiguous:
        warnings.append(
            f"Dates in column '{mapping['order_date']}' use an ambiguous "
            f"D/M/Y format (all values <= 12) and were read as day-first "
            f"(DD/MM/YYYY). Verify the date column if your data is US-style "
            f"(MM/DD/YYYY).")
```

Update the module docstring's date sentence to note the locale can be forced via `dayfirst` and is otherwise inferred.

- [ ] **Step 4: Run to verify it passes.** `../venv/Scripts/python.exe tests/test_ingest.py` — expected all PASS.

- [ ] **Step 5: Commit.**
```bash
git add src/data/ingest/validator.py tests/test_ingest.py
git commit -m "feat(ingest): validate() accepts an explicit dayfirst locale override"
```

---

## Task 2: `build_canonical` grain override + `detect_grain`

**Files:**
- Modify: `src/data/ingest/builder.py` (add `import pandas as pd`; add `detect_grain`; add `dayfirst`/`grain` params to `build_canonical`; branch the collapse on `grain`)
- Test: `tests/test_ingest.py` (add `test_build_canonical_grain_override` + `test_detect_grain`, register both)

- [ ] **Step 1: Write the failing tests.** Add to `tests/test_ingest.py` after `test_build_canonical_sums_line_items`:

```python
def test_build_canonical_grain_override():
    from src.data.ingest.builder import build_canonical
    import pandas as pd
    # line_item: two IDENTICAL lines @25 -> auto keeps 25, but forced line_item sums to 50.
    df = pd.DataFrame({"c": ["c1", "c1"], "o": ["o1", "o1"],
                       "when": ["2025-01-01", "2025-01-01"], "amt": ["25", "25"], "sku": ["A", "B"]})
    m = {"customer_id": "c", "order_id": "o", "order_date": "when",
         "order_amount": "amt", "product": "sku"}
    res = build_canonical(df, m, grain="line_item")
    check("line_item sums identical lines to 50",
          float(res["orders"]["order_amount"].iloc[0]) == 50.0)
    check("line_item warns", any("line-item" in w.lower() for w in res["warnings"]))

    # order_level: differing amounts -> keep first (10), warn about discarding.
    df2 = pd.DataFrame({"c": ["c1", "c1"], "o": ["o1", "o1"],
                        "when": ["2025-01-01", "2025-01-01"], "amt": ["10", "15"]})
    m2 = {"customer_id": "c", "order_id": "o", "order_date": "when", "order_amount": "amt"}
    res2 = build_canonical(df2, m2, grain="order_level")
    check("order_level keeps first amount (10)",
          float(res2["orders"]["order_amount"].iloc[0]) == 10.0)
    check("order_level warns first-was-kept",
          any("first was kept" in w.lower() for w in res2["warnings"]))


def test_detect_grain():
    from src.data.ingest.builder import detect_grain
    import pandas as pd
    m = {"customer_id": "c", "order_id": "o", "order_date": "when", "order_amount": "amt"}
    diff = pd.DataFrame({"c": ["c1", "c1"], "o": ["o1", "o1"],
                         "when": ["x", "x"], "amt": ["30", "45"]})
    check("detect line_item on differing amounts", detect_grain(diff, m) == "line_item")
    same = pd.DataFrame({"c": ["c1", "c1"], "o": ["o1", "o1"],
                         "when": ["x", "x"], "amt": ["30", "30"]})
    check("detect order_level on identical amounts", detect_grain(same, m) == "order_level")
    check("detect order_level when amount unmapped",
          detect_grain(same, {"customer_id": "c", "order_id": "o", "order_date": "when"}) == "order_level")
```

Register in `main()` after `test_build_canonical_sums_line_items()`: add `test_build_canonical_grain_override()` and `test_detect_grain()`.

- [ ] **Step 2: Run to verify it fails.** `../venv/Scripts/python.exe tests/test_ingest.py` — expected FAIL: `build_canonical() got an unexpected keyword argument 'grain'` (or `detect_grain` not found).

- [ ] **Step 3: Implement.** In `src/data/ingest/builder.py`, add `import pandas as pd` under the existing import. Add above `build_canonical`:

```python
def detect_grain(df, mapping):
    """Pure: 'line_item' if any order id shows more than one distinct amount,
    else 'order_level'. Safe default 'order_level' when amount/order_id are
    unmapped/absent or on any coercion error (never raises)."""
    amt_col = mapping.get("order_amount")
    oid_col = mapping.get("order_id")
    if not amt_col or not oid_col or amt_col not in df.columns or oid_col not in df.columns:
        return "order_level"
    try:
        from src.data.ingest.validator import _clean_amount
        tmp = pd.DataFrame({"oid": df[oid_col].astype(str),
                            "amt": _clean_amount(df[amt_col])})
        per = tmp.groupby("oid")["amt"].nunique(dropna=True)
        return "line_item" if bool((per > 1).any()) else "order_level"
    except Exception:
        return "order_level"
```

Change the signature:

```python
def build_canonical(df, mapping, dayfirst=None, grain=None) -> dict:
```

Change the validate call from `result = validate(df, mapping)` to:

```python
    result = validate(df, mapping, dayfirst=dayfirst)
```

Replace the collapse block (from `warnings = list(result.warnings)` through the line that reorders `orders` columns) with:

```python
    warnings = list(result.warnings)

    rows_per_order = result.orders.groupby("order_id").size()
    amt_nunique = result.orders.groupby("order_id")["order_amount"].nunique()

    if grain == "line_item":
        amount_agg = "sum"
        n = int((rows_per_order > 1).sum())
        if n:
            warnings.append(
                f"{n} order(s) had their line amounts summed to an order total "
                "(line-item file).")
    elif grain == "order_level":
        amount_agg = "first"
        n = int((amt_nunique > 1).sum())
        if n:
            warnings.append(
                f"{n} order(s) had multiple differing amounts; the first was kept "
                "(order-level file). If this is a line-item export, choose "
                "'Line-item' instead.")
    else:
        amount_agg = _collapse_amount
        n = int((amt_nunique > 1).sum())
        if n:
            warnings.append(
                f"{n} order(s) spanned multiple line amounts and were summed to "
                "an order total. Verify the amount column mapping.")

    orders = (result.orders
              .groupby("order_id", sort=False)
              .agg(customer_id=("customer_id", "first"),
                   order_date=("order_date", "first"),
                   order_amount=("order_amount", amount_agg))
              .reset_index())
    orders = orders[["customer_id", "order_id", "order_date", "order_amount"]]
```

Update the module docstring to note that grain (`None` auto / `"line_item"` always-sum / `"order_level"` keep-first) can be forced.

- [ ] **Step 4: Run to verify it passes.** `../venv/Scripts/python.exe tests/test_ingest.py` — expected all PASS (new grain + detect_grain checks, and the existing `test_build_canonical_sums_line_items` / `test_build_canonical_line_grained_warns` / `test_build_canonical_dedups_orders` still pass because `grain=None` keeps the auto rule).

- [ ] **Step 5: Commit.**
```bash
git add src/data/ingest/builder.py tests/test_ingest.py
git commit -m "feat(ingest): build_canonical grain override + pure detect_grain"
```

---

## Task 3: `apply_mapping` threads the overrides

**Files:**
- Modify: `src/ui/upload.py` (`apply_mapping` signature + call)
- Test: `tests/test_upload_flow.py` (add `test_apply_mapping_honors_overrides`, register in `__main__`)

- [ ] **Step 1: Write the failing test.** Add to `tests/test_upload_flow.py` after `test_apply_mapping_failure_returns_errors`:

```python
def test_apply_mapping_honors_overrides():
    csv = "c,o,when,amt,sku\nc1,o1,03/04/2025,25,A\nc1,o1,03/04/2025,25,B\n"
    df = pd.read_csv(io.StringIO(csv), dtype=str)
    m = {"customer_id": "c", "order_id": "o", "order_date": "when",
         "order_amount": "amt", "product": "sku"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        # month-first => 03/04 is March 4; line_item => identical 25+25 summed to 50.
        res = apply_mapping(df, m, store_path=store, dayfirst=False, grain="line_item")
    assert res["ok"] is True
    row = res["orders"].iloc[0]
    assert float(row["order_amount"]) == 50.0
    assert row["order_date"] == pd.Timestamp("2025-03-04")
```

Register in `__main__` (add before the final `print(...)`): `test_apply_mapping_honors_overrides()`.

- [ ] **Step 2: Run to verify it fails.** `../venv/Scripts/python.exe tests/test_upload_flow.py` — expected FAIL: `apply_mapping() got an unexpected keyword argument 'dayfirst'`.

- [ ] **Step 3: Implement.** In `src/ui/upload.py`, change `apply_mapping`:

```python
def apply_mapping(df, mapping, store_path=_STORE, dayfirst=None, grain=None):
    """Validate + build canonical for a confirmed mapping.

    `dayfirst`/`grain` are optional operator overrides (None = auto). On success,
    persists the mapping recipe for next time. Returns the builder result dict
    {ok, errors, warnings, orders, order_items, matrix}.
    """
    result = build_canonical(df, mapping, dayfirst=dayfirst, grain=grain)
    if result["ok"]:
        save_mapping(list(df.columns), mapping, path=store_path)
    return result
```

- [ ] **Step 4: Run to verify it passes.** `../venv/Scripts/python.exe tests/test_upload_flow.py` — expected `test_upload_flow: OK`, exit 0.

- [ ] **Step 5: Commit.**
```bash
git add src/ui/upload.py tests/test_upload_flow.py
git commit -m "feat(upload): apply_mapping threads dayfirst/grain overrides to build"
```

---

## Task 4: Confirm-screen locale & grain controls

**Files:**
- Modify: `src/ui/upload.py` (`_UPLOAD_KEYS`; `_build_and_activate` signature; `render_confirm_gate` controls + translation)
- Test: `tests/test_upload_flow.py` (add `test_confirm_gate_shows_locale_and_grain_radios`, register in `__main__`)

- [ ] **Step 1: Write the failing test.** Add to `tests/test_upload_flow.py` after `test_apply_mapping_honors_overrides`:

```python
def test_confirm_gate_shows_locale_and_grain_radios():
    from streamlit.testing.v1 import AppTest
    script = (
        "import os, sys\n"
        "sys.path.insert(0, os.getcwd())\n"
        "import pandas as pd, streamlit as st\n"
        "from src.ui.upload import render_confirm_gate\n"
        "st.session_state['upload_stage'] = 'confirm'\n"
        "st.session_state['upload_df'] = pd.DataFrame({'c':['c1','c1'],'o':['o1','o1'],"
        "'when':['03/04/2025','03/04/2025'],'amt':['30','45'],'sku':['A','B']})\n"
        "st.session_state['upload_mapping'] = {'customer_id':'c','order_id':'o',"
        "'order_date':'when','order_amount':'amt','product':'sku'}\n"
        "st.session_state['upload_filename'] = 'f.csv'\n"
        "render_confirm_gate(lambda *a, **k: None)\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, f"confirm gate raised: {at.exception}"
    labels = [r.label for r in at.radio]
    assert "Date format" in labels, labels
    assert "Order grain" in labels, labels
```

Register in `__main__`: add `test_confirm_gate_shows_locale_and_grain_radios()`.

- [ ] **Step 2: Run to verify it fails.** `../venv/Scripts/python.exe tests/test_upload_flow.py` — expected FAIL: `assert "Date format" in labels` (no such radio yet).

- [ ] **Step 3: Add the two override keys to cleanup.** In `src/ui/upload.py`, extend `_UPLOAD_KEYS`:

```python
_UPLOAD_KEYS = ("upload_stage", "upload_df", "upload_filename", "upload_mapping",
                "upload_profile", "upload_saved", "upload_errors", "upload_warnings",
                "date_locale_choice", "order_grain_choice")
```

- [ ] **Step 4: Render the controls + translate on Confirm.** In `render_confirm_gate`, insert the controls after the preview block (right after the `if picked: st.dataframe(...)` lines) and before the `c1, c2 = st.columns(2)` line:

```python
    # --- Locale & grain: show what build will do, let the operator override. ---
    from src.data.ingest.validator import _infer_dayfirst
    from src.data.ingest.builder import detect_grain

    date_col = chosen.get("order_date")
    if date_col and date_col in df.columns:
        inferred_df, ambiguous = _infer_dayfirst(df[date_col])
    else:
        inferred_df, ambiguous = True, False
    if ambiguous:
        detected_locale = "ambiguous — assuming Day-first (DD/MM/YYYY)"
    elif inferred_df:
        detected_locale = "Day-first (DD/MM/YYYY)"
    else:
        detected_locale = "Month-first (MM/DD/YYYY)"
    st.radio("Date format",
             ["Auto", "Day-first (DD/MM/YYYY)", "Month-first (MM/DD/YYYY)"],
             key="date_locale_choice")
    st.caption(f"Detected: {detected_locale}")

    detected_grain = detect_grain(df, chosen)
    grain_label = ("line-item — lines will be summed per order"
                   if detected_grain == "line_item" else "order-level (one row per order)")
    st.radio("Order grain",
             ["Auto", "Line-item — sum lines per order", "Order-level — one row per order"],
             key="order_grain_choice")
    st.caption(f"Detected: {grain_label}")
```

Then change the Confirm button block. Replace:

```python
    c1, c2 = st.columns(2)
    if c1.button("✅ Confirm & analyze", type="primary", use_container_width=True):
        _build_and_activate(fname, df, chosen, run_analysis)
        st.rerun()
```

with:

```python
    def _dayfirst_override():
        c = st.session_state.get("date_locale_choice", "Auto")
        if c.startswith("Day-first"):
            return True
        if c.startswith("Month-first"):
            return False
        return None

    def _grain_override():
        c = st.session_state.get("order_grain_choice", "Auto")
        if c.startswith("Line-item"):
            return "line_item"
        if c.startswith("Order-level"):
            return "order_level"
        return None

    c1, c2 = st.columns(2)
    if c1.button("✅ Confirm & analyze", type="primary", use_container_width=True):
        _build_and_activate(fname, df, chosen, run_analysis,
                            dayfirst=_dayfirst_override(), grain=_grain_override())
        st.rerun()
```

- [ ] **Step 5: Thread overrides through `_build_and_activate`.** Change its signature and the `apply_mapping` call:

```python
def _build_and_activate(filename, df, mapping, run_analysis, *, dayfirst=None, grain=None):
    """Run apply_mapping; on success swap the active dataset + analyze."""
    result = apply_mapping(df, mapping, dayfirst=dayfirst, grain=grain)
```

(The rest of the function body is unchanged. The saved-recipe fast-path caller in `render_upload_section` calls `_build_and_activate(up.name, df, prep["mapping"], run_analysis)` with no overrides — that still works via the defaults.)

- [ ] **Step 6: Run to verify it passes.** `../venv/Scripts/python.exe tests/test_upload_flow.py` — expected `test_upload_flow: OK`, exit 0.

- [ ] **Step 7: Commit.**
```bash
git add src/ui/upload.py tests/test_upload_flow.py
git commit -m "feat(upload): confirm-screen date-locale & order-grain override controls"
```

---

## Task 5: Regression sweep + journal

**Files:**
- Modify: `CLAUDE.md` (dated Project Journal entry at the top)

- [ ] **Step 1: Run the affected suites.** Each must exit 0:

```
../venv/Scripts/python.exe tests/test_ingest.py
../venv/Scripts/python.exe tests/test_upload_flow.py
../venv/Scripts/python.exe tests/test_canonical.py
../venv/Scripts/python.exe tests/test_mapping_persist.py
../venv/Scripts/python.exe tests/test_dataset_swap.py
```

Expected: all pass. If `test_dataset_swap` or `test_upload_flow` regress, investigate — the only behavioral change to existing paths is the added optional params (default `None` = prior behavior), so any failure is a real bug to fix, not a fixture to relax.

- [ ] **Step 2: Confirm the app still boots.** Run:
```
../venv/Scripts/python.exe -c "from streamlit.testing.v1 import AppTest; at=AppTest.from_file('app.py', default_timeout=60).run(); print('boot exception:', at.exception)"
```
Expected: `boot exception: None`.

- [ ] **Step 3: Add the journal entry.** Add a dated entry at the TOP of the Project Journal in `CLAUDE.md` (newest first), summarizing: operator can now see + override the inferred date locale and order grain on the confirm screen; overrides thread `None`-default through `validate`/`build_canonical`/`apply_mapping`; new pure `detect_grain`; follows the existing entry style.

- [ ] **Step 4: Commit.**
```bash
git add CLAUDE.md
git commit -m "docs: journal confirm-screen locale & grain override controls"
```

---

## Self-review notes

- **Spec coverage:** validator override → Task 1; builder grain override + `detect_grain` → Task 2; `apply_mapping` threading → Task 3; confirm-screen controls + translation + `_UPLOAD_KEYS` cleanup + `_build_and_activate` threading → Task 4; regression + journal → Task 5. Error-handling (safe `order_level` default, `_infer_dayfirst` tolerance) is covered by `detect_grain`'s try/except (Task 2) and the `date_col`-absent guard in Task 4.
- **Signature consistency:** `validate(df, mapping, dayfirst=None)`, `build_canonical(df, mapping, dayfirst=None, grain=None)`, `apply_mapping(df, mapping, store_path=_STORE, dayfirst=None, grain=None)`, `_build_and_activate(filename, df, mapping, run_analysis, *, dayfirst=None, grain=None)`, `detect_grain(df, mapping)` — all consistent across tasks. Grain values `"line_item"`/`"order_level"`/`None` used identically everywhere.
- **UI-display refinement vs spec** (stable options + `Detected:` caption) is documented in the header and preserves the spec's semantics.
- **Backward-compat:** every new param defaults to `None`; existing callers and the saved-recipe fast path are unchanged.
```
