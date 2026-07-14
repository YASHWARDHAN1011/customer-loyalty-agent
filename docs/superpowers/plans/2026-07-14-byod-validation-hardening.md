# BYOD Validation Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two silent-wrong-number bugs in the ingestion firewall — US-biased
date parsing and line-item revenue collapse — and prove the fix with a realistic
Australian e-commerce fixture.

**Architecture:** Two surgical changes to pure modules. `validator.py` gains
evidence-based day-first inference (replacing a bare `pd.to_datetime`);
`builder.py` replaces `drop_duplicates("order_id")` with a per-order amount
collapse (sum differing line prices, keep identical repeated totals once). A new
fixture in `tests/test_ingest.py` drives both end-to-end through the FeatureMatrix.

**Tech Stack:** Python, pandas. Tests are **standalone scripts** (no pytest): a
`check(name, cond)` helper prints `PASS`/`FAIL` and `sys.exit(1)` on first failure.
Run the whole file with the outer venv.

**Test runner (used in every task):**
```
../venv/Scripts/python.exe tests/test_ingest.py
```
Expected on success: a stream of `PASS ...` lines ending in `N checks passed.` and
exit code 0. On failure: a `FAIL <name>` line and exit code 1.

**Spec:** `docs/superpowers/specs/2026-07-14-byod-validation-hardening-design.md`

---

## Task 1: Evidence-based date-locale inference (validator)

**Files:**
- Modify: `src/data/ingest/validator.py` (add `_infer_dayfirst`; change the date
  block in `validate`, currently around lines 76–84; update module docstring)
- Test: `tests/test_ingest.py` (add `test_validate_au_dates`, register in `main()`)

- [ ] **Step 1: Write the failing tests**

Add this function to `tests/test_ingest.py` (place it after the existing
`test_validate_bad_dates` function):

```python
def test_validate_au_dates():
    from src.data.ingest.validator import validate
    import pandas as pd
    m = {"customer_id": "cust", "order_id": "ord",
         "order_date": "when", "order_amount": "total"}

    # Decisive: 13 > 12 in first slot => day-first for the whole column.
    df = pd.DataFrame({"cust": ["c1", "c1"], "ord": ["o1", "o2"],
                       "when": ["13/06/2025", "03/04/2025"], "total": ["100", "200"]})
    r = validate(df, m)
    d = dict(zip(r.orders["order_id"], r.orders["order_date"]))
    check("AU 13/06 -> 13 June", d["o1"] == pd.Timestamp("2025-06-13"))
    check("AU 03/04 -> 3 April (day-first)", d["o2"] == pd.Timestamp("2025-04-03"))
    check("decisive day-first: no ambiguity warning",
          not any("ambiguous" in w.lower() for w in r.warnings))

    # Decisive the other way: 13 in the SECOND slot => month-first.
    df2 = pd.DataFrame({"cust": ["c1"], "ord": ["o1"],
                        "when": ["04/13/2025"], "total": ["50"]})
    r2 = validate(df2, m)
    check("US 04/13 -> 13 April (month-first)",
          r2.orders["order_date"].iloc[0] == pd.Timestamp("2025-04-13"))

    # Truly ambiguous (all components <= 12): default day-first + warn.
    df3 = pd.DataFrame({"cust": ["c1"], "ord": ["o1"],
                        "when": ["05/06/2025"], "total": ["50"]})
    r3 = validate(df3, m)
    check("ambiguous defaults to day-first (5 June)",
          r3.orders["order_date"].iloc[0] == pd.Timestamp("2025-06-05"))
    check("ambiguous emits a warning",
          any("ambiguous" in w.lower() for w in r3.warnings))

    # ISO dates stay unambiguous and warning-free.
    df4 = pd.DataFrame({"cust": ["c1"], "ord": ["o1"],
                        "when": ["2025-06-13"], "total": ["50"]})
    r4 = validate(df4, m)
    check("ISO date parses",
          r4.orders["order_date"].iloc[0] == pd.Timestamp("2025-06-13"))
    check("ISO date: no ambiguity warning",
          not any("ambiguous" in w.lower() for w in r4.warnings))
```

Register it in `main()` — add this line right after the existing
`test_validate_bad_dates()` call:

```python
    test_validate_au_dates()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../venv/Scripts/python.exe tests/test_ingest.py`
Expected: FAIL at `AU 03/04 -> 3 April (day-first)` (current code parses it as
March 4 because `pd.to_datetime` defaults to month-first), exit code 1.

