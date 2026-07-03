# Ingestion Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a pure, testable upload-ingestion pipeline that turns any client CSV/Excel file into the canonical `orders` + `order_items` tables and a Phase-1 `FeatureMatrix`, with a human-confirmable column mapping and a malfunction firewall that never crashes on bad data.

**Architecture:** New package `src/data/ingest/` with six single-responsibility modules — `reader` (bytes → DataFrame), `profiler` (per-column profile; the ONLY thing sent to the LLM), `mapper` (LLM proposes a column mapping, deterministic fuzzy fallback when no LLM), `validator` (the firewall: dates/amounts/ids/required, returns human messages not stack traces), `builder` (validate → assemble canonical tables → `FeatureMatrix`), and `mapping_store` (persist the confirmed mapping recipe + a header fingerprint, never raw rows). Every module is Streamlit-free and unit-tested via the repo's standalone-script house style. The Streamlit confirm screen and app wiring are deliberately out of scope (Phase 4 integration), exactly as Phases 1 & 2 were scoped.

**Tech Stack:** Python, pandas, numpy, stdlib `csv`/`hashlib`/`json`/`difflib`. No pytest (standalone scripts with `check()` + non-zero exit), no network.

---

## Context the engineer needs

- **Repo root for this work:** `C:/Users/yashw/Desktop/customer-loyalty-agent/customer-loyalty-agent` (the *inner* directory). All paths below are relative to it.
- **Canonical contract (already built, Phase 1 — read it first):** `src/data/canonical.py`.
  - `orders` columns: `customer_id, order_id, order_date, order_amount` (REQUIRED).
  - `order_items` columns: `order_id, product, category, quantity` (OPTIONAL).
  - `build_feature_matrix(orders, order_items=None) -> FeatureMatrix`. It assumes **already-validated** input — this pipeline is what guarantees that.
- **Test house style (copy exactly from `tests/test_demo_adapter.py`):** standalone script, `sys.path.insert(0, <parent>)`, a `check(name, cond)` that prints `PASS`/`FAIL` and `sys.exit(1)` on failure, tiny in-memory fixtures, no network. Run with `..\venv\Scripts\python.exe tests/test_ingest.py`.
- **Branch:** create and work on `feat/ingest-pipeline`.
- **Commit style:** conventional-commit subjects. **Do NOT add a `Co-Authored-By: Claude` trailer** — attribute solely to the user.
- **Spec:** `docs/superpowers/specs/2026-06-26-intelligence-layer-byod-design.md` §3 (ingestion) and §3 "Persistence — mapping only".

### Design decisions locked for this plan

