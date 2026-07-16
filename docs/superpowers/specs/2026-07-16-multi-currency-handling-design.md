# Multi-Currency Handling — Design Spec

**Date:** 2026-07-16
**Status:** Approved (brainstorm complete; ready for implementation planning)
**Depends on:** the BYOD ingestion pipeline (`src/data/ingest/`), the canonical
data model (`src/data/canonical.py`), and the upload/confirm UI (`src/ui/upload.py`).
This is a post-roadmap **depth** thread, in the same family as the two prior
depth passes (date-locale inference, line-item revenue collapse) — make the
*inputs* correct so the grounded chat agent can never be confidently wrong.

## 1. Why

The chat-first agent's core promise is *"grounded — it computes real numbers over
the client's real data and never fabricates a figure."* The single most important
business number is `monetary` (the M in RFM): it drives power-user scoring, every
"who are my best customers" answer, the grounded-query tool, exports, and the
proactive briefing.

Today `order_amount` is one numeric column. `validator._clean_amount` strips **all**
non-numeric characters — including any currency symbol — so `$10`, `€10`, and `A$10`
all collapse to `10`. There is **no currency concept anywhere** in the pipeline. A
real client whose export mixes AUD / USD / NZD therefore gets a **silently-wrong
mixed-currency sum** for `monetary` and `avg_order_value`, corrupting every
downstream figure the agent reports. This is precisely the silent-wrong-number
failure mode the depth passes exist to eliminate.

**Driver:** a concrete real client (an Australian e-commerce brand) has orders in
multiple currencies and needs correct consolidation — not just labeling.

## 2. Locked decisions

- **Currency source:** a **dedicated currency column** (e.g. Shopify/WooCommerce
  `Currency` = `USD`/`AUD`/`NZD`). Modeled as a new **optional** canonical field
  `order_currency`.
- **Rates:** **operator-entered flat per-currency rates** on the confirm screen;
  the reporting currency's rate is locked at `1.0`. Offline, no network, no
  fabricated figure — the operator owns every rate (identical trust posture to the
  existing date-locale / grain overrides). Flat rates, **not** per-order-date
  historical rates.
- **Trust gate:** when 2+ currencies are detected, **analysis is blocked** until
  every non-base currency has a rate. No silently-mixed sum can ever escape.
- **Architecture:** convert **inside the validator** (Approach A) — the validator
  docstring already states *"Coercion is deterministic and lives ONLY here"*, and
  currency conversion is amount coercion. Heavier logic extracted into a new pure
  `src/data/ingest/currency.py`.

Rejected: converting in the builder (splits amount handling, breaks the
one-place-coerces invariant); converting in the UI layer (business logic in
Streamlit, untestable, bypasses the numeric firewall); live/historical FX APIs
(network in the ingest path, injects an externally-fetched/approximate number into
the monetary core, conflicts with the trust invariant).

## 3. Canonical model change

`mapper.CANONICAL_FIELDS` gains one **optional** field:

```
order_currency: required=False,
  aliases=["currency", "curr", "ccy", "iso_currency", "currency_code"]
```

A single-currency file simply leaves it unmapped and behaves exactly as today.

Crucially, **nothing is added to the `orders` or `order_items` canonical tables.**
Currency is a *processing input* consumed entirely during validation to produce an
already-converted `order_amount`. After conversion, canonical `orders` keeps its
current 4-column shape (`customer_id, order_id, order_date, order_amount`), now
guaranteed single-currency (the reporting currency). `canonical.py` and every
downstream consumer stay **untouched**.

The chosen **reporting currency** (a string like `"AUD"`) rides alongside as
metadata — returned by validator/builder, stored in session + the mapping recipe —
so surfaces can *label* monetary figures. It is never a data column.

## 4. New module — `src/data/ingest/currency.py`

Pure (no Streamlit, no network), unit-testable in isolation. Four functions:

- **`normalize_currency(raw) -> str | None`** — one raw cell → canonical uppercase
  code. Handles ISO codes (`"usd"`, `" AUD "` → `"USD"`/`"AUD"`) and common symbols
  (`"$"`, `"€"`, `"£"`, `"A$"`, `"US$"`, `"NZ$"`). A bare `"$"` is genuinely
  ambiguous (USD/AUD/NZD/CAD) → normalizes to a sentinel `"$?"` the UI surfaces for
  operator resolution rather than guessing. Blank/unrecognized → `None`.
- **`detect_currencies(df, mapping) -> list[str]`** — pure; mirrors `detect_grain`.
  Sorted distinct normalized currencies in the mapped column (`[]` if
  unmapped/absent). Never raises. This is what the confirm screen reads to build the
  rate form.