- [ ] **Step 3: Add the inference helper**

Add near the top of `src/data/ingest/validator.py`, after the imports and before
`ValidationResult`:

```python
import re

# Numeric D/M/Y or M/D/Y with 1-2 digit day and month (ISO YYYY-MM-DD and
# text-month formats are unambiguous and handled by pandas directly).
_AMBIG_DATE = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-]\d{2,4}\s*$")


def _infer_dayfirst(raw: pd.Series):
    """Decide day-first vs month-first from evidence in the column.

    Returns (dayfirst: bool, ambiguous: bool). `ambiguous` is True only when
    D/M values are present but none disambiguate (every day and month <= 12),
    in which case we default to day-first and the caller warns.
    """
    saw_ambig = first_gt12 = second_gt12 = False
    for v in raw.astype(str):
        mtch = _AMBIG_DATE.match(v)
        if not mtch:
            continue
        saw_ambig = True
        a, b = int(mtch.group(1)), int(mtch.group(2))
        if a > 12:
            first_gt12 = True
        if b > 12:
            second_gt12 = True
    if first_gt12:
        return True, False
    if second_gt12:
        return False, False
    return True, saw_ambig
```

- [ ] **Step 4: Use the helper in `validate`**

In `src/data/ingest/validator.py`, replace the current date block:

```python
    raw_dates = df[mapping["order_date"]]
    dates = pd.to_datetime(raw_dates, errors="coerce")
```

with:

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

Then update the module docstring (lines 1–10): change the sentence about dates to
note that day-first vs month-first is inferred from the column's evidence and that
a warning is emitted when the format is genuinely ambiguous.

- [ ] **Step 5: Run tests to verify they pass**

Run: `../venv/Scripts/python.exe tests/test_ingest.py`
Expected: all `PASS`, including the five new `test_validate_au_dates` checks;
exit code 0.

- [ ] **Step 6: Commit**

```bash
git add src/data/ingest/validator.py tests/test_ingest.py
git commit -m "fix(ingest): infer date locale from data (day-first for AU), warn when ambiguous"
```

---

## Task 2: Order-grain amount collapse (builder)

**Files:**
- Modify: `src/data/ingest/builder.py` (add `_collapse_amount`; replace the
  detect-warn-then-`drop_duplicates` block, lines ~28–42; update module docstring)
- Test: `tests/test_ingest.py` (add `test_build_canonical_sums_line_items`;
  rewrite the existing `test_build_canonical_line_grained_warns` expectation)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ingest.py` (after `test_build_canonical_dedups_orders`):

```python
def test_build_canonical_sums_line_items():
    from src.data.ingest.builder import build_canonical
    import pandas as pd
    # One order, three line rows with DISTINCT line prices -> true total 100.
    df = pd.DataFrame({
        "cust": ["c1", "c1", "c1"],
        "ord":  ["o1", "o1", "o1"],
        "when": ["2025-01-01", "2025-01-01", "2025-01-01"],
        "line": ["30", "45", "25"],
        "sku":  ["A", "B", "C"],
    })
    m = {"customer_id": "cust", "order_id": "ord", "order_date": "when",
         "order_amount": "line", "product": "sku"}
    res = build_canonical(df, m)
    check("line-item build ok", res["ok"] is True)
    check("one order after collapse", len(res["orders"]) == 1)
    check("line prices summed to order total (100)",
          float(res["orders"]["order_amount"].iloc[0]) == 100.0)
    check("summed-lines warning present",
          any("summed" in w.lower() for w in res["warnings"]))

    # Repeated per-order TOTAL on every line -> must be kept once, NOT summed.
    df2 = pd.DataFrame({
        "cust": ["c1", "c1"], "ord": ["o1", "o1"],
        "when": ["2025-01-01", "2025-01-01"],
        "amt":  ["100", "100"], "sku": ["A", "B"],
    })
    m2 = {"customer_id": "cust", "order_id": "ord", "order_date": "when",
          "order_amount": "amt", "product": "sku"}
    res2 = build_canonical(df2, m2)
    check("repeated total kept once (100, not 200)",
          float(res2["orders"]["order_amount"].iloc[0]) == 100.0)
    check("repeated total: no summed warning",
          not any("summed" in w.lower() for w in res2["warnings"]))
```

Register in `main()` after the existing `test_build_canonical_dedups_orders()`:

```python
    test_build_canonical_sums_line_items()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `../venv/Scripts/python.exe tests/test_ingest.py`
