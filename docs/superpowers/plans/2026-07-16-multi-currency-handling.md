# Multi-Currency Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Consolidate a client upload that mixes currencies into one reporting currency using operator-supplied flat rates, gated so a silently-wrong mixed sum can never reach the RFM `monetary` figure the chat agent reports.

**Architecture:** A new pure `src/data/ingest/currency.py` (normalize / detect / convert / label) wired into the validator behind `None`-default params (Approach A — amount coercion stays in the validator). The confirm screen detects currencies, collects rates, and blocks Confirm until every non-base rate is set; the validator enforces the same gate authoritatively. The chosen reporting currency rides as metadata (session + mapping recipe) to label money figures. Spec: `docs/superpowers/specs/2026-07-16-multi-currency-handling-design.md`.

**Tech Stack:** Python, pandas, Streamlit (+ `streamlit.testing.v1.AppTest`), pytest.

---

## File Structure

- **Create** `src/data/ingest/currency.py` — normalize a raw currency cell to an ISO code, detect distinct currencies, apply a rate dict, label a code. Pure, no Streamlit/network.
- **Modify** `src/data/ingest/mapper.py` — add optional canonical field `order_currency`.
- **Modify** `src/ui/upload.py` — add `order_currency` display label; thread `reporting_currency`/`rates` through `apply_mapping`/`prepare_upload`/`_build_and_activate`; confirm-gate currency block; session-key hygiene.
- **Modify** `src/data/ingest/validator.py` — `reporting_currency`/`rates` params, `ValidationResult.reporting_currency`, single-currency label, multi-currency gate + conversion.
- **Modify** `src/data/ingest/builder.py` — thread the two params; add `reporting_currency` to the result dict.
- **Modify** `src/data/ingest/mapping_store.py` — persist `extras` (reporting currency + rates); add `load_recipe`.
- **Modify** `src/ui/dataset.py` — accept + store `reporting_currency`.
- **Modify** `src/agent/tools.py` — prefix monetary grounded-query figures with the reporting currency.
- **Modify** `src/export/generator.py` — currency suffix on the CSV monetary column header + a reporting-currency line in the summary report.
- **Tests:** create `tests/test_currency.py`; extend `tests/test_ingest.py`, `tests/test_mapping_persist.py`, `tests/test_upload_flow.py`, `tests/test_export.py`, `tests/test_tools_canonical.py`.

Run tests with the project venv: `..\venv\Scripts\python.exe -m pytest <path> -v` (from the inner `customer-loyalty-agent/` dir). Examples below use `pytest` for brevity.

---

## Task 1: Currency module (`currency.py`)

**Files:**
- Create: `src/data/ingest/currency.py`
- Test: `tests/test_currency.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_currency.py
"""Currency normalize/detect/convert/label contract (no network)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.data.ingest.currency import (
    normalize_currency, detect_currencies, convert_amounts, currency_label, AMBIGUOUS)


def test_normalize_iso_and_symbols():
    assert normalize_currency("usd") == "USD"
    assert normalize_currency("  AUD ") == "AUD"
    assert normalize_currency("A$") == "AUD"
    assert normalize_currency("US$") == "USD"
    assert normalize_currency("NZ$") == "NZD"
    assert normalize_currency("€") == "EUR"
    assert normalize_currency("$") == AMBIGUOUS
    assert normalize_currency("") is None
    assert normalize_currency(None) is None
    assert normalize_currency("wat") is None


def test_detect_currencies_sorted_distinct():
    df = pd.DataFrame({"cur": ["USD", "usd", "AUD", ""], "x": [1, 2, 3, 4]})
    assert detect_currencies(df, {"order_currency": "cur"}) == ["AUD", "USD"]
    assert detect_currencies(df, {}) == []
    assert detect_currencies(df, {"order_currency": "missing"}) == []


def test_convert_amounts_multiplies_by_rate():
    amounts = pd.Series([10.0, 10.0, 5.0])
    codes = pd.Series(["USD", "AUD", "NZD"])
    rates = {"AUD": 1.0, "USD": 1.5, "NZD": 1.1}
    out = convert_amounts(amounts, codes, rates)
    assert list(out.round(2)) == [15.0, 10.0, 5.5]


def test_convert_amounts_missing_rate_is_nan():
    out = convert_amounts(pd.Series([10.0]), pd.Series(["JPY"]), {"AUD": 1.0})
    assert out.isna().all()


def test_currency_label_symbol_or_code():
    assert currency_label("AUD") == "A$"
    assert currency_label("USD") == "US$"
    assert currency_label("XYZ") == "XYZ"
    assert currency_label(None) == ""


if __name__ == "__main__":
    test_normalize_iso_and_symbols()
    test_detect_currencies_sorted_distinct()
    test_convert_amounts_multiplies_by_rate()
    test_convert_amounts_missing_rate_is_nan()
    test_currency_label_symbol_or_code()
    print("test_currency: OK")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_currency.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.data.ingest.currency'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/data/ingest/currency.py
"""
Currency normalization + conversion for the ingest firewall.

Pure module (no Streamlit, no network). Turns a raw currency column into
canonical uppercase ISO codes, detects which currencies a file contains, and
applies operator-supplied FLAT conversion rates to fold every order amount into a
single reporting currency. Rate provenance is the caller's concern — this module
applies whatever {code: rate} dict it is handed (base currency = 1.0).
"""

import pandas as pd

# Unambiguous symbol -> ISO code. A bare "$" is shared by USD/AUD/NZD/CAD and is
# NOT here; it normalizes to the ambiguous sentinel so the UI can surface it.
_SYMBOL_TO_CODE = {
    "US$": "USD", "A$": "AUD", "AU$": "AUD", "NZ$": "NZD",
    "C$": "CAD", "CA$": "CAD", "€": "EUR", "£": "GBP", "¥": "JPY",
}
AMBIGUOUS = "$?"

# Code -> display symbol for labeling. Falls back to the raw code.
_CODE_TO_SYMBOL = {
    "USD": "US$", "AUD": "A$", "NZD": "NZ$", "CAD": "C$",
    "EUR": "€", "GBP": "£", "JPY": "¥",
}


def normalize_currency(raw):
    """One raw cell -> canonical uppercase ISO code, the '$?' sentinel, or None.

    - 3-letter alpha tokens are ISO codes ('usd' -> 'USD').
    - Known multi-char symbols map via _SYMBOL_TO_CODE ('A$' -> 'AUD').
    - A bare '$' is ambiguous -> '$?'.
    - Blank / unrecognized -> None.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s or s.lower() in ("nan", "none"):
        return None
    up = s.upper()
    if up.isalpha() and len(up) == 3:
        return up
    if s in _SYMBOL_TO_CODE:
        return _SYMBOL_TO_CODE[s]
    if up in _SYMBOL_TO_CODE:
        return _SYMBOL_TO_CODE[up]
    if s == "$":
        return AMBIGUOUS
    return None


def detect_currencies(df, mapping):
    """Sorted distinct normalized currencies in the mapped currency column.
    Empty list if unmapped/absent. Never raises."""
    col = mapping.get("order_currency")
    if not col or col not in df.columns:
        return []
    try:
        codes = df[col].map(normalize_currency).dropna()
        return sorted(set(codes.tolist()))
    except Exception:
        return []


def convert_amounts(amounts, currencies, rates):
    """`amounts` (numeric Series) times each row's rate, looked up from the row's
    normalized `currencies` code in `rates` ({code: rate}, base=1.0). A currency
    absent from `rates` yields NaN (an unconvertible row the validator treats as a
    bad amount)."""
    factors = currencies.map(rates)
    return (pd.to_numeric(amounts, errors="coerce")
            * pd.to_numeric(factors, errors="coerce"))


def currency_label(code):
    """Display symbol for a code ('AUD' -> 'A$'); falls back to the raw code.
    Empty string for a falsy code."""
    if not code:
        return ""
    return _CODE_TO_SYMBOL.get(str(code).upper(), str(code))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_currency.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/data/ingest/currency.py tests/test_currency.py
git commit -m "feat: currency normalize/detect/convert/label module"
```