- **`convert_amounts(amounts, currencies, rates) -> Series`** — `amounts *
  currencies.map(rates)`. `rates` is e.g. `{"AUD": 1.0, "USD": 1.53, "NZD": 1.09}`
  (base = 1.0). A currency with no rate entry → `NaN` (validator treats those as
  unconvertible rows). Vectorized for 200k-row scale.
- **`currency_label(code) -> str`** — display helper (`"AUD"` → `"A$"`/`"AUD"`);
  small static map, falls back to the raw code.

Detection and conversion are separate so the UI can detect (to build the rate form)
before any rate exists. The module is provenance-agnostic — it applies whatever
rate dict it is handed.

## 5. Validator wiring (`src/data/ingest/validator.py`)

Two optional params, both `None`-default so existing callers and single-currency
files are byte-for-byte unchanged:

```python
def validate(df, mapping, dayfirst=None, reporting_currency=None, rates=None):
```

Flow, added right after the existing `_clean_amount` step (keeps all amount
coercion in one place):

1. **No currency column mapped** → skip everything below; behaves exactly as today.
   `reporting_currency` may still be carried purely as a display label.
2. **Currency column mapped** → normalize via `normalize_currency`, get distinct
   codes via `detect_currencies`:
   - **One distinct currency** → no conversion (rate 1.0); record it as the
     reporting-currency label. No gate.
   - **Multiple currencies** → gated path:
     - `rates` is `None` or missing an entry for any non-base detected currency →
       **hard error** (not a warning): *"This file contains N currencies (AUD, USD,
       NZD). Enter a conversion rate for each on the confirm screen before analysis
       can run."* Returns `ok=False`. **This is the trust gate.**
     - `rates` covers every detected currency → `convert_amounts` multiplies each
       row into the reporting currency. A row still `NaN` (unknown/ambiguous `"$?"`,
       or blank currency) is counted against the existing `_FAIL_FRACTION`
       bad-amount check → clean rejection if >10%, else drops with a warning.
3. Converted amounts flow into `orders["order_amount"]` exactly as before. The
   existing negative-clip and comma-decimal heuristics run on the **converted**
   values (correct — they operate on final reporting-currency amounts, and are
   currency-agnostic).

`ValidationResult` gains a `reporting_currency` field (default `None`) so the
builder/UI can read it.

## 6. Builder threading (`src/data/ingest/builder.py`)

`build_canonical` threads the two params straight to `validate`, matching how
`dayfirst`/`grain` are already threaded:

```python
def build_canonical(df, mapping, dayfirst=None, grain=None,
                    reporting_currency=None, rates=None):
    result = validate(df, mapping, dayfirst=dayfirst,
                      reporting_currency=reporting_currency, rates=rates)
```

The collapse logic (`_collapse_amount`, grain handling) is **unchanged** — by the
time it runs, amounts are already single-currency, so summing lines / keeping order
totals is correct exactly as today. No currency↔grain interaction.

The returned dict gains `reporting_currency` (read off `ValidationResult`).
`upload.apply_mapping` (pure) forwards `reporting_currency` + `rates` to
`build_canonical`, mirroring the existing `dayfirst`/`grain` forwarding.

## 7. Confirm-screen UI (`src/ui/upload.py` → `render_confirm_gate`)

Rendered after the existing column dropdowns / date-locale / grain controls.

- **No currency column mapped** → nothing new renders. (`order_currency` is in the
  mapping dropdowns as an optional field; the operator maps it there if present.)
- **Currency column mapped** → call `detect_currencies` live on the current
  selection and render a **"💱 Currencies"** block:
  - **One currency detected** → caption only: *"All orders are in AUD. No conversion
    needed."* No inputs, no gate.
  - **Multiple detected** → gated control:
    - A **reporting-currency** `st.selectbox`, defaulted to the **most frequent**
      detected currency (natural base for an AU brand). Its rate locks at `1.0`.
    - One `st.number_input` **per other detected currency** ("1 USD = ___ AUD"),
      defaulting to unset (blank/`0.0`).
    - Any `"$?"` ambiguous symbol shown with a note asking the operator to confirm
      which currency it is; unresolved `"$?"` rows drop as unconvertible.
    - A live caption showing the order count per currency so the operator sees the
      stakes.
- **The gate:** the **Confirm** button is disabled until every non-base currency has
  a rate > 0 (soft UI gate), **and** the validator returns `ok=False` otherwise
  (authoritative gate — even a programmatic path can't bypass it).
- On Confirm, selections translate to `reporting_currency` (string) + `rates`
  (dict, base=1.0) → `_build_and_activate` → `apply_mapping`.
- **Session-state hygiene:** new keys (`reporting_currency_choice`, per-currency
  `rate_<CODE>` inputs) added to `_UPLOAD_KEYS` cleanup, so a second upload never
  inherits the first file's currencies/rates (the exact bug class the locale/grain
  pass had to fix).