Expected: FAIL at `line prices summed to order total (100)` — current builder keeps
the first amount (30), exit code 1.

- [ ] **Step 3: Implement the collapse**

In `src/data/ingest/builder.py`, add above `build_canonical`:

```python
def _collapse_amount(s):
    """Per order: identical amounts are a repeated order total (keep one);
    differing amounts are per-line prices (sum to the order total)."""
    return s.iloc[0] if s.nunique(dropna=False) == 1 else s.sum()
```

Replace the current block (the `warnings = list(...)` through the
`orders = result.orders.drop_duplicates("order_id").reset_index(drop=True)` line):

```python
    warnings = list(result.warnings)

    amt_per_order = result.orders.groupby("order_id")["order_amount"].nunique()
    summed = int((amt_per_order > 1).sum())
    if summed:
        warnings.append(
            f"{summed} order(s) spanned multiple line amounts and were summed to "
            "an order total. Verify the amount column mapping.")

    orders = (result.orders
              .groupby("order_id", sort=False)
              .agg(customer_id=("customer_id", "first"),
                   order_date=("order_date", "first"),
                   order_amount=("order_amount", _collapse_amount))
              .reset_index())
    orders = orders[["customer_id", "order_id", "order_date", "order_amount"]]
```

Then update the module docstring (lines ~9–13): replace the "amount is read as an
order TOTAL repeated across those rows (kept once via drop_duplicates), NOT summed
per line" assumption with the new rule — identical per-order amounts are kept once,
differing line amounts are summed to the order total.

- [ ] **Step 4: Update the now-outdated existing test**

The existing `test_build_canonical_line_grained_warns` asserts the OLD behavior
(first amount kept, "may be off" warning). Find it in `tests/test_ingest.py` and
replace its body so it asserts the NEW behavior: differing line amounts are summed
and the warning contains "summed". Keep the same function name and its call in
`main()`. Example replacement body (adapt column/amount names to whatever the
existing fixture uses):

```python
def test_build_canonical_line_grained_warns():
    from src.data.ingest.builder import build_canonical
    import pandas as pd
    df = pd.DataFrame({
        "cust": ["c1", "c1"], "ord": ["o1", "o1"],
        "when": ["2025-01-01", "2025-01-01"], "amt": ["10", "15"],
    })
    m = {"customer_id": "cust", "order_id": "ord",
         "order_date": "when", "order_amount": "amt"}
    res = build_canonical(df, m)
    check("line-grained summed to 25", float(res["orders"]["order_amount"].iloc[0]) == 25.0)
    check("line-grained warns about summing",
          any("summed" in w.lower() for w in res["warnings"]))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `../venv/Scripts/python.exe tests/test_ingest.py`
Expected: all `PASS` (new sum test, rewritten line-grained test, and the untouched
`test_build_canonical_dedups_orders` which uses identical amounts and so is
unaffected); exit code 0.

- [ ] **Step 6: Commit**

```bash
git add src/data/ingest/builder.py tests/test_ingest.py
git commit -m "fix(ingest): sum per-line amounts into order totals (was under-counting revenue)"
```

---

## Task 3: Realistic AU e-commerce fixture (end-to-end)

**Files:**
- Test: `tests/test_ingest.py` (add `test_au_shopify_export_end_to_end`, register
  in `main()`)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_ingest.py` (after `test_build_canonical_sums_line_items`):