- **Reader reads every cell as a string** (`dtype=str`). Raw amounts (`"$1,234.50"`), leading-zero ids, and ambiguous dates are preserved verbatim so the *validator* is the single place that coerces types deterministically. This is what makes the firewall trustworthy.
- **The uploaded file is treated as order-grained for `orders`** (one logical order may appear on multiple line rows). The builder de-duplicates `orders` on `order_id` (keeping the first row's customer/date/amount), so `order_amount` is read as an order total repeated across line rows — not summed per line. This assumption is documented in `builder.py` and asserted by a test.
- **The mapper never trusts a hallucinated header.** Any LLM-proposed mapping value that is not an actual column name in the profile is dropped; the fuzzy fallback fills required fields it can.
- **`propose_mapping` takes an injectable `generate_fn`** (a `str -> str` text-completion callable). The pure module has NO Streamlit/`caller.generate` import; the app passes a wrapper in Phase 4. Tests pass a fake `generate_fn`.

### File structure (what each file owns)

- Create `src/data/ingest/__init__.py` — empty package marker.
- Create `src/data/ingest/reader.py` — `read_table`, `sniff_encoding`, `sniff_delimiter`.
- Create `src/data/ingest/profiler.py` — `profile_columns`.
- Create `src/data/ingest/mapper.py` — `CANONICAL_FIELDS`, `fuzzy_map`, `propose_mapping` (+ private `_build_prompt`, `_parse_llm_mapping`, `_score`, `_norm`).
- Create `src/data/ingest/validator.py` — `ValidationResult`, `validate`, `REQUIRED`.
- Create `src/data/ingest/builder.py` — `build_canonical`.
- Create `src/data/ingest/mapping_store.py` — `fingerprint`, `save_mapping`, `load_mapping`.
- Create `tests/test_ingest.py` — reader/profiler/mapper/validator/builder (the firewall contract).
- Create `tests/test_mapping_persist.py` — fingerprint + save/load round-trip.
- Modify `CLAUDE.md` — add a dated Project Journal entry (final task).

---

## Task 1: Package marker + reader

**Files:**
- Create: `src/data/ingest/__init__.py`
- Create: `src/data/ingest/reader.py`
- Test: `tests/test_ingest.py`

- [ ] **Step 1: Create the package marker**

```python
# src/data/ingest/__init__.py
"""Upload ingestion pipeline: file -> profile -> mapping -> validate -> canonical."""
```

- [ ] **Step 2: Write the failing test (start `tests/test_ingest.py`)**

```python
"""Standalone tests for src/data/ingest/. No network, tiny fixtures."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def test_reader_csv_comma(tmpdir):
    from src.data.ingest.reader import read_table
    p = os.path.join(tmpdir, "a.csv")
    with open(p, "w", encoding="utf-8") as f:
        f.write("cust,order,amt\n1,100,9.50\n1,101,3.00\n")
    df = read_table(p)
    check("csv rows read", len(df) == 2)
    check("csv headers read", list(df.columns) == ["cust", "order", "amt"])
    check("csv cells are strings", df["amt"].iloc[0] == "9.50")


def test_reader_semicolon_and_utf16(tmpdir):
    from src.data.ingest.reader import read_table
    p = os.path.join(tmpdir, "b.csv")
    with open(p, "w", encoding="utf-16") as f:
        f.write("cust;order;amt\n1;100;9,50\n")
    df = read_table(p)
    check("semicolon delimiter sniffed", list(df.columns) == ["cust", "order", "amt"])
    check("utf-16 decoded", df["amt"].iloc[0] == "9,50")


if __name__ == "__main__":
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        test_reader_csv_comma(d)
        test_reader_semicolon_and_utf16(d)
    print(f"\n{_passed} checks passed.")
```

- [ ] **Step 3: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.data.ingest.reader'`.

- [ ] **Step 4: Write `src/data/ingest/reader.py`**

```python
"""
File reader: bytes -> pandas DataFrame.

Reads CSV or Excel robustly. Every cell is read as a STRING (dtype=str) so raw
amounts ("$1,234.50"), leading-zero ids, and ambiguous dates survive verbatim to
the validator, which is the single place that coerces types. Pure / no Streamlit.
"""

import csv
from io import StringIO

import pandas as pd

# BOM-less fallbacks tried in order; latin-1 decodes any byte as a last resort.
_ENCODINGS = ["utf-8", "utf-16", "latin-1"]


def sniff_encoding(raw: bytes) -> str:
    """Pick an encoding from a BOM, else the first that decodes cleanly."""
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    if raw.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for enc in _ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "latin-1"


def sniff_delimiter(sample: str) -> str:
    """Guess the CSV delimiter; default to comma when the sniffer is unsure."""
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def read_table(path, sheet=0) -> pd.DataFrame:
    """Read a CSV or Excel file at `path` into an all-string DataFrame."""
    lower = str(path).lower()
    if lower.endswith((".xlsx", ".xls")):
        return pd.read_excel(path, sheet_name=sheet, dtype=str)
    with open(path, "rb") as f:
        raw = f.read()
    text = raw.decode(sniff_encoding(raw))
    sep = sniff_delimiter(text[:4096])
    return pd.read_csv(StringIO(text), sep=sep, dtype=str)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: PASS — `4 checks passed.`

- [ ] **Step 6: Commit**

```bash
git checkout -b feat/ingest-pipeline
git add src/data/ingest/__init__.py src/data/ingest/reader.py tests/test_ingest.py
git commit -m "feat(ingest): robust CSV/Excel reader with encoding + delimiter sniffing"
```

---

## Task 2: Column profiler

**Files:**
- Create: `src/data/ingest/profiler.py`
- Test: `tests/test_ingest.py` (append)

- [ ] **Step 1: Add the failing test**

Append to `tests/test_ingest.py` (before `if __name__`):

```python
def test_profiler():
    from src.data.ingest.profiler import profile_columns
    df = pd.DataFrame({
        "Cust Ref": ["1", "2", "2", "3"],
        "Total (AUD)": ["$9.50", "$3.00", "", "12"],
        "When": ["2024-01-02", "2024-01-05", "2024-02-01", "bad"],
        "Note": ["a", "b", "c", "d"],
    })
    profs = profile_columns(df)
    by = {p["name"]: p for p in profs}
    check("all columns profiled", set(by) == {"Cust Ref", "Total (AUD)", "When", "Note"})
    check("amount guessed numeric", by["Total (AUD)"]["guessed_kind"] == "numeric")
    check("date guessed date", by["When"]["guessed_kind"] == "date")
    check("note guessed text", by["Note"]["guessed_kind"] == "text")
    check("null pct computed", by["Total (AUD)"]["pct_null"] == 25.0)
    check("samples are strings", all(isinstance(s, str) for s in by["Note"]["samples"]))
```

And add its call inside `if __name__ == "__main__":` (no tmpdir needed):

```python
    test_profiler()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: FAIL — `No module named 'src.data.ingest.profiler'`.

- [ ] **Step 3: Write `src/data/ingest/profiler.py`**

```python
"""
Column profiler: describe each column without exposing raw rows.

Produces, per column, a name / guessed kind / a few sample values / %null /
%unique. This profile is the ONLY thing the mapper sends to the LLM — never raw
rows — so mapping is cheap and no customer PII leaves the machine. Pure module.
"""

import pandas as pd


def _blank(series: pd.Series) -> pd.Series:
    """True where a cell is NaN or an empty/whitespace string."""
    return series.isna() | (series.astype(str).str.strip() == "")


def _guess_kind(series: pd.Series) -> str:
    """Guess numeric / date / text / empty from up to 50 non-blank samples."""
    vals = series[~_blank(series)].astype(str)
    if len(vals) == 0:
        return "empty"
    sample = vals.head(50)
    numeric = pd.to_numeric(
        sample.str.replace(r"[$,]", "", regex=True), errors="coerce")
    if numeric.notna().mean() > 0.9:
        return "numeric"
    dates = pd.to_datetime(sample, errors="coerce")
    if dates.notna().mean() > 0.9:
        return "date"
    return "text"


def profile_columns(df: pd.DataFrame) -> list:
    """Return a list of per-column profile dicts (no raw rows leak beyond samples)."""
    n = len(df)
    out = []
    for col in df.columns:
        s = df[col]
        blank = _blank(s)
        out.append({
            "name": str(col),
            "guessed_kind": _guess_kind(s),
            "samples": s[~blank].astype(str).head(5).tolist(),
            "pct_null": round(float(blank.mean()) * 100, 1) if n else 0.0,
            "pct_unique": (round(float(s[~blank].nunique()) / n * 100, 1)
                           if n else 0.0),
        })
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: PASS — check count rises by 6.

- [ ] **Step 5: Commit**

```bash
git add src/data/ingest/profiler.py tests/test_ingest.py
git commit -m "feat(ingest): per-column profiler (kind, samples, null/unique) for LLM"
```

---

## Task 3: Mapper — deterministic fuzzy fallback

**Files:**
- Create: `src/data/ingest/mapper.py`
- Test: `tests/test_ingest.py` (append)

- [ ] **Step 1: Add the failing test**

Append to `tests/test_ingest.py` and add the calls under `__main__`:

```python
def test_fuzzy_map():
    from src.data.ingest.mapper import fuzzy_map
    profile = [
        {"name": "Customer Ref"}, {"name": "Order No"},
        {"name": "Order Date"}, {"name": "Total (AUD)"},
        {"name": "Product Name"}, {"name": "Dept"},
    ]
    m = fuzzy_map(profile)
    check("customer_id mapped", m["customer_id"] == "Customer Ref")
    check("order_id mapped", m["order_id"] == "Order No")
    check("order_date mapped", m["order_date"] == "Order Date")
    check("order_amount mapped", m["order_amount"] == "Total (AUD)")
    check("product mapped", m["product"] == "Product Name")
    check("category mapped", m["category"] == "Dept")
    check("absent optional is None", m["quantity"] is None)


def test_fuzzy_map_no_match():
    from src.data.ingest.mapper import fuzzy_map
    m = fuzzy_map([{"name": "xyz"}, {"name": "foo"}])
    check("unmatched required is None", m["customer_id"] is None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: FAIL — `No module named 'src.data.ingest.mapper'`.

- [ ] **Step 3: Write `src/data/ingest/mapper.py` (fuzzy half only)**

```python
"""
Column mapper: propose which upload column maps to each canonical field.

`propose_mapping` asks an injected LLM `generate_fn`; on any failure (or no
generate_fn) it falls back to `fuzzy_map`, a deterministic header matcher, so
ingestion works with zero LLM. Any LLM-proposed value that is not a real column
name is dropped — the mapper never trusts a hallucinated header. Pure module: no
Streamlit / no caller import; the app injects the LLM wrapper in a later phase.
"""

import json
import re
from difflib import SequenceMatcher

# Canonical target fields. `required` ones must be mapped before validation runs;
# `aliases` seed the fuzzy matcher. Order matters: earlier fields claim a header
# first (a header is used by at most one field).
CANONICAL_FIELDS = {
    "customer_id": {"required": True,
                    "aliases": ["customer", "cust", "user", "client", "buyer",
                                "member", "account", "email"]},
    "order_id":    {"required": True,
                    "aliases": ["order", "transaction", "txn", "invoice",
                                "receipt", "reference"]},
    "order_date":  {"required": True,
                    "aliases": ["date", "ordered", "purchase", "timestamp",
                                "created", "placed"]},
    "order_amount": {"required": True,
                     "aliases": ["amount", "total", "revenue", "price", "value",
                                 "spend", "sales", "gross", "paid", "aud"]},
    "product":  {"required": False,
                 "aliases": ["product", "item", "sku", "article", "name"]},
    "category": {"required": False,
                 "aliases": ["category", "department", "dept", "aisle", "type",
                             "class", "group"]},
    "quantity": {"required": False,
                 "aliases": ["quantity", "qty", "count", "units", "number"]},
}

_MATCH_THRESHOLD = 0.5


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _score(header: str, field: str, aliases: list) -> float:
    """Best similarity of a header to a canonical field name or its aliases."""
    h = _norm(header)
    best = 0.0
    for target in [field.replace("_", "")] + aliases:
        t = _norm(target)
        if not t or not h:
            continue
        if h == t:
            return 1.0
        if t in h or h in t:
            best = max(best, 0.8)
        best = max(best, SequenceMatcher(None, h, t).ratio())
    return best


def fuzzy_map(profile: list) -> dict:
    """Deterministic header->canonical mapping. `profile` is a list of column
    dicts (only each dict's `name` is used). Every canonical field is a key;
    unmatched fields map to None."""
    headers = [p["name"] for p in profile]
    mapping = {}
    used = set()
    for field, meta in CANONICAL_FIELDS.items():
        best_header, best_score = None, 0.0
        for h in headers:
            if h in used:
                continue
            s = _score(h, field, meta["aliases"])
            if s > best_score:
                best_header, best_score = h, s
        if best_header is not None and best_score >= _MATCH_THRESHOLD:
            mapping[field] = best_header
            used.add(best_header)
        else:
            mapping[field] = None
    return mapping
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: PASS — check count rises by 8.

- [ ] **Step 5: Commit**

```bash
git add src/data/ingest/mapper.py tests/test_ingest.py
git commit -m "feat(ingest): deterministic fuzzy header->canonical mapping fallback"
```

---

## Task 4: Mapper — LLM proposal with fallback

**Files:**
- Modify: `src/data/ingest/mapper.py`
- Test: `tests/test_ingest.py` (append)

- [ ] **Step 1: Add the failing test**

Append and register under `__main__`:

```python
def test_propose_mapping_llm():
    from src.data.ingest.mapper import propose_mapping
    profile = [{"name": "Cust Ref", "guessed_kind": "text", "samples": ["1"],
                "pct_null": 0.0, "pct_unique": 90.0}]

    def fake_gen(prompt):
        check("prompt carries header", "Cust Ref" in prompt)
        check("prompt has no raw-row dump", "SELECT" not in prompt)
        return '{"customer_id": "Cust Ref", "order_id": "Ghost Col"}'

    res = propose_mapping(profile, generate_fn=fake_gen)
    check("llm source", res["source"] == "llm")
    check("valid header kept", res["mapping"]["customer_id"] == "Cust Ref")
    check("hallucinated header dropped", res["mapping"].get("order_id") is None)


def test_propose_mapping_fallback():
    from src.data.ingest.mapper import propose_mapping
    profile = [{"name": "Customer Ref"}, {"name": "Order No"},
               {"name": "Order Date"}, {"name": "Total"}]

    def broken_gen(prompt):
        raise RuntimeError("all keys exhausted")

    res = propose_mapping(profile, generate_fn=broken_gen)
    check("falls back to fuzzy", res["source"] == "fuzzy")
    check("fuzzy still maps required", res["mapping"]["customer_id"] == "Customer Ref")

    res2 = propose_mapping(profile, generate_fn=None)
    check("no generate_fn -> fuzzy", res2["source"] == "fuzzy")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: FAIL — `cannot import name 'propose_mapping'`.

- [ ] **Step 3: Append the LLM half to `src/data/ingest/mapper.py`**

```python
def _build_prompt(profile: list) -> str:
    """Render the column profile (never raw rows) into a mapping request."""
    lines = ["You map a client's spreadsheet columns onto a fixed schema.",
             "Canonical fields (map each to ONE source column name, or omit it):",
             "  required: customer_id, order_id, order_date, order_amount",
             "  optional: product, category, quantity",
             "",
             "Source columns (name | kind | %null | %unique | samples):"]
    for p in profile:
        lines.append(
            f"  {p['name']} | {p.get('guessed_kind', '?')} | "
            f"{p.get('pct_null', '?')}% null | {p.get('pct_unique', '?')}% unique "
            f"| {p.get('samples', [])}")
    lines += ["",
              "Reply with ONLY a JSON object mapping canonical field -> source "
              "column name. Use exact source names. Omit fields with no match."]
    return "\n".join(lines)


def _parse_llm_mapping(raw: str, headers: list) -> dict:
    """Extract the JSON object and keep only real fields mapped to real headers."""
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object in LLM reply")
    obj = json.loads(raw[start:end + 1])
    header_set = set(headers)
    mapping = {f: None for f in CANONICAL_FIELDS}
    for field, col in obj.items():
        if field in CANONICAL_FIELDS and col in header_set:
            mapping[field] = col
    return mapping


def propose_mapping(profile: list, generate_fn=None) -> dict:
    """Propose a mapping. Returns {'mapping', 'source'} where source is 'llm' or
    'fuzzy'. Tries the injected `generate_fn(prompt)->str` first; on ANY failure
    (no fn, exception, unparseable/empty result) falls back to `fuzzy_map`."""
    headers = [p["name"] for p in profile]
    if generate_fn is not None:
        try:
            mapping = _parse_llm_mapping(generate_fn(_build_prompt(profile)), headers)
            if any(mapping.get(f) for f in CANONICAL_FIELDS
                   if CANONICAL_FIELDS[f]["required"]):
                return {"mapping": mapping, "source": "llm"}
        except Exception:
            pass
    return {"mapping": fuzzy_map(profile), "source": "fuzzy"}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: PASS — check count rises by 9.

- [ ] **Step 5: Commit**

```bash
git add src/data/ingest/mapper.py tests/test_ingest.py
git commit -m "feat(ingest): LLM mapping proposal with hallucination guard + fuzzy fallback"
```

---

## Task 5: Validator — the malfunction firewall

**Files:**
- Create: `src/data/ingest/validator.py`
- Test: `tests/test_ingest.py` (append)

- [ ] **Step 1: Add the failing tests (the firewall contract)**

Append and register under `__main__`:

```python
def _good_df():
    return pd.DataFrame({
        "cust": ["1", "1", "2"],
        "ord":  ["100", "101", "200"],
        "when": ["2024-01-02", "2024-01-20", "2024-01-05"],
        "amt":  ["$9.50", "1,200.00", "40"],
    })

_GOOD_MAP = {"customer_id": "cust", "order_id": "ord",
             "order_date": "when", "order_amount": "amt",
             "product": None, "category": None, "quantity": None}


def test_validate_happy():
    from src.data.ingest.validator import validate
    r = validate(_good_df(), _GOOD_MAP)
    check("valid input ok", r.ok is True)
    check("no errors", r.errors == [])
    check("dollar+comma amount cleaned", float(r.orders["order_amount"].iloc[1]) == 1200.0)
    check("dates parsed", str(r.orders["order_date"].dtype).startswith("datetime"))
    check("no items when unmapped", r.order_items is None)


def test_validate_missing_required():
    from src.data.ingest.validator import validate
    m = dict(_GOOD_MAP, order_amount=None)
    r = validate(_good_df(), m)
    check("rejects missing required", r.ok is False)
    check("names the missing field", any("order_amount" in e for e in r.errors))
    check("message is human, not a trace", all("Traceback" not in e for e in r.errors))


def test_validate_bad_dates():
    from src.data.ingest.validator import validate
    df = _good_df(); df["when"] = ["nope", "nope", "nope"]
    r = validate(df, _GOOD_MAP)
    check("rejects unparseable dates", r.ok is False)
    check("date error mentions column", any("when" in e for e in r.errors))


def test_validate_negative_amount_warns():
    from src.data.ingest.validator import validate
    df = _good_df(); df["amt"] = ["-5", "10", "20"]
    r = validate(df, _GOOD_MAP)
    check("negatives do not hard-fail", r.ok is True)
    check("negative produces a warning", any("negative" in w.lower() for w in r.warnings))
    check("negative clipped to 0", float(r.orders["order_amount"].iloc[0]) == 0.0)


def test_validate_builds_items():
    from src.data.ingest.validator import validate
    df = _good_df(); df["prod"] = ["milk", "eggs", "soda"]; df["dept"] = ["dairy", "dairy", "drinks"]
    m = dict(_GOOD_MAP, product="prod", category="dept")
    r = validate(df, m)
    check("items built when mapped", r.order_items is not None)
    check("items have canonical cols",
          set(["order_id", "product", "category", "quantity"]).issubset(r.order_items.columns))
    check("quantity defaults to 1", int(r.order_items["quantity"].iloc[0]) == 1)


def test_validate_empty_file():
    from src.data.ingest.validator import validate
    r = validate(pd.DataFrame({"cust": [], "ord": [], "when": [], "amt": []}), _GOOD_MAP)
    check("empty file rejected cleanly", r.ok is False)
    check("empty file has a message", len(r.errors) > 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: FAIL — `No module named 'src.data.ingest.validator'`.

- [ ] **Step 3: Write `src/data/ingest/validator.py`**

```python
"""
Validator: the malfunction firewall.

Takes the raw DataFrame + a confirmed column mapping and returns a
`ValidationResult`. On bad data it returns precise, human-readable messages —
never a stack trace. Coercion is deterministic and lives ONLY here: amounts are
stripped of currency symbols/commas and forced numeric (negatives clipped to 0
with a warning), dates are parsed, and rows missing any required field after
coercion are dropped. Pure module.
"""

from dataclasses import dataclass, field

import pandas as pd

REQUIRED = ["customer_id", "order_id", "order_date", "order_amount"]
# Fraction of unparseable values in a required column that flips a warning into
# a hard rejection.
_FAIL_FRACTION = 0.1


@dataclass
class ValidationResult:
    ok: bool
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    orders: pd.DataFrame = None       # canonical orders when ok
    order_items: pd.DataFrame = None  # canonical items when optional cols mapped


def _clean_amount(series: pd.Series) -> pd.Series:
    """Strip everything but digits/dot/minus, then coerce to float (NaN if empty)."""
    cleaned = (series.astype(str)
               .str.replace(r"[^0-9.\-]", "", regex=True)
               .replace("", None))
    return pd.to_numeric(cleaned, errors="coerce")


def validate(df: pd.DataFrame, mapping: dict) -> ValidationResult:
    errors, warnings = [], []

    missing = [f for f in REQUIRED if not mapping.get(f)]
    if missing:
        errors.append(
            "These required fields are not mapped to a column: "
            + ", ".join(missing) + ". Map them on the confirm screen and retry.")
        return ValidationResult(False, errors, warnings)

    if len(df) == 0:
        return ValidationResult(
            False, ["The uploaded file has no data rows."], warnings)

    orders = pd.DataFrame({
        "customer_id": df[mapping["customer_id"]].astype(str).str.strip(),
        "order_id": df[mapping["order_id"]].astype(str).str.strip(),
    })

    raw_dates = df[mapping["order_date"]]
    dates = pd.to_datetime(raw_dates, errors="coerce")
    bad_dates = dates.isna() & raw_dates.notna() & (raw_dates.astype(str).str.strip() != "")
    if len(df) and bad_dates.mean() > _FAIL_FRACTION:
        errors.append(
            f"{int(bad_dates.sum())} value(s) in the date column "
            f"'{mapping['order_date']}' could not be read as dates.")
    orders["order_date"] = dates

    raw_amt = df[mapping["order_amount"]]
    amt = _clean_amount(raw_amt)
    bad_amt = amt.isna() & raw_amt.notna() & (raw_amt.astype(str).str.strip() != "")
    if len(df) and bad_amt.mean() > _FAIL_FRACTION:
        errors.append(
            f"{int(bad_amt.sum())} value(s) in the amount column "
            f"'{mapping['order_amount']}' are not numeric.")
    negatives = (amt < 0)
    if negatives.any():
        warnings.append(
            f"{int(negatives.sum())} negative amount(s) were clipped to 0 "
            f"(likely returns/refunds).")
        amt = amt.clip(lower=0)
    orders["order_amount"] = amt

    orders["customer_id"] = orders["customer_id"].replace("", None)
    orders["order_id"] = orders["order_id"].replace("", None)

    if errors:
        return ValidationResult(False, errors, warnings)

    orders = orders.dropna(subset=REQUIRED).reset_index(drop=True)
    if len(orders) == 0:
        return ValidationResult(
            False,
            ["No rows survived validation — every row was missing a required "
             "customer, order, date, or amount value."],
            warnings)

    items = None
    if mapping.get("product") or mapping.get("category"):
        items = pd.DataFrame({"order_id": df[mapping["order_id"]].astype(str).str.strip()})
        items["product"] = (df[mapping["product"]] if mapping.get("product")
                            else None)
        items["category"] = (df[mapping["category"]] if mapping.get("category")
                             else None)
        if mapping.get("quantity"):
            items["quantity"] = _clean_amount(df[mapping["quantity"]]).fillna(1)
        else:
            items["quantity"] = 1
        items = items[items["order_id"].isin(orders["order_id"])].reset_index(drop=True)

    return ValidationResult(True, [], warnings, orders, items)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: PASS — check count rises by ~20.

- [ ] **Step 5: Commit**

```bash
git add src/data/ingest/validator.py tests/test_ingest.py
git commit -m "feat(ingest): validator firewall — clean coercion + human error messages"
```

---

## Task 6: Builder — validate → canonical → FeatureMatrix

**Files:**
- Create: `src/data/ingest/builder.py`
- Test: `tests/test_ingest.py` (append)

- [ ] **Step 1: Add the failing test**

Append and register under `__main__`:

```python
def test_build_canonical_full():
    from src.data.ingest.builder import build_canonical
    df = _good_df()
    df["prod"] = ["milk", "eggs", "soda"]; df["dept"] = ["dairy", "dairy", "drinks"]
    m = dict(_GOOD_MAP, product="prod", category="dept")
    res = build_canonical(df, m)
    check("build ok", res["ok"] is True)
    check("orders returned", res["orders"] is not None)
    check("matrix returned", res["matrix"] is not None)
    check("optional features available on rich upload",
          res["matrix"].is_available("avg_basket_size"))
    check("core features available",
          res["matrix"].is_available("monetary"))


def test_build_canonical_orders_only():
    from src.data.ingest.builder import build_canonical
    res = build_canonical(_good_df(), _GOOD_MAP)
    check("orders-only ok", res["ok"] is True)
    check("optional tagged unavailable",
          res["matrix"].is_available("reorder_rate") is False)
    check("core still available", res["matrix"].is_available("recency_days"))


def test_build_canonical_dedups_orders():
    from src.data.ingest.builder import build_canonical
    # order 100 appears twice (two line rows); amount is the order total repeated.
    df = pd.DataFrame({
        "cust": ["1", "1"], "ord": ["100", "100"],
        "when": ["2024-01-02", "2024-01-02"], "amt": ["50", "50"]})
    res = build_canonical(df, _GOOD_MAP)
    check("duplicate order rows collapsed", len(res["orders"]) == 1)
    check("monetary not double-counted",
          float(res["matrix"].frame["monetary"].iloc[0]) == 50.0)


def test_build_canonical_rejects_bad():
    from src.data.ingest.builder import build_canonical
    res = build_canonical(_good_df(), dict(_GOOD_MAP, customer_id=None))
    check("bad mapping surfaces not-ok", res["ok"] is False)
    check("errors passed through", len(res["errors"]) > 0)
    check("no matrix on failure", res["matrix"] is None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: FAIL — `No module named 'src.data.ingest.builder'`.

- [ ] **Step 3: Write `src/data/ingest/builder.py`**

```python
"""
Builder: assemble validated data into canonical tables + a FeatureMatrix.

Runs the validator, then (on success) de-duplicates `orders` on order_id and
hands the canonical tables to Phase 1's `build_feature_matrix`. Returns a plain
dict so the (later) UI layer can render success, warnings, or a clean error list
without catching exceptions.

Assumption: the uploaded file is order-grained for `orders` — a logical order may
appear on several line rows, so `order_amount` is read as an order TOTAL repeated
across those rows (kept once via drop_duplicates), NOT summed per line. Line-level
detail flows into `order_items` when product/category columns are mapped.
"""

from src.data.ingest.validator import validate


def build_canonical(df, mapping) -> dict:
    """Validate + build. Returns {ok, errors, warnings, orders, order_items,
    matrix}; matrix/orders are None when validation fails."""
    result = validate(df, mapping)
    if not result.ok:
        return {"ok": False, "errors": result.errors, "warnings": result.warnings,
                "orders": None, "order_items": None, "matrix": None}

    from src.data.canonical import build_feature_matrix

    orders = result.orders.drop_duplicates("order_id").reset_index(drop=True)
    matrix = build_feature_matrix(orders, result.order_items)
    return {"ok": True, "errors": [], "warnings": result.warnings,
            "orders": orders, "order_items": result.order_items, "matrix": matrix}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: PASS — check count rises by ~13.

- [ ] **Step 5: Commit**

```bash
git add src/data/ingest/builder.py tests/test_ingest.py
git commit -m "feat(ingest): builder assembles validated upload into canonical + FeatureMatrix"
```

---

## Task 7: Mapping persistence (recipe + fingerprint, never raw rows)

**Files:**
- Create: `src/data/ingest/mapping_store.py`
- Test: `tests/test_mapping_persist.py`

- [ ] **Step 1: Write the failing test**

```python
"""Standalone tests for src/data/ingest/mapping_store.py. No network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def test_fingerprint_order_insensitive():
    from src.data.ingest.mapping_store import fingerprint
    a = fingerprint(["Cust", "Order", "Amt"])
    b = fingerprint(["amt", "  order ", "CUST"])
    check("fingerprint ignores order/case/space", a == b)
    c = fingerprint(["Cust", "Order", "Amt", "Extra"])
    check("different shape -> different fingerprint", a != c)


def test_save_load_roundtrip(tmpdir):
    from src.data.ingest.mapping_store import save_mapping, load_mapping
    path = os.path.join(tmpdir, "mappings.json")
    headers = ["Cust Ref", "Order No", "When", "Total"]
    mapping = {"customer_id": "Cust Ref", "order_id": "Order No",
               "order_date": "When", "order_amount": "Total"}
    save_mapping(headers, mapping, path=path)
    got = load_mapping(headers, path=path)
    check("saved mapping loads back", got == mapping)
    check("same shape re-upload hits", load_mapping(["total", "when", "order no", "cust ref"], path=path) == mapping)
    check("different shape misses", load_mapping(["a", "b"], path=path) is None)


def test_store_never_holds_rows(tmpdir):
    from src.data.ingest.mapping_store import save_mapping
    path = os.path.join(tmpdir, "mappings.json")
    save_mapping(["Cust", "Amt"], {"customer_id": "Cust"}, path=path)
    with open(path) as f:
        blob = f.read()
    check("only mapping recipe persisted, no obvious PII keys",
          "row" not in blob.lower() and "value" not in blob.lower())


def test_missing_store_returns_none():
    from src.data.ingest.mapping_store import load_mapping
    check("absent store -> None", load_mapping(["x"], path="does/not/exist.json") is None)


if __name__ == "__main__":
    import tempfile
    test_fingerprint_order_insensitive()
    with tempfile.TemporaryDirectory() as d:
        test_save_load_roundtrip(d)
        test_store_never_holds_rows(d)
    test_missing_store_returns_none()
    print(f"\n{_passed} checks passed.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_mapping_persist.py`
Expected: FAIL — `No module named 'src.data.ingest.mapping_store'`.

- [ ] **Step 3: Write `src/data/ingest/mapping_store.py`**

```python
"""
Mapping persistence — recipe only, never raw rows.

Saves the confirmed column-mapping recipe keyed by a dataset FINGERPRINT (a hash
of the sorted, normalised header set). On re-upload of a same-shaped file the app
can auto-apply the saved mapping and skip the LLM/confirm step. No customer data
is ever written — only headers (hashed) and the field->column recipe. Best-effort
JSON store like the other `.app_state/*.json` stores: never raises.
"""

import hashlib
import json
import os

_STORE = os.path.join(".app_state", "mappings.json")


def fingerprint(headers) -> str:
    """Stable 16-char hash of the normalised (sorted, lowercased, trimmed) header
    set — order/case/whitespace insensitive."""
    joined = "|".join(sorted(str(h).strip().lower() for h in headers))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:16]


def _load_all(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_mapping(headers, mapping: dict, path: str = _STORE) -> str:
    """Persist `mapping` under this header set's fingerprint. Returns the
    fingerprint. Best-effort: swallows any I/O error."""
    fp = fingerprint(headers)
    data = _load_all(path)
    data[fp] = {"mapping": mapping}
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_mapping_persist.py`
Expected: PASS — `9 checks passed.`

- [ ] **Step 5: Commit**

```bash
git add src/data/ingest/mapping_store.py tests/test_mapping_persist.py
git commit -m "feat(ingest): persist mapping recipe by header fingerprint (no raw rows)"
```

---

## Task 8: Full-suite regression + journal

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run the new suites**

Run: `..\venv\Scripts\python.exe tests/test_ingest.py`
Expected: PASS — all checks pass.

Run: `..\venv\Scripts\python.exe tests/test_mapping_persist.py`
Expected: PASS — `9 checks passed.`

- [ ] **Step 2: Run the existing canonical/demo suites (must stay green)**

Run: `..\venv\Scripts\python.exe tests/test_canonical.py`
Expected: PASS — 52 checks.

Run: `..\venv\Scripts\python.exe tests/test_demo_adapter.py`
Expected: PASS — 40 checks.

- [ ] **Step 3: Add the Project Journal entry**

Add this entry at the TOP of the `## 📓 Project Journal` section in `CLAUDE.md` (newest first):

```markdown
### 2026-07-03 — Intelligence Layer, Phase 3: Ingestion pipeline
Built the upload path + malfunction firewall so a client's own CSV/Excel becomes
canonical data (spec §3; plan: docs/superpowers/plans/2026-07-03-ingestion-pipeline.md).
New package `src/data/ingest/` (all pure / Streamlit-free):
- **`reader.py`** — CSV/Excel → all-string DataFrame; sniffs encoding (BOM +
  utf-8/16 fallbacks) and delimiter.
- **`profiler.py`** — per-column profile (guessed kind, samples, %null, %unique);
  the ONLY thing the mapper sends to the LLM — never raw rows (cheap + no PII).
- **`mapper.py`** — `propose_mapping` (injected `generate_fn`; drops hallucinated
  headers) with a deterministic `fuzzy_map` fallback so mapping works with zero LLM.
- **`validator.py`** — the firewall: strips `$`/commas, coerces amounts (negatives
  clipped + warned), parses dates, drops rows missing required fields; returns
  human messages, never a stack trace.
- **`builder.py`** — validate → dedupe orders on order_id → Phase-1
  `build_feature_matrix`; returns a plain result dict (ok/errors/warnings/…).
- **`mapping_store.py`** — persist the mapping recipe keyed by a header fingerprint
  (`.app_state/mappings.json`); same-shaped re-upload reuses it. No raw rows at rest.
- Scope (narrow): pure pipeline + persistence + tests only. The Streamlit confirm
  screen, upload UI, and app wiring are Phase 4 integration — app.py untouched.
- Tests: `tests/test_ingest.py` (reader/profiler/mapper/validator/builder — the
  firewall contract) + `tests/test_mapping_persist.py`. No network. Existing
  canonical (52) + demo-adapter (40) suites still green.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: journal Phase 3 ingestion pipeline"
```

---

## Self-Review (completed by plan author)

**Spec coverage (§3 + persistence):**
- reader ✅ Task 1 · profiler ✅ Task 2 · mapper (LLM + fuzzy fallback) ✅ Tasks 3–4 · validator firewall ✅ Task 5 · builder ✅ Task 6 · mapping persistence (recipe + fingerprint) ✅ Task 7.
- `test_ingest.py` firewall cases (missing required, bad dates, `$`/comma/negative amounts, empty file, multi-line→items) ✅ Task 5–6. `test_mapping_persist.py` fingerprint round-trip ✅ Task 7.
- **Deliberately deferred (documented, not gaps):** UI confirm screen (spec §3 stage 4), Excel multi-sheet selection UI, upload wiring into `app.py`/session_state, and canonical-artifact rebuild — all Phase 4 integration per the approved narrow scope. `DD/MM/YYYY` day-first handling is covered by pandas' parser in the validator; an explicit day-first locale toggle is a Phase 4 confirm-screen concern.

**Placeholder scan:** none — every code step contains full source; every test step contains real assertions.

**Type consistency:** `propose_mapping` returns `{mapping, source}`; `fuzzy_map`/`_parse_llm_mapping` return a `{field: header|None}` dict; `validate` returns `ValidationResult(ok, errors, warnings, orders, order_items)`; `build_canonical` returns `{ok, errors, warnings, orders, order_items, matrix}`. `CANONICAL_FIELDS` keys match the canonical `orders`/`order_items` columns from `src/data/canonical.py`. Consistent across all tasks.