---

## Task 2: Add `order_currency` canonical field

**Files:**
- Modify: `src/data/ingest/mapper.py:18-38` (add field to `CANONICAL_FIELDS`)
- Modify: `src/ui/upload.py:57-62` (add its confirm-screen label so the gate doesn't KeyError)
- Test: `tests/test_ingest.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingest.py`:

```python
def test_mapper_has_order_currency_optional():
    from src.data.ingest.mapper import CANONICAL_FIELDS
    assert "order_currency" in CANONICAL_FIELDS
    assert CANONICAL_FIELDS["order_currency"]["required"] is False


def test_fuzzy_map_finds_currency_column():
    from src.data.ingest.mapper import fuzzy_map
    profile = [{"name": "Customer"}, {"name": "Order"}, {"name": "Date"},
               {"name": "Total"}, {"name": "Currency"}]
    m = fuzzy_map(profile)
    assert m["order_currency"] == "Currency"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest.py::test_mapper_has_order_currency_optional tests/test_ingest.py::test_fuzzy_map_finds_currency_column -v`
Expected: FAIL — `KeyError: 'order_currency'`.

- [ ] **Step 3: Write minimal implementation**

In `src/data/ingest/mapper.py`, add after the `quantity` entry inside `CANONICAL_FIELDS` (keep it last so required + product/category/quantity claim headers first):

```python
    "quantity": {"required": False,
                 "aliases": ["quantity", "qty", "count", "units", "number"]},
    "order_currency": {"required": False,
                       "aliases": ["currency", "curr", "ccy", "iso_currency",
                                   "currency_code"]},
```

In `src/ui/upload.py`, add the label to `_FIELD_LABEL` so `render_confirm_gate`'s loop (which iterates every optional field) can render it:

```python
_FIELD_LABEL = {
    "customer_id": "Customer ID", "order_id": "Order ID",
    "order_date": "Order date", "order_amount": "Order amount",
    "product": "Product (optional)", "category": "Category (optional)",
    "quantity": "Quantity (optional)", "order_currency": "Currency (optional)",
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest.py::test_mapper_has_order_currency_optional tests/test_ingest.py::test_fuzzy_map_finds_currency_column -v`
Expected: PASS. Then `pytest tests/test_ingest.py -q` — still green (no regressions).

- [ ] **Step 5: Commit**

```bash
git add src/data/ingest/mapper.py src/ui/upload.py tests/test_ingest.py
git commit -m "feat: add optional order_currency canonical field"
```

---

## Task 3: Validator conversion + gate

**Files:**
- Modify: `src/data/ingest/validator.py:59-65` (`ValidationResult` field), `:84` (signature), `:133-147` (currency block), success return `:187`
- Test: `tests/test_ingest.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingest.py`:

```python
def _cur_mapping():
    return {"customer_id": "cust", "order_id": "ord", "order_date": "when",
            "order_amount": "amt", "order_currency": "cur"}


def test_validate_single_currency_labels():
    df = pd.DataFrame({"cust": ["c1", "c2"], "ord": ["o1", "o2"],
                       "when": ["2025-01-01", "2025-01-02"], "amt": ["10", "20"],
                       "cur": ["AUD", "AUD"]})
    res = validate(df, _cur_mapping())
    assert res.ok
    assert res.reporting_currency == "AUD"


def test_validate_multi_currency_gated_without_rates():
    df = pd.DataFrame({"cust": ["c1", "c2"], "ord": ["o1", "o2"],
                       "when": ["2025-01-01", "2025-01-02"], "amt": ["10", "10"],
                       "cur": ["USD", "AUD"]})
    res = validate(df, _cur_mapping(), reporting_currency="AUD")
    assert not res.ok
    assert "currenc" in res.errors[0].lower()


def test_validate_multi_currency_converts_with_rates():
    df = pd.DataFrame({"cust": ["c1", "c2"], "ord": ["o1", "o2"],
                       "when": ["2025-01-01", "2025-01-02"], "amt": ["10", "10"],
                       "cur": ["USD", "AUD"]})
    res = validate(df, _cur_mapping(), reporting_currency="AUD",
                   rates={"AUD": 1.0, "USD": 1.53})
    assert res.ok
    assert res.reporting_currency == "AUD"
    got = dict(zip(res.orders["order_id"], res.orders["order_amount"].round(2)))
    assert got["o1"] == 15.30   # USD 10 * 1.53
    assert got["o2"] == 10.00   # AUD 10 * 1.0


def test_validate_no_currency_column_unchanged():
    df = pd.DataFrame({"cust": ["c1"], "ord": ["o1"],
                       "when": ["2025-01-01"], "amt": ["$10"]})
    res = validate(df, {"customer_id": "cust", "order_id": "ord",
                        "order_date": "when", "order_amount": "amt"})
    assert res.ok
    assert res.reporting_currency is None
    assert res.orders["order_amount"].iloc[0] == 10.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest.py::test_validate_multi_currency_converts_with_rates -v`
Expected: FAIL — `TypeError: validate() got an unexpected keyword argument 'reporting_currency'`.

- [ ] **Step 3: Write minimal implementation**

In `src/data/ingest/validator.py`, add a field to `ValidationResult` (after `order_items`):

```python
@dataclass
class ValidationResult:
    ok: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    orders: pd.DataFrame = None       # canonical orders when ok
    order_items: pd.DataFrame = None  # canonical items when optional cols mapped
    reporting_currency: str = None    # resolved reporting currency (label/metadata)
```

Change the signature:

```python
def validate(df, mapping, dayfirst=None, reporting_currency=None, rates=None) -> ValidationResult:
```

Replace the amount block (currently `raw_amt = df[mapping["order_amount"]]` … `orders["order_amount"] = amt`) with the same lines plus a currency step inserted immediately after `amt = _clean_amount(raw_amt)` and before the `bad_amt` check, so all downstream checks run on converted values:

```python
    raw_amt = df[mapping["order_amount"]]
    amt = _clean_amount(raw_amt)

    # --- Currency consolidation. Active ONLY when a currency column is mapped;
    # single-currency and no-column files are byte-for-byte unchanged. Conversion
    # happens here (all amount coercion lives in the validator) so every check
    # below sees final reporting-currency amounts. ---
    resolved_currency = reporting_currency
    curr_col = mapping.get("order_currency")
    if curr_col and curr_col in df.columns:
        from src.data.ingest.currency import (
            detect_currencies, convert_amounts, normalize_currency, AMBIGUOUS)
        detected = detect_currencies(df, mapping)
        if len(detected) == 1:
            resolved_currency = reporting_currency or detected[0]
        elif len(detected) > 1:
            codes = df[curr_col].map(normalize_currency)
            base = reporting_currency or str(codes.value_counts().idxmax())
            rate_map = dict(rates or {})
            rate_map.setdefault(base, 1.0)
            required = [c for c in detected if c != AMBIGUOUS]
            missing = [c for c in required if not rate_map.get(c)]
            if rates is None or missing:
                errors.append(
                    f"This file contains {len(detected)} currencies "
                    f"({', '.join(detected)}). Enter a conversion rate for each "
                    f"(relative to {base}) on the confirm screen before analysis "
                    f"can run.")
                return ValidationResult(False, errors, warnings)
            if AMBIGUOUS in detected and not rate_map.get(AMBIGUOUS):
                n_amb = int((codes == AMBIGUOUS).sum())
                warnings.append(
                    f"{n_amb} order(s) use an ambiguous '$' currency with no rate "
                    f"and were dropped. Assign a rate to '$?' to include them.")
            amt = convert_amounts(amt, codes, rate_map)
            resolved_currency = base

    bad_amt = amt.isna() & raw_amt.notna() & (raw_amt.astype(str).str.strip() != "")
```

(Leave the rest of the amount block — the `bad_amt` fail-fraction check, negatives clip, `orders["order_amount"] = amt`, comma-decimal warning — exactly as it is; it now operates on converted values.)

Finally, change the success return to carry the resolved currency:

```python
    return ValidationResult(True, [], warnings, orders, items,
                            reporting_currency=resolved_currency)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest.py -q`
Expected: PASS — all four new tests plus the existing ingest suite green.

- [ ] **Step 5: Commit**

```bash
git add src/data/ingest/validator.py tests/test_ingest.py
git commit -m "feat: validator multi-currency gate + conversion"
```

---

## Task 4: Builder threading

**Files:**
- Modify: `src/data/ingest/builder.py:49-59` (signature + failure return), `:102-103` (success return)
- Test: `tests/test_ingest.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_ingest.py`:

```python
def test_build_canonical_threads_currency_end_to_end():
    # Messy AU export: AUD + USD, two single-line orders. Consolidate to AUD.
    df = pd.DataFrame({
        "cust": ["c1", "c2"], "ord": ["o1", "o2"],
        "when": ["03/04/2025", "05/04/2025"],
        "amt": ["$10.00", "US$10.00"], "cur": ["AUD", "USD"]})
    mapping = {"customer_id": "cust", "order_id": "ord", "order_date": "when",
               "order_amount": "amt", "order_currency": "cur"}
    from src.data.ingest.builder import build_canonical
    # No rates -> gated failure surfaced as a clean error, not a crash.
    gated = build_canonical(df, mapping, reporting_currency="AUD")
    assert gated["ok"] is False
    assert gated["reporting_currency"] is None
    # With rates -> converts and builds a matrix; monetary is in AUD.
    ok = build_canonical(df, mapping, reporting_currency="AUD",
                         rates={"AUD": 1.0, "USD": 2.0})
    assert ok["ok"] is True
    assert ok["reporting_currency"] == "AUD"
    monetary = dict(zip(ok["matrix"].frame["customer_id"],
                        ok["matrix"].frame["monetary"]))
    assert round(monetary["c1"], 2) == 10.0   # AUD 10
    assert round(monetary["c2"], 2) == 20.0   # USD 10 * 2.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ingest.py::test_build_canonical_threads_currency_end_to_end -v`
Expected: FAIL — `TypeError: build_canonical() got an unexpected keyword argument 'reporting_currency'`.

- [ ] **Step 3: Write minimal implementation**

In `src/data/ingest/builder.py`, change the signature and the two return dicts:

```python
def build_canonical(df, mapping, dayfirst=None, grain=None,
                    reporting_currency=None, rates=None) -> dict:
    """Validate + build. Returns {ok, errors, warnings, orders, order_items,
    matrix, reporting_currency}; matrix/orders are None when validation fails.

    dayfirst: override date locale (None = auto-detect).
    grain: None = auto / "line_item" = always-sum / "order_level" = keep-first.
    reporting_currency / rates: fold a multi-currency file into one currency
    (None = single-currency / no currency column).
    """
    result = validate(df, mapping, dayfirst=dayfirst,
                      reporting_currency=reporting_currency, rates=rates)
    if not result.ok:
        return {"ok": False, "errors": result.errors, "warnings": result.warnings,
                "orders": None, "order_items": None, "matrix": None,
                "reporting_currency": None}
```

And the success return at the end of the function:

```python
    return {"ok": True, "errors": [], "warnings": warnings,
            "orders": orders, "order_items": result.order_items, "matrix": matrix,
            "reporting_currency": result.reporting_currency}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ingest.py::test_build_canonical_threads_currency_end_to_end -q`
Expected: PASS. Then `pytest tests/test_ingest.py tests/test_canonical.py -q` — green.

- [ ] **Step 5: Commit**

```bash
git add src/data/ingest/builder.py tests/test_ingest.py
git commit -m "feat: thread reporting_currency/rates through build_canonical"
```

---

## Task 5: Persist currency in the mapping recipe

**Files:**
- Modify: `src/data/ingest/mapping_store.py:34-53` (`save_mapping` extras + new `load_recipe`)
- Test: `tests/test_mapping_persist.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_mapping_persist.py`:

```python
def test_recipe_round_trips_currency(tmp_path):
    from src.data.ingest.mapping_store import save_mapping, load_recipe
    p = str(tmp_path / "m.json")
    headers = ["a", "b", "c"]
    save_mapping(headers, {"customer_id": "a"}, path=p,
                 extras={"reporting_currency": "AUD",
                         "rates": {"AUD": 1.0, "USD": 1.5}})
    rec = load_recipe(headers, path=p)
    assert rec["mapping"]["customer_id"] == "a"
    assert rec["reporting_currency"] == "AUD"
    assert rec["rates"]["USD"] == 1.5


def test_load_recipe_pre_currency_recipe(tmp_path):
    from src.data.ingest.mapping_store import save_mapping, load_recipe
    p = str(tmp_path / "m.json")
    save_mapping(["a"], {"customer_id": "a"}, path=p)  # no extras
    rec = load_recipe(["a"], path=p)
    assert rec["mapping"]["customer_id"] == "a"
    assert rec.get("reporting_currency") is None


def test_load_recipe_missing_returns_none(tmp_path):
    from src.data.ingest.mapping_store import load_recipe
    assert load_recipe(["x"], path=str(tmp_path / "nope.json")) is None
```

If `tests/test_mapping_persist.py` does not already `import`/use `tmp_path`, no change is needed — `tmp_path` is a built-in pytest fixture.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mapping_persist.py::test_recipe_round_trips_currency -v`
Expected: FAIL — `TypeError: save_mapping() got an unexpected keyword argument 'extras'`.

- [ ] **Step 3: Write minimal implementation**

In `src/data/ingest/mapping_store.py`, extend `save_mapping` and add `load_recipe` (keep `load_mapping` unchanged for back-compat):

```python
def save_mapping(headers, mapping: dict, path: str = _STORE, extras: dict = None) -> str:
    """Persist `mapping` (plus any `extras`, e.g. reporting_currency + rates)
    under this header set's fingerprint. Returns the fingerprint. Best-effort:
    swallows any I/O error."""
    fp = fingerprint(headers)
    data = _load_all(path)
    entry = {"mapping": mapping}
    if extras:
        entry.update(extras)
    data[fp] = entry
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass
    return fp


def load_mapping(headers, path: str = _STORE):
    """Return the saved mapping for this header set's fingerprint, or None."""
    return _load_all(path).get(fingerprint(headers), {}).get("mapping")


def load_recipe(headers, path: str = _STORE):
    """Return the full saved entry ({'mapping', optional 'reporting_currency',
    'rates'}) for this header set, or None if there is none."""
    return _load_all(path).get(fingerprint(headers)) or None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mapping_persist.py -q`
Expected: PASS (new + existing).

- [ ] **Step 5: Commit**

```bash
git add src/data/ingest/mapping_store.py tests/test_mapping_persist.py
git commit -m "feat: persist reporting currency + rates in mapping recipe"
```

---

## Task 6: Upload pure functions — thread + persist + fast-path currency

**Files:**
- Modify: `src/ui/upload.py:22-52` (`prepare_upload` uses `load_recipe`; `apply_mapping` threads + persists currency)
- Test: `tests/test_upload_flow.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_upload_flow.py` (imports `io`, `json`, `tempfile`, `pandas as pd` already exist in the file):

```python
def test_apply_mapping_forwards_and_persists_currency(monkeypatch):
    import src.ui.upload as up
    captured = {}

    def fake_build(df, mapping, dayfirst=None, grain=None,
                   reporting_currency=None, rates=None):
        captured["rc"] = reporting_currency
        captured["rates"] = rates
        return {"ok": True, "errors": [], "warnings": [], "orders": None,
                "order_items": None, "matrix": None,
                "reporting_currency": reporting_currency}

    monkeypatch.setattr(up, "build_canonical", fake_build)
    df = pd.DataFrame({"a": ["1"], "b": ["2"]})
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "m.json")
        up.apply_mapping(df, {"customer_id": "a"}, store_path=store,
                         reporting_currency="AUD",
                         rates={"AUD": 1.0, "USD": 1.5})
        saved = json.load(open(store))
    assert captured["rc"] == "AUD"
    assert captured["rates"]["USD"] == 1.5
    entry = next(iter(saved.values()))
    assert entry["reporting_currency"] == "AUD"
    assert entry["rates"]["USD"] == 1.5