```python
def test_au_shopify_export_end_to_end():
    """A messy Shopify/WooCommerce-style AU export through the full pipeline:
    DD/MM/YYYY dates, $ + thousands commas, a parenthesised refund, and a
    multi-line order. Every number below is hand-computed."""
    from src.data.ingest.builder import build_canonical
    import pandas as pd
    df = pd.DataFrame({
        "Email":      ["ann@x.com", "ann@x.com", "ann@x.com", "bob@x.com", "bob@x.com"],
        "Name":       ["#1001", "#1001", "#1002", "#2001", "#2002"],
        "Created at": ["13/06/2025", "13/06/2025", "20/06/2025", "01/06/2025", "15/06/2025"],
        "Total":      ["$1,200.00", "$300.00", "$50.00", "$80.00", "($20.00)"],
        "Lineitem":   ["Sofa", "Cushion", "Lamp", "Mug", "Return"],
    })
    m = {"customer_id": "Email", "order_id": "Name", "order_date": "Created at",
         "order_amount": "Total", "product": "Lineitem"}
    res = build_canonical(df, m)
    check("AU export builds ok", res["ok"] is True)

    orders = res["orders"].set_index("order_id")
    # Order #1001 = two lines (1200 + 300) summed = 1500.
    check("multi-line order #1001 summed to 1500",
          float(orders.loc["#1001", "order_amount"]) == 1500.0)
    # Date read day-first: 13/06/2025 -> 13 June (13 > 12 forces day-first).
    check("AU date #1001 = 13 June 2025",
          orders.loc["#1001", "order_date"] == pd.Timestamp("2025-06-13"))
    # Refund ($20) clipped to 0.
    check("refund order #2002 clipped to 0",
          float(orders.loc["#2002", "order_amount"]) == 0.0)

    # FeatureMatrix RFM for Ann: 2 orders (#1001, #1002), monetary 1500+50 = 1550.
    fm = res["matrix"]
    feats = fm.frame.set_index("customer_id")
    check("Ann frequency = 2 orders", int(feats.loc["ann@x.com", "frequency"]) == 2)
    check("Ann monetary = 1550", float(feats.loc["ann@x.com", "monetary"]) == 1550.0)
```

Register in `main()` after `test_build_canonical_sums_line_items()`:

```python
    test_au_shopify_export_end_to_end()
```

- [ ] **Step 2: Run the test**

Run: `../venv/Scripts/python.exe tests/test_ingest.py`
Expected: if Task 1 and Task 2 are complete, this should PASS immediately (it is an
integration check over the already-fixed pipeline). If it FAILS on the
`frequency` / `monetary` names, inspect the actual columns and fix the assertion:

```bash
../venv/Scripts/python.exe -c "from src.data.canonical import build_core_features; import inspect; print(inspect.getsource(build_core_features))" 2>&1 | head -40
```

Adjust the `feats.loc[...]` column names in the test to the real feature-matrix
column names (e.g. `frequency`/`monetary` may be named differently) and the
hand-computed values if the definitions differ. Do NOT change the pipeline to fit
the test — the pipeline is correct; the assertion must match its real output.

- [ ] **Step 3: Commit**

```bash
git add tests/test_ingest.py
git commit -m "test(ingest): realistic AU Shopify export drives the full pipeline end-to-end"
```

---

## Task 4: Full regression sweep + journal

**Files:**
- Modify: `CLAUDE.md` (add a dated Project Journal entry at the top)

- [ ] **Step 1: Run the ingestion-adjacent suites**

Run each and confirm exit code 0 (`N checks passed.` / `ALL PASSED`):

```
../venv/Scripts/python.exe tests/test_ingest.py
../venv/Scripts/python.exe tests/test_canonical.py
../venv/Scripts/python.exe tests/test_mapping_persist.py
../venv/Scripts/python.exe tests/test_upload_flow.py
```

Expected: all pass. If `test_upload_flow.py` or `test_canonical.py` regress,
investigate — the builder now returns summed order amounts; any fixture there that
relied on first-amount dedup with *differing* amounts must be reconciled (identical
amounts are unaffected).

- [ ] **Step 2: Confirm the app still boots (no import breakage)**

Run:
```
../venv/Scripts/python.exe -c "import ast; ast.parse(open('src/data/ingest/validator.py').read()); ast.parse(open('src/data/ingest/builder.py').read()); print('syntax ok')"
```
Expected: `syntax ok`.

- [ ] **Step 3: Add the journal entry**

Add a new dated entry at the TOP of the Project Journal section in `CLAUDE.md`
(newest first), summarizing: the two fixed correctness bugs (date locale, line-item
revenue), the evidence-based approach (infer + warn, never blind-guess), and the AU
fixture. Follow the existing entry style.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: journal BYOD validation hardening (date locale + line-item revenue)"
```

---

## Self-review notes

- **Spec coverage:** date inference → Task 1; order-grain collapse → Task 2; AU
  fixture + RFM assertions + both regression checks (no-double-count in Task 2,
  ambiguity-warning in Task 1) → Tasks 1–3. Docstring updates → Tasks 1 & 2.
- **Ambiguous default = day-first:** asserted in Task 1 (`05/06/2025` → 5 June +
  warning), matching the spec.
- **Risk flagged in Task 3/4:** feature-matrix column names (`frequency`/
  `monetary`) are assumed; Task 3 Step 2 gives the exact command to verify and
  adjust rather than guess.
