# Per-Line Customer/Date Conflict Warnings — Design

**Date:** 2026-07-23
**Status:** Approved, ready for planning
**Depends on:** BYOD ingestion pipeline (`src/data/ingest/`), the line-item
amount-collapse depth pass (2026-07-14), and the confirm-screen grain controls
(2026-07-16).

## 1. Problem

When an uploaded file is **line-grained** — several rows share one `order_id`,
one row per line item — `build_canonical` collapses it to one row per order with
`.groupby("order_id").agg(customer_id="first", order_date="first",
order_amount=<grain>)` (`src/data/ingest/builder.py`).

The **amount** dimension of that collapse was already made honest: a prior depth
pass added sum-vs-first grain logic plus a warning when differing line amounts are
summed. But the other two collapsed columns are still silent:

- If two rows of the same `order_id` carry **different `customer_id`s**, the
  builder keeps the first and discards the rest — silently attributing the whole
  order (and its revenue) to one customer. This almost always signals that the
  `order_id` column isn't unique per order, or is mapped to the wrong column.
- If two rows carry **different `order_date`s**, the builder keeps the first —
  silently choosing one date, which feeds recency / tenure / avg-gap / churn. This
  is often benign (partial shipments dated separately) but is still an undisclosed
  decision.

Both are the exact failure class this tool promises never to make: a **silent
wrong number / silent misattribution with no warning**. This design closes the
last collapse dimension.

## 2. Goal

Surface — never hide — a customer_id or order_date conflict discarded during the
order collapse, as an operator warning, mirroring the existing amount-summing
warning. **Keep-first behavior is unchanged**; only the disclosure is new.

## 3. Non-goals (out of scope)

- Any change to the collapse *result*. We still keep the first customer and first
  date. No gating/erroring on conflicts (an explicitly rejected option), no
  "earliest date" heuristic, no splitting an order across customers.
- Any new module, UI surface, or confirm-screen control. This is warnings-only,
  entirely inside `build_canonical`.
- Any validator (`validate`) change. Conflicts are a *collapse* concern, detected
  in the builder after validation has passed.
- The other multi-currency / locale / grain threads (already shipped).

## 4. Design

All logic lives in `build_canonical` in `src/data/ingest/builder.py`, at the
existing collapse step, alongside the current `amt_nunique` computation.

### 4.1 Detection (pure, on the validated `result.orders`)

Before (or beside) the existing groupby-agg that builds `orders`:

```python
cust_conflicts = int(
    (result.orders.groupby("order_id")["customer_id"].nunique(dropna=False) > 1).sum())
date_conflicts = int(
    (result.orders.groupby("order_id")["order_date"].nunique(dropna=False) > 1).sum())
```

`dropna=False` so a genuine value-vs-missing split within an order still counts as
a conflict rather than being hidden by NaN-dropping.

### 4.2 Warnings

Appended to the already-copied `warnings` list (the builder copies
`result.warnings` at the top of the success path, so this never mutates the
`ValidationResult`):

- **Customer conflict (strong wording)** — only when `cust_conflicts > 0`:
  > "{N} order(s) had more than one customer across their rows; the first customer
  > was kept. This usually means the Order ID column isn't unique per order or is
  > mapped to the wrong column — verify the Order ID mapping."

- **Date conflict (soft wording)** — only when `date_conflicts > 0`:
  > "{N} order(s) had rows with different dates (e.g. partial shipments); the first
  > date was kept."

### 4.3 When it fires

- Runs for **all grains** (`auto` / `line_item` / `order_level`) — customer_id and
  order_date are collapsed as "first" regardless of the amount grain choice, so the
  conflict is grain-independent.
- **Never fires on order-grained files** (one row per `order_id`): every group has
  a single customer/date, so `nunique` is 1. The Instacart demo and any
  one-row-per-order upload are completely unaffected — no new warnings, identical
  output.

## 5. Trust invariant

Still keep-first, still exception-free on validated input, still no fabricated
numbers. The change makes a previously-hidden discard **visible** to the operator,
so they can catch a broken Order ID mapping or acknowledge a benign partial-
shipment date split — consistent with every other BYOD warning.

## 6. Testing

Extend `tests/test_ingest.py` (standalone-script style, no network):

- **Customer conflict fires:** a line-grained fixture where one `order_id` spans
  two `customer_id`s → build succeeds, warning list contains the strong customer
  message with the right count, and the kept customer is the first.
- **Date conflict fires:** a fixture where one `order_id` spans two `order_date`s →
  success, warning list contains the soft date message with the right count.
- **Clean file is silent:** an order-grained fixture (one row per order_id) →
  success, neither conflict message present.
- Full ingest sweep (`test_ingest`), plus `test_canonical`, `test_upload_flow`,
  `test_mapping_persist`, `test_export`, `test_tools_canonical` stay green; the app
  boots with 0 exceptions.

## 7. Files touched

- `src/data/ingest/builder.py` — add the two nunique checks + two conditional
  warnings inside `build_canonical`.
- `tests/test_ingest.py` — three new checks.
- `CLAUDE.md` — a dated journal entry.