def test_prepare_upload_fast_path_returns_saved_currency():
    df = pd.read_csv(io.StringIO(_GOOD_CSV), dtype=str)
    mapping = {"customer_id": "Cust", "order_id": "Ord",
               "order_date": "When", "order_amount": "Paid"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "m.json")
        from src.data.ingest.mapping_store import save_mapping
        save_mapping(list(df.columns), mapping, path=store,
                     extras={"reporting_currency": "AUD",
                             "rates": {"AUD": 1.0, "USD": 1.5}})
        state = prepare_upload(df, generate_fn=_fake_generate, store_path=store)
    assert state["stage"] == "build"
    assert state["reporting_currency"] == "AUD"
    assert state["rates"]["USD"] == 1.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_upload_flow.py::test_apply_mapping_forwards_and_persists_currency tests/test_upload_flow.py::test_prepare_upload_fast_path_returns_saved_currency -v`
Expected: FAIL — `apply_mapping()` rejects `reporting_currency`; `prepare_upload` result has no `reporting_currency` key.

- [ ] **Step 3: Write minimal implementation**

In `src/ui/upload.py`, update the import line and both pure functions. Change the mapping-store import:

```python
from src.data.ingest.mapping_store import (
    load_mapping, load_recipe, save_mapping, _STORE,
)
```

`prepare_upload` — use `load_recipe` so the fast path carries currency:

```python
def prepare_upload(df, generate_fn, store_path=_STORE):
    """Profile the uploaded frame and resolve its column mapping.

    Returns {stage, mapping, source, profile, saved, reporting_currency, rates}.
    A saved recipe (matched by header fingerprint) fast-paths to stage "build"
    and replays its stored reporting_currency + rates; otherwise a proposed
    mapping goes to stage "confirm" with currency None (set on the confirm screen).
    """
    profile = profile_columns(df)
    headers = list(df.columns)
    recipe = load_recipe(headers, path=store_path)
    if recipe and recipe.get("mapping"):
        return {"stage": "build", "mapping": recipe["mapping"], "source": "saved",
                "profile": profile, "saved": True,
                "reporting_currency": recipe.get("reporting_currency"),
                "rates": recipe.get("rates")}
    proposed = propose_mapping(profile, generate_fn=generate_fn)
    return {"stage": "confirm", "mapping": proposed["mapping"],
            "source": proposed["source"], "profile": profile, "saved": False,
            "reporting_currency": None, "rates": None}
