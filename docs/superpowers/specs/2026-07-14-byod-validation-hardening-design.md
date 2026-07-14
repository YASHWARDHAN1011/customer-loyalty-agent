# BYOD Validation Hardening — Design

**Date:** 2026-07-14
**Status:** Approved (brainstorm) — ready for implementation plan
**Scope:** Two silent-wrong-number correctness bugs in the ingestion firewall,
plus a realistic Australian e-commerce fixture that exercises the whole pipeline.

## Motivation

The chat-first BYOD roadmap (Phases 4→9) is complete and the tool's core promise
is "never fabricate a number." But green tests are not the same as trustworthy on
a client's real data. This project is a live internship deliverable running an
Australian e-commerce brand's own exports. Two probes against the ingestion
validator confirmed real correctness bugs that produce **wrong numbers without
crashing or warning** — the worst failure mode for a grounded tool:

1. **Date-locale bug.** `03/04/2025` (3 April in Australia) is parsed as **March
   4** — `pd.to_datetime` defaults to month-first. Every order date on a real AU
   file silently shifts, corrupting recency, tenure, avg-gap and churn (the entire
   RFM core).

   Evidence: `validate()` on `["03/04/2025","05/06/2025"]` produced
   `2025-03-04`, `2025-05-06`.

2. **Line-item revenue collapse.** A Shopify/WooCommerce export is line-grained:
   one order spans several rows, each with its own line price (30 + 45 + 25 = $100
   order). The validator kept all three rows with amounts `[30, 45, 25]`, and the
   builder then dedupes on `order_id` keeping the first → the order records **$30
   instead of $100**. Revenue, monetary value and AOV all silently under-count.

   Evidence: a 3-line order (`30/45/25`) yielded `order_amount` `[30, 45, 25]`
   with no warning; builder `drop_duplicates` keeps `30`.

## Approach (chosen: A — deterministic auto-correct + honest warnings)

Let the evidence in the data decide. Auto-correct where the data is decisive;
warn (never silently guess) only where it is genuinely ambiguous. No blind
`dayfirst=True` (that mirrors the bug onto US clients); no always-sum (that
double-counts repeated-total files). No confirm-screen UI or config — out of scope.

## Components

### 1. Date-locale inference — `src/data/ingest/validator.py`

Add `_parse_dates(raw_series) -> (parsed_series, warnings)` and call it in place of
the current bare `pd.to_datetime(raw_dates, errors="coerce")`.

- Consider only values matching the ambiguous numeric pattern
  `^\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*$`. ISO `YYYY-MM-DD` and text-month formats
  are unambiguous and left to pandas.
- **Evidence rule**, over the ambiguous values:
  - any **first** component in `13..31` ⇒ `dayfirst=True`;
  - else any **second** component in `13..31` ⇒ `dayfirst=False`;
  - else (every component ≤ 12) ⇒ **truly ambiguous** ⇒ default `dayfirst=True`
    and append a warning naming the column and instructing the operator to verify.
- Parse the entire column once with the inferred `dayfirst`.
- The existing >10% (`_FAIL_FRACTION`) unparseable-date rejection is unchanged and
  runs on the inference-parsed result.

**Ambiguous-case default = day-first.** The deployment client is Australian, and
any real multi-order file almost always contains a day > 12 that resolves the
locale decisively before the default is ever reached. The warning is the true
safeguard in the rare all-≤12 case.

### 2. Order-grain collapse — `src/data/ingest/builder.py`

Replace `result.orders.drop_duplicates("order_id")` with a per-order aggregation:

- Group by `order_id` (`sort=False`, preserve first-seen order). Per order:
  - `order_amount`: if `nunique() == 1` ⇒ keep that single value (repeated order
    total); if it differs ⇒ **sum** (line prices).
  - `customer_id`, `order_date`: `first`.
- Correct for all three real shapes with no double-counting:
  - one-row-per-order → group of 1 → sum == the value (unchanged);
  - repeated-total line file → identical amounts → kept once (not summed);
  - true line-item file → differing amounts → summed to the order total.
- Replace the current misleading warning ("the first amount per order id is used,
  so revenue totals may be off") with an accurate one: "N order(s) spanned
  multiple line amounts and were summed to an order total. Verify the amount
  column mapping." Only emitted when at least one order was summed.
- Update the `builder.py` and `validator.py` module docstrings: the "amount is a
  repeated order total, kept once via drop_duplicates" assumption is exactly what
  this change corrects.

`build_feature_matrix` still receives clean, order-grained, deduped `orders`, so
downstream is unchanged.

### 3. Realistic AU fixture + tests — `tests/test_ingest.py`

A hand-built in-memory export mirroring a real Shopify/WooCommerce AU dump:
`DD/MM/YYYY` dates, `$` symbols with thousands commas, at least one parenthesised
refund, and **multi-line orders** (one order across several line rows with distinct
line prices). Assertions follow the repo's standalone script style (print each
check; `sys.exit(1)` on any failure):

- A `13/06/2025`-style date resolves to **13 June 2025** (day > 12 forces
  day-first) — not swapped, not dropped.
- A known 3-line order sums to its correct order total.
- The resulting `FeatureMatrix` RFM figures (recency / frequency / monetary / AOV)
  match hand-computed expected values.
- **Regression — no double-count:** a repeated-total line file (same amount on
  every line of an order) yields that amount once, not the sum.
- **Regression — ambiguity warning:** an all-`≤12/≤12` date file (e.g. `05/06`)
  parses under the day-first default and emits the ambiguity warning.

## Trust invariant (held)

Every figure is still computed by code over real data; the LLM never sees or
invents a number. This change makes the *inputs* to that computation correct on
real-world export shapes, and makes the remaining honest uncertainty (all-ambiguous
dates, summed line orders) visible to the operator as warnings rather than silent.

## Out of scope (unchanged)

Confirm-screen locale/grain UI, config-driven locale selection, multi-currency
conversion, and per-line customer/date conflict handling within a single order id.