## 8. Persistence (mapping recipe)

The confirmed reporting currency + rate dict are saved into the existing mapping
recipe (`.app_state/mappings.json`, keyed by header fingerprint), alongside the
column mapping and the locale/grain choices already stored there.

- Same-shaped re-upload fast-path replays the **stored** `reporting_currency` +
  `rates`, skipping the manual gate.
- **Safety backstop:** if the incoming file contains a currency the stored rates
  don't cover, the fast path cannot reuse stale rates — the validator's Section-5
  hard error fires and the operator is dropped back into the full confirm gate to
  set the missing rate.
- Existing store guarantees hold: **no raw rows at rest**, best-effort JSON,
  tolerant of a corrupt/old store. A pre-currency recipe simply has no rates key →
  treated as single-currency (unchanged behavior).

## 9. Displaying the reporting currency

Consolidation is the core deliverable; labeling is the cheap, high-trust finish that
stops the agent from reading out bare ambiguous numbers. Deliberately minimal:

- The active `reporting_currency` is stored in `session_state` (set via the
  dataset-swap seam, where `dataset_label` lives). Defaults to `None` for the demo /
  single-currency-unlabeled case → surfaces fall back to today's bare-number
  behavior (no regression).
- **Where it shows** (money surfaces only, via `currency_label`):
  - **Grounded-query tool** — when a scalar/aggregate is over `monetary` or
    `avg_order_value`, the rendered metric card and the "narrate ONLY these numbers"
    instruction carry the currency (e.g. `"A$1,240"`), so the **chat agent** speaks
    the figure with its currency instead of a naked number. *This is the one spot
    that touches the agent surface — it makes the agent's spoken numbers correct.*
  - **CSV export** — the loyalty/monetary column header gets a `(AUD)` suffix.
  - **Summary report** — monetary lines get the currency label.
- **Out of scope (YAGNI):** no per-figure currency formatting everywhere, no
  locale-aware thousands/decimal formatting, no symbol on every chart axis. Just the
  reporting-currency code/symbol on the monetary headline figures. The agent gains
  no *capability* here — its numbers just gain a currency.

## 10. Testing

Following repo patterns (pure-module unit tests + AppTest for UI):

- **`tests/test_currency.py` (NEW)** — the module contract on hand-computable
  fixtures: `normalize_currency` (ISO case/whitespace, symbols, `"$?"` sentinel,
  garbage → `None`), `detect_currencies` (distinct sorted; unmapped → `[]`; never
  raises), `convert_amounts` (multiplication, base=1.0 passthrough, missing-rate →
  `NaN`), `currency_label`.
- **`tests/test_ingest.py` (EXTENDED)** — `test_validate_multi_currency_gated`
  (2+ currencies, no/partial rates → `ok=False` + human message; single currency →
  no gate + correct label); `test_validate_currency_conversion` (mixed file + full
  rates → `monetary`/`order_amount` hand-computed, e.g. 10 USD @1.53 + 10 AUD →
  25.30 AUD); `test_multi_currency_end_to_end` (messy AU export: AUD+USD+NZD, mixed
  symbols/codes → validator→builder→FeatureMatrix, every RFM figure hand-computed in
  AUD, mirroring `test_au_shopify_export_end_to_end`); a regression assert that a
  **no-currency-column** file is byte-for-byte unchanged.
- **`tests/test_upload_flow.py` (EXTENDED)** — `apply_mapping` forwards
  `reporting_currency`/`rates` (pure); AppTest asserts the confirm gate renders rate
  inputs and blocks Confirm until rates are set.
- **`tests/test_mapping_persist.py` (EXTENDED)** — recipe round-trips reporting
  currency + rates; a pre-currency recipe loads as single-currency; a
  new-currency-on-replay falls back to the gate.
- **Runtime verification** (per the CSV-export lesson — "run the real full app after
  BYOD changes"): drive `app.py` through a multi-currency upload → confirm → analyze
  with 0 exceptions, confirming the chat/grounded-query path speaks a
  currency-labeled monetary figure.

## 11. Out of scope

- Per-order-date historical FX rates; live FX APIs; any network in the ingest path.
- Currencies embedded in the amount cell as the primary source (a dedicated column
  is the confirmed shape). `normalize_currency` still recognizes symbols, so an
  embedded-symbol currency column degrades gracefully, but the amount-embedded case
  is not a first-class path.
- Per-storefront/per-file single-currency merges.
- Multi-currency *display* everywhere; only the monetary headline figures are
  labeled.
- The other remaining depth thread — per-line customer/date conflict handling — is
  separate and unaffected.