```

`apply_mapping` — thread + persist currency:

```python
def apply_mapping(df, mapping, store_path=_STORE, dayfirst=None, grain=None,
                  reporting_currency=None, rates=None):
    """Validate + build canonical for a confirmed mapping.

    `dayfirst`/`grain`/`reporting_currency`/`rates` are optional operator
    overrides (None = auto / single-currency). On success, persists the mapping
    recipe (with any currency settings) for next time. Returns the builder result
    dict {ok, errors, warnings, orders, order_items, matrix, reporting_currency}.
    """
    result = build_canonical(df, mapping, dayfirst=dayfirst, grain=grain,
                             reporting_currency=reporting_currency, rates=rates)
    if result["ok"]:
        extras = {}
        if reporting_currency:
            extras["reporting_currency"] = reporting_currency
        if rates:
            extras["rates"] = rates
        save_mapping(list(df.columns), mapping, path=store_path,
                     extras=extras or None)
    return result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_upload_flow.py -q`
Expected: PASS — new tests plus the existing upload-flow suite (the fast-path test `test_prepare_upload_uses_saved_recipe_fast_path` still works because `load_recipe` returns `{"mapping": ...}`).

- [ ] **Step 5: Commit**

```bash
git add src/ui/upload.py tests/test_upload_flow.py
git commit -m "feat: thread + persist currency through upload pure functions"
```

---

## Task 7: Confirm-screen currency UI + dataset seam

**Files:**
- Modify: `src/ui/upload.py:66-83` (session-key hygiene), `:133-148` (`_build_and_activate`), `:126-130` (fast-path call), `:205-233` (currency block + gated Confirm)
- Modify: `src/ui/dataset.py:16-35` (store `reporting_currency`)
- Test: `tests/test_upload_flow.py` (append AppTest)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_upload_flow.py`:

