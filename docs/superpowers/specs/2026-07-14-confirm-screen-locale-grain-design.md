# Confirm-Screen Locale & Grain Controls — Design

**Date:** 2026-07-14
**Status:** Approved (brainstorm) — ready for implementation plan
**Builds on:** `2026-07-14-byod-validation-hardening-design.md` (date-locale inference
and per-order amount collapse now live in the ingestion firewall).

## Motivation

The BYOD validation hardening pass made the ingestion firewall *infer* the date
locale (day-first vs month-first) and *collapse* order grain (sum line prices per
order) correctly. But both decisions happen **inside `build_canonical`, after the
operator clicks Confirm**, and surface only as post-hoc warnings once analysis has
already run. For a client-facing tool, the operator should **see and steer** the two
decisions that most affect revenue and churn correctness *before* anything computes.

The auto-rules are correct for the common export shapes, but each has a residual
case the operator alone can resolve:
- **Locale:** a column where every date component is ≤12 is genuinely ambiguous;
  the firewall defaults to day-first, but only the operator knows the true locale.
- **Grain:** a line-item file whose lines within an order happen to cost the same
  (2 items @ $25 → true order total $50) is indistinguishable from a repeated
  order total by the auto-rule, which would keep $25. Only the operator knows.

## Approach (chosen: A — explicit overrides threaded through the pure backend)

The confirm screen computes detection live and passes the operator's choice down as
explicit override arguments. Backend override params default to `None` (= current
auto behavior, fully backward-compatible). Detection helpers are **pure** and reused
for both the on-screen display and the auto path, so "what we show" and "what we do"
can never drift.

Rejected: **B** — confirm screen pre-transforms the data before `build_canonical`
(duplicates coercion outside the validator, violating "coercion lives ONLY in the
validator"). **C** — stash overrides in `session_state` for the builder to read
(hidden coupling; pure functions should take explicit args).

## Components

### 1. Backend override params (pure)

**`src/data/ingest/validator.py`** — `validate(df, mapping, dayfirst=None)`:
- `dayfirst=None` → infer via existing `_infer_dayfirst` (unchanged behavior,
  including the ambiguity warning).
- `dayfirst=True`/`False` → force that locale; skip inference; **no** ambiguity
  warning (the operator decided).

**`src/data/ingest/builder.py`**:
- `build_canonical(df, mapping, dayfirst=None, grain=None)`:
  - `dayfirst` passed straight to `validate`.
  - `grain=None` → current auto rule (`_collapse_amount`: identical per-order
    amounts kept once, differing summed).
  - `grain="line_item"` → **always sum** per order (even identical amounts). Warn:
    "N order(s) had their line amounts summed to an order total (line-item file)."
  - `grain="order_level"` → **one row per order, keep first** amount. If any order
    had differing amounts (values discarded), warn: "N order(s) had multiple
    differing amounts; the first was kept (order-level file). If this is a
    line-item export, choose 'Line-item' instead."
- New pure `detect_grain(df, mapping) -> "line_item" | "order_level"`: coerce the
  mapped amount column via the validator's `_clean_amount`, group by the raw mapped
  `order_id` column (as strings), return `"line_item"` if any order has more than
  one distinct non-null amount, else `"order_level"`. Mirrors the auto-rule so the
  displayed detection matches what an Auto build will do. Returns `"order_level"`
  when the amount or order_id column is unmapped/absent (nothing to detect).

**`src/ui/upload.py`** — `apply_mapping(df, mapping, dayfirst=None, grain=None)`
threads both to `build_canonical`.

### 2. Confirm-screen controls (`render_confirm_gate`)

Rendered after the per-field dropdowns + preview, before the Confirm/Cancel row.
Both controls key off the **currently chosen** columns (Streamlit reruns on any
selectbox change, so detection recomputes each render):

- **Date format** — `st.radio` with options:
  - `Auto (detected: <Day-first DD/MM/YYYY | Month-first MM/DD/YYYY>)`
  - `Day-first (DD/MM/YYYY)`
  - `Month-first (MM/DD/YYYY)`
  Detection: `_infer_dayfirst(df[chosen["order_date"]])`. When ambiguous, the Auto
  label reads `Auto (ambiguous — assuming Day-first)`. Session key
  `date_locale_choice`.
- **Order grain** — `st.radio` with options:
  - `Auto (detected: <line-item — lines will be summed | order-level>)`
  - `Line-item — sum lines per order`
  - `Order-level — one row per order`
  Detection: `detect_grain(df, chosen)`. Session key `order_grain_choice`.

On **Confirm**, translate the two radio selections to overrides:
- Date: `Auto → None`, `Day-first → True`, `Month-first → False`.
- Grain: `Auto → None`, `Line-item → "line_item"`, `Order-level → "order_level"`.
Pass both to `_build_and_activate(fname, df, chosen, run_analysis, dayfirst=…,
grain=…)` → `apply_mapping`.

Both new session keys (`date_locale_choice`, `order_grain_choice`) are added to
`_UPLOAD_KEYS` so `_clear_upload_state` drops them on Confirm-success / Cancel /
Back-to-demo / new-file, exactly like the `map_*` selectbox keys — so a second
upload never inherits the first file's locale/grain choice.

### 3. Data flow

Uploader → `prepare_upload` (unchanged) → confirm screen renders dropdowns +
**live detection** of locale & grain → operator adjusts columns and/or overrides →
Confirm → `_build_and_activate` → `apply_mapping(df, mapping, dayfirst, grain)` →
`build_canonical` → `validate(dayfirst)` + grain-aware collapse → active dataset +
analysis. The saved-mapping fast path (`stage == "build"`) still uses Auto/`None`
for both (a saved recipe carries only the column mapping, not locale/grain — a
deliberate non-goal; a fast-pathed file gets the correct auto behavior and its
post-hoc warning).

### 4. Error handling

Detection helpers never raise: `_infer_dayfirst` already tolerates any strings;
`detect_grain` wraps its coercion so a weird amount column falls back to
`"order_level"` (the safe, non-summing default) rather than crashing the confirm
screen. The confirm gate is best-effort UI — a detection failure degrades to the
Auto option preselected, never a traceback.

### 5. Testing

- **`tests/test_ingest.py`** (standalone-script style, `check(name, cond)`):
  - `validate` with `dayfirst=False` forces month-first on an AU-looking
    `13`-free column; `dayfirst=True` forces day-first; and a forced choice emits
    **no** ambiguity warning.
  - `build_canonical` with `grain="line_item"` sums identical per-order lines
    (2×$25 → $50) and warns; with `grain="order_level"` keeps the first of
    differing amounts and warns; `grain=None` unchanged from the hardening pass.
  - `detect_grain` returns `"line_item"` for a differing-amount order, `"order_level"`
    for identical/one-row orders, and `"order_level"` when amount/order_id unmapped.
- **`tests/test_upload_flow.py`**:
  - pure `apply_mapping(..., dayfirst=…, grain=…)` honors both overrides (fake
    `generate_fn`, no network).
  - AppTest seeding `session_state["upload_stage"]="confirm"` + a small `upload_df`
    asserts both radios render with the Auto option present and the detected label.

## Out of scope (unchanged)

Multi-currency detection/normalization; per-line customer/date conflict handling
within one order id; persisting the locale/grain choice into the saved mapping
recipe (fast-path stays Auto).