```python
def test_confirm_gate_shows_currency_controls_and_gates():
    from streamlit.testing.v1 import AppTest
    script = (
        "import os, sys\n"
        "sys.path.insert(0, os.getcwd())\n"
        "import pandas as pd, streamlit as st\n"
        "from src.ui.upload import render_confirm_gate\n"
        "st.session_state['upload_stage'] = 'confirm'\n"
        "st.session_state['upload_df'] = pd.DataFrame({'c':['c1','c2'],'o':['o1','o2'],"
        "'when':['2025-01-01','2025-01-02'],'amt':['10','10'],'cur':['USD','AUD']})\n"
        "st.session_state['upload_mapping'] = {'customer_id':'c','order_id':'o',"
        "'order_date':'when','order_amount':'amt','order_currency':'cur'}\n"
        "st.session_state['upload_filename'] = 'f.csv'\n"
        "render_confirm_gate(lambda *a, **k: None)\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, f"confirm gate raised: {at.exception}"
    assert "Reporting currency" in [s.label for s in at.selectbox], \
        [s.label for s in at.selectbox]
    assert any(n.label.startswith("1 USD") for n in at.number_input), \
        [n.label for n in at.number_input]
```

Also append to the `__main__` block at the bottom of the file:

```python
    test_confirm_gate_shows_currency_controls_and_gates()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_upload_flow.py::test_confirm_gate_shows_currency_controls_and_gates -v`
Expected: FAIL — no selectbox labelled "Reporting currency".

- [ ] **Step 3: Write minimal implementation**

**3a.** In `src/ui/dataset.py`, add the param + store it:

```python
def set_active_dataset(state, *, orders, order_items, features, available,
                       active_levers, label, source, reporting_currency=None):
```

and, alongside the other `state[...] =` writes (e.g. after `state["dataset_source"] = source`):

```python
    state["reporting_currency"] = reporting_currency
```

**3b.** In `src/ui/upload.py`, add the new session key and broaden the clear helper.

Add `"reporting_currency_choice"` to `_UPLOAD_KEYS`:

```python
_UPLOAD_KEYS = ("upload_stage", "upload_df", "upload_filename", "upload_mapping",
                "upload_profile", "upload_saved", "upload_errors", "upload_warnings",
                "date_locale_choice", "order_grain_choice",
                "reporting_currency_choice")
```

In `_clear_upload_state`, also clear `rate_*` keys (the per-currency inputs) by widening the prefix match:

```python
    for k in [k for k in list(st.session_state)
              if k.startswith("map_") or k.startswith("rate_")]:
        st.session_state.pop(k, None)
```

**3c.** In `render_confirm_gate`, insert the currency block after the grain radio/caption (right before the `_dayfirst_override` inner def) so `chosen` is already built:

```python
    # --- Currencies: detect + collect operator rates; gate Confirm on completeness. ---
    from src.data.ingest.currency import (
        detect_currencies, normalize_currency, AMBIGUOUS)
    detected_currencies = detect_currencies(df, chosen)
    reporting_currency = None
    rates = None
    currency_ready = True
    if len(detected_currencies) == 1:
        reporting_currency = detected_currencies[0]
        st.caption(f"💱 All orders are in {reporting_currency}. No conversion needed.")
    elif len(detected_currencies) > 1:
        st.markdown("**💱 Currencies** — this file mixes currencies. Pick the "
                    "reporting currency and enter a rate for every other one.")
        counts = df[chosen["order_currency"]].map(normalize_currency).value_counts()
        base = st.selectbox("Reporting currency", detected_currencies, index=0,
                            key="reporting_currency_choice")
        rates = {base: 1.0}
        for code in detected_currencies:
            if code == base:
                continue
            n = int(counts.get(code, 0))
            r = st.number_input(f"1 {code} = ? {base}  ({n:,} orders)",
                                min_value=0.0, value=0.0, step=0.01,
                                format="%.4f", key=f"rate_{code}")
            rates[code] = r
            if code != AMBIGUOUS and not r:
                currency_ready = False
        reporting_currency = base
        if not currency_ready:
            st.warning("Enter a non-zero rate for every currency before analyzing.")
```

Then change the Confirm button so it is disabled until currency is ready and forwards the two new args:

```python
    c1, c2 = st.columns(2)
    if c1.button("✅ Confirm & analyze", type="primary", use_container_width=True,
                 disabled=not currency_ready):
        _build_and_activate(fname, df, chosen, run_analysis,
                            dayfirst=_dayfirst_override(), grain=_grain_override(),
                            reporting_currency=reporting_currency, rates=rates)
        st.rerun()
    if c2.button("Cancel", use_container_width=True):
        _clear_upload_state(reset_uploader=True)
        st.rerun()
    return True
```

**3d.** Update `_build_and_activate` to accept + forward currency and pass it to the dataset seam:

```python
def _build_and_activate(filename, df, mapping, run_analysis, *, dayfirst=None,
                        grain=None, reporting_currency=None, rates=None):
    """Run apply_mapping; on success swap the active dataset + analyze."""
    result = apply_mapping(df, mapping, dayfirst=dayfirst, grain=grain,
                           reporting_currency=reporting_currency, rates=rates)
    if not result["ok"]:
        st.session_state["upload_stage"] = "confirm"
        st.session_state["upload_errors"] = result["errors"]
        return
    feats, available, active = features_from_matrix(result["matrix"])
    set_active_dataset(st.session_state, orders=result["orders"],
                       order_items=result["order_items"], features=feats,
                       available=available, active_levers=active,
                       label=filename, source="upload",
                       reporting_currency=result.get("reporting_currency"))
    warnings = result.get("warnings", [])
    _clear_upload_state()
    st.session_state["upload_warnings"] = warnings
    run_analysis(st.session_state["top_pct"])
```

**3e.** Update the fast-path call in `render_upload_section` (the `if prep["stage"] == "build":` branch) to replay stored currency + rates:

```python
        if prep["stage"] == "build":
            _build_and_activate(up.name, df, prep["mapping"], run_analysis,
                                reporting_currency=prep.get("reporting_currency"),
                                rates=prep.get("rates"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_upload_flow.py tests/test_dataset_swap.py -q`
Expected: PASS — the new AppTest plus existing upload-flow and dataset-swap suites (the demo boot in `app.py` still calls `set_active_dataset` without `reporting_currency`, which now defaults to `None`).

- [ ] **Step 5: Commit**

```bash
git add src/ui/upload.py src/ui/dataset.py tests/test_upload_flow.py
git commit -m "feat: confirm-screen currency controls + gated Confirm"
```

---

## Task 8: Label monetary figures with the reporting currency

**Files:**
- Modify: `src/agent/tools.py` (near `:835-921`) — money prefix helper + scalar rendering
- Modify: `src/export/generator.py:44-61` (CSV header suffix), `:92-98` (report currency line)
- Test: `tests/test_tools_canonical.py` (append), `tests/test_export.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_export.py`:

```python
def test_csv_export_labels_monetary_currency():
    from streamlit.testing.v1 import AppTest
    script = (
        "import os, sys\n"
        "sys.path.insert(0, os.getcwd())\n"
        "import pandas as pd, streamlit as st\n"
        "from src.export.generator import generate_csv_export\n"
        "st.session_state['scored_df'] = pd.DataFrame({'user_id':[1,2],"
        "'loyalty_score':[80.0,20.0],'monetary':[100.0,50.0]})\n"
        "st.session_state['power_user_ids'] = {1}\n"
        "st.session_state['reporting_currency'] = 'AUD'\n"
        "st.session_state['_out'] = generate_csv_export().decode('utf-8')\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, at.exception
    header = at.session_state['_out'].splitlines()[0]
    assert "(AUD)" in header, header
```

Append to `tests/test_tools_canonical.py`:

```python
def test_grounded_query_scalar_shows_currency_symbol():
    from streamlit.testing.v1 import AppTest
    script = (
        "import os, sys\n"
        "sys.path.insert(0, os.getcwd())\n"
        "import pandas as pd, streamlit as st\n"
        "from src.agent.tools import run_grounded_query\n"
        "st.session_state['ui_history'] = []\n"
        "st.session_state['features'] = pd.DataFrame({'user_id':[1,2,3],"
        "'monetary':[100.0,200.0,300.0]})\n"
        "st.session_state['orders'] = pd.DataFrame({'customer_id':[1],'order_id':[1],"
        "'order_date':pd.to_datetime(['2025-01-01']),'order_amount':[10.0]})\n"
        "st.session_state['full_data'] = None\n"
        "st.session_state['reporting_currency'] = 'AUD'\n"
        "run_grounded_query(table='customers', operation='aggregate',"
        " metric='monetary', agg='mean')\n"
    )
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, at.exception
    texts = [m.get('content', '') for m in at.session_state['ui_history']]
    assert any('A$' in t for t in texts), texts
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_export.py::test_csv_export_labels_monetary_currency tests/test_tools_canonical.py::test_grounded_query_scalar_shows_currency_symbol -v`
Expected: FAIL — header lacks `(AUD)`; the grounded-query card shows `200` with no `A$`.

- [ ] **Step 3: Write minimal implementation**

**3a.** In `src/agent/tools.py`, add a helper near the other `_gq_*` helpers (just above `def run_grounded_query`):

```python
_MONETARY_COLS = {"monetary", "avg_order_value", "order_amount"}


def _gq_money_prefix(metric, agg):
    """Reporting-currency symbol to prefix a monetary figure, or '' if the metric
    isn't monetary / the agg is a count / no reporting currency is set."""
    if agg == "count" or metric not in _MONETARY_COLS:
        return ""
    from src.data.ingest.currency import currency_label
    return currency_label(st.session_state.get("reporting_currency"))
```

Then in `run_grounded_query`'s `if kind == "scalar":` branch, prefix the value and tell the model the currency:

```python
    if kind == "scalar":
        money = _gq_money_prefix(metric, agg)
        label = f"{agg.title()} of {metric.replace('_', ' ')}"
        st.session_state.ui_history.append({
            "role": "assistant", "type": "text",
            "content": (f"### 📐 {label}\n\n**{money}{_gq_fmt(result['value'])}**  \n"
                        f"_computed over {result['n']:,} rows_"),
        })
        rc = st.session_state.get("reporting_currency")
        return {
            "status": "success", "kind": "scalar", "computed": label,
            "value": result["value"], "n": result["n"], "query": result["query"],
            "currency": rc if money else None,
            "instruction": (
                "State this computed figure in one sentence. Use ONLY this number"
                + (f", expressed in {rc}." if money else ".")),
        }
```

**3b.** In `src/export/generator.py`, label the monetary CSV columns. Replace the feature-column loop (currently `for c in feature_cols: final[feature_label(c)] = export_df[c]`) with:

```python
    from src.agent.tool_context import feature_label
    from src.data.ingest.currency import currency_label  # noqa: F401 (kept for parity)

    _META = {'user_id', 'customer_id', 'loyalty_score',
             'loyalty_tier', 'is_power_user'}
    _MONEY_COLS = {'monetary', 'avg_order_value', 'total_spend'}
    feature_cols = [c for c in export_df.columns if c not in _META]

    final = pd.DataFrame({
        'Customer ID': export_df['user_id'],
        'Loyalty Score (0-100)': export_df['loyalty_score'],
        'Loyalty Tier': export_df['loyalty_tier'],
        'Is Power User (1=Yes)': export_df['is_power_user'],
    })
    code = st.session_state.get('reporting_currency')
    for c in feature_cols:
        label = feature_label(c)
        if code and c in _MONEY_COLS:
            label = f"{label} ({code})"
        final[label] = export_df[c]
```

**3c.** In `src/export/generator.py` `generate_summary_report`, add a reporting-currency line to the header. Replace:

```python
    dataset = st.session_state.get('dataset_label', 'Your dataset')

    report = f"""# Customer Loyalty Intelligence Report
**Generated:** {now}
**Dataset:** {dataset}
```

with:

```python
    dataset = st.session_state.get('dataset_label', 'Your dataset')
    code = st.session_state.get('reporting_currency')
    currency_line = (f"\n**Reporting currency:** {code} "
                     f"(all monetary figures converted)") if code else ""

    report = f"""# Customer Loyalty Intelligence Report
**Generated:** {now}
**Dataset:** {dataset}{currency_line}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_export.py tests/test_tools_canonical.py -q`
Expected: PASS — new tests plus existing export/tools suites (the demo has no `reporting_currency`, so its output is unchanged).

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools.py src/export/generator.py tests/test_export.py tests/test_tools_canonical.py
git commit -m "feat: label monetary figures with the reporting currency"
```

---

## Task 9: Full-suite + runtime verification + journal

**Files:**
- Modify: `CLAUDE.md` (add a dated journal entry at the top of the Project Journal)

- [ ] **Step 1: Run the full test suite**

Run: `..\venv\Scripts\python.exe -m pytest -q`
Expected: PASS — all suites green, including `test_currency`, and the extended `test_ingest`, `test_mapping_persist`, `test_upload_flow`, `test_export`, `test_tools_canonical`.

- [ ] **Step 2: Runtime-verify the real app on a multi-currency upload**

Per the CSV-export lesson ("run the real full app after BYOD changes"), drive `app.py` end to end. Create a temporary script `scripts/_smoke_currency.py`:

```python
import io, pandas as pd
from streamlit.testing.v1 import AppTest
from src.ui.upload import apply_mapping
from src.data.app_data import features_from_matrix

csv = ("Cust,Ord,When,Paid,Cur\n"
       "c1,o1,2025-01-01,10.00,USD\n"
       "c2,o2,2025-01-02,10.00,AUD\n"
       "c3,o3,2025-01-03,20.00,NZD\n")
df = pd.read_csv(io.StringIO(csv), dtype=str)
m = {"customer_id": "Cust", "order_id": "Ord", "order_date": "When",
     "order_amount": "Paid", "order_currency": "Cur"}
# Gate holds without rates:
assert apply_mapping(df, m, reporting_currency="AUD")["ok"] is False
# Converts with rates:
res = apply_mapping(df, m, reporting_currency="AUD",
                    rates={"AUD": 1.0, "USD": 1.5, "NZD": 1.1})
assert res["ok"] and res["reporting_currency"] == "AUD"
mon = dict(zip(res["matrix"].frame["customer_id"], res["matrix"].frame["monetary"]))
assert round(mon["c1"], 2) == 15.0 and round(mon["c3"], 2) == 22.0
print("currency smoke: OK", mon)

at = AppTest.from_file("app.py", default_timeout=90).run()
assert not at.exception, at.exception
print("app boot: OK")
```

Run: `..\venv\Scripts\python.exe scripts/_smoke_currency.py`
Expected: prints `currency smoke: OK ...` and `app boot: OK`, no traceback. Then delete the temp script: `git clean -f scripts/_smoke_currency.py` (or `Remove-Item scripts/_smoke_currency.py`).

- [ ] **Step 3: Add the journal entry**

Add a dated entry at the TOP of the Project Journal in `CLAUDE.md` summarizing: the multi-currency depth pass (optional `order_currency` field → validator gate + operator-rate conversion in `currency.py` → recipe persistence → confirm-screen rate controls → reporting-currency labels on grounded-query/CSV/report), why (protect the `monetary` RFM figure the chat agent reports on real mixed-currency client data), and the test coverage (`test_currency` + extended ingest/persist/upload/export/tools suites + full-app runtime smoke). Match the style of the existing entries.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: journal multi-currency handling"
```

- [ ] **Step 5: Finish the branch**

Use the `superpowers:finishing-a-development-branch` skill to decide merge/PR/push. (Prior pattern for this repo: code review → `--no-ff` merge to `main` → push.)

---

## Self-Review

**Spec coverage:**
- Spec §3 (canonical `order_currency` field) → Task 2. ✅
- Spec §4 (currency module: normalize/detect/convert/label) → Task 1. ✅
- Spec §5 (validator params, single-currency label, multi-currency gate + conversion, `ValidationResult.reporting_currency`) → Task 3. ✅
- Spec §6 (builder threading + `reporting_currency` in result) → Task 4. ✅
- Spec §7 (confirm-screen currency block, most-frequent base default, per-currency rate inputs, gated Confirm, session-key hygiene, fast-path replay) → Task 7 (+ fast-path replay wired there; pure fast-path data from Task 6). ✅
- Spec §8 (recipe persistence of currency + rates; new-currency backstop = validator gate) → Task 5 (store) + Task 6 (persist on apply) + Task 7 (fast-path replays; gate re-fires on uncovered currency). ✅
- Spec §9 (label grounded-query monetary figure, CSV header, summary report; `reporting_currency` in session via dataset seam) → Task 8 (labels) + Task 7 (session seam). ✅
- Spec §10 (tests: `test_currency`, extended ingest/upload/persist; runtime verification) → Tasks 1–9. ✅

**Placeholder scan:** No TBD/TODO/"handle edge cases"; every code step shows complete code. ✅

**Type/name consistency:** `reporting_currency`/`rates` names are identical across `validate`, `build_canonical`, `apply_mapping`, `prepare_upload`, `_build_and_activate`, `set_active_dataset`. `ValidationResult.reporting_currency` and the builder/`apply_mapping` result key `"reporting_currency"` match. `AMBIGUOUS`, `normalize_currency`, `detect_currencies`, `convert_amounts`, `currency_label` are defined in Task 1 and imported by exact name in Tasks 3/7/8. `load_recipe` defined in Task 5, used in Task 6. `_MONETARY_COLS` (tools) vs `_MONEY_COLS` (generator) are intentionally separate module-local constants. ✅

**Ordering note:** Task 2 adds `order_currency` to `CANONICAL_FIELDS` *and* its `_FIELD_LABEL` in the same task, so the confirm gate never KeyErrors between tasks. The currency UI (Task 7) only renders once a currency column is mapped, so Tasks 2–6 keep the app green with no visible behavior change.
