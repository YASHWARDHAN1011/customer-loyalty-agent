# Intelligence Layer — Bring-Your-Own-Data Redesign

**Date:** 2026-06-26
**Status:** Design approved (brainstorm complete) — ready for planning
**Author:** brainstormed with the user (internship deliverable for an Australian
e-commerce brand)

---

## 1. Why

The customer-loyalty-agent today is, structurally, "a chatbot bolted onto the
Instacart dataset." Every analysis module reads hardcoded Instacart-derived
columns (`total_orders`, `reorder_rate`, `dept_diversity`, `avg_basket_size`,
`total_items`, `avg_days_between_orders`). The moment a real client feeds in their
own data — which has revenue but may have *no* line items, departments, or reorder
flags — most of the engine silently produces wrong numbers or breaks.

This redesign turns the app into a professional **intelligence layer** that:

1. **Never malfunctions** when a different client's data is fed in.
2. Makes the **existing** agentic stack (briefing, autopilot, simulation,
   exports, watches) fire on that real data — **depth, not new breadth.**

It is a **real internship deliverable**, not a portfolio toy: prioritise trust,
data-portability, and graceful degradation over more features.

### Direction (locked)

**Approach A — Canonical Contract + Adapter.** Define ONE internal canonical data
model. Ingestion converts any input INTO it. All analysis/agent/UI read ONLY from
it. Instacart stops being special and becomes a built-in demo dataset fed through
the same pipe. (Rejected: B = map onto existing Instacart features / lossy
proxies; C = LLM picks signals at runtime / untrustworthy.)

**Re-anchor on RFM** (Recency / Frequency / Monetary) as the guaranteed-computable
core that works on *any* store. Instacart-style signals (categories, baskets,
reorders) become OPTIONAL extensions present only when the upload supports them.

---

## 2. Canonical data model (Section 1 — approved)

Two canonical tables:

- **`orders`** — `customer_id`, `order_id`, `order_date`, `order_amount`
  — **REQUIRED** for real client uploads.
- **`order_items`** — `order_id`, `product`, `category`, `quantity`
  — **OPTIONAL** (present only when the client has line-item data).

From these we build a **canonical feature matrix**: one row per customer, with
**every feature tagged available / unavailable**. That availability tag is the
mechanism that makes "never malfunctions" true — downstream code renormalises and
degrades based on it, never on a raw column name.

**Always computable from `orders` alone (the RFM core):**

| Feature | Meaning |
|---|---|
| `recency_days` | days since last order |
| `frequency` | number of orders |
| `monetary` | total revenue |
| `avg_order_value` | monetary / frequency |
| `tenure_days` | days since first order |
| `avg_days_between_orders` | mean gap between orders |

**Optional extensions (require `order_items`):**

| Feature | Meaning |
|---|---|
| `category_diversity` | unique categories purchased |
| `avg_basket_size` | items per order |
| `reorder_rate` | share of repeat purchases |

---

## 3. Ingestion pipeline (Section 2 — approved)

New package `src/data/ingest/`. Stages (all pure except the UI confirm step;
each gets its own standalone test):

1. **`reader.py`** — parse CSV/Excel; sniff delimiter, encoding, sheet.
2. **`profiler.py`** — per-column profile: name, dtype, sample values, `%null`,
   `%unique`. **Only this profile is sent to the LLM — never raw rows** (cheap +
   no PII leaves the machine).
3. **`mapper.py`** — LLM proposes a column mapping with confidence + reasoning.
   A deterministic fuzzy-header fallback runs when the LLM is unavailable / keys
   exhausted, so ingestion still works with zero LLM.
4. **UI confirm screen** — the **trust gate**. The user sees the proposed mapping
   in dropdowns and confirms before any analysis runs. Lightweight self-check
   warnings are folded in here. (Wrong mapping = silently wrong numbers = lost
   trust, so a human always confirms.)
5. **`validator.py`** — the **malfunction firewall**: dates parse, amounts are
   numeric ≥ 0, ids repeat, required columns present. On failure it returns a
   precise, human-readable message — **never a stack trace.**
6. **`builder.py`** — assemble the canonical `orders` + `order_items` tables and
   the feature matrix with availability tags.

### Persistence — mapping only (locked)

Save the confirmed column-mapping **recipe** plus a **dataset fingerprint**
(sorted-header hash) — **never the raw rows.** On re-upload of a same-shaped file,
auto-apply the saved mapping and skip the LLM/confirm step. No PII at rest;
connector-friendly. Best-effort JSON store like the other `.app_state/*.json`
stores. (A returning client still re-uploads the file but doesn't re-map.)

---

## 4. RFM engine + re-anchoring (Section 3 — approved)

### The problem this fixes

Today's 5 scoring **levers** are essentially `total_orders` + four line-item
features (`reorder_rate`, `dept_diversity`, `avg_basket_size`, `total_items`). An
orders-only client upload kills **4 of 5 levers**, collapsing the loyalty score to
"who ordered most often." And Instacart has **no money** — yet revenue is a real
store's single most important signal and today's engine never uses it.

### Re-anchoring

- **3a. Canonical core** (always computable): the six RFM-core features in §2.
- **3b. Optional extension levers** (need `order_items`): `category_diversity`,
  `avg_basket_size`, `reorder_rate`.
- **3c. Scoring — renormalise over available levers.** Default weights are defined
  over the full lever set. At scoring time, drop levers whose feature is
  unavailable and **renormalise the remaining weights to sum to 1.0.**
  `compute_scaler` / `apply_scoring` already iterate `if col in df.columns`, so the
  math already tolerates missing columns — we add explicit renormalisation and
  surface *which* levers were active. Orders-only → scores on RFM core; rich data →
  richer score; **never zero.**
- **3d. Per-consumer re-anchoring:**
  - **Churn (`calculate_churn_risk`)** — switch the at-risk test from
    `avg_days_between_orders > churn_days` to **`recency_days > churn_days`**
    (recency is the textbook churn signal and is always present; avg-gap needs
    ≥ 2 orders). Keep avg-gap as a secondary signal.
  - **Segmentation / interventions** — operate over whatever levers are active;
    intervention templates keyed to an absent optional feature simply don't fire.
  - **Happy path** — genuinely needs categories → degrades gracefully (see §5).
  - **Simulation** — `LEVERS` becomes "active levers only."
- **3e. Sidebar weight sliders** become dynamic — one slider per **active** lever,
  not five hardcoded Instacart ones; a caption lists which levers are active.

The thread through all of it: availability tags drive renormalisation and
degradation everywhere. **Nothing reads a raw Instacart column name anymore.**

---

## 5. Graceful degradation per surface (Section 4 — approved)

Three states per surface, driven by availability tags:

1. **Full** — required + needed optional features present → render as today.
2. **Degraded** — required present, optional missing → render the RFM-core
   version + a small inline note (e.g. "Basket metrics need product-level data").
3. **Unavailable** — a surface that *fundamentally* needs optional data → replace
   the body with a **calm, designed empty-state card** ("This view needs an
   items/products column. Re-upload with line items to unlock it.") — never a
   blank chart or a stack trace.

The empty-state is a first-class component, not an error. Trust = "the tool tells
me what it can and can't do."

| Surface | Needs optional data? | Behaviour when orders-only |
|---|---|---|
| **Overview** | No | **Full** — RFM headline metrics (revenue, recency, frequency, AOV); *richer* than today since it gains money. |
| **Scoring** | No | **Full** — renormalised RFM-core levers; sidebar shows only active sliders; caption lists active levers. |
| **Segments** | Partial | **Degraded** — gaps over active levers only; absent-feature rows omitted. |
| **Interventions** | Partial | **Degraded** — only templates whose feature exists fire; RFM-based ones (win-back lapsed, raise AOV) always available. |
| **Happy Path** | **Yes** (categories) | **Unavailable** empty-state when no `order_items`. |
| **Chat / Agent / Autopilot** | Tool-dependent | Each tool self-guards: a tool needing an absent feature returns a clean "can't — needs X data" message the agent narrates; never crashes the loop. Briefing/Watches signals for absent features don't generate. |
| **Simulation** | Lever-dependent | Only **active** levers offered as lift targets. |
| **Exports** | No | Target-list / CSV always work (RFM columns guaranteed). |

**One binding rule:** every surface asks the feature matrix "is this lever
available?" before rendering — it never assumes an Instacart column exists.

---

## 6. Instacart as a built-in demo dataset (Section 5 — approved)

Delete the special-case. Today `get_app_data()` is a separate path (merge 5 CSVs →
`_compute_features` → 6 Instacart columns). After this redesign, **Instacart flows
through the same canonical pipe as a client upload** — a one-click "Demo dataset."
Demo path === client path: if it works for Instacart, the same code works for the
client.

A **demo-only adapter** (`src/data/demo/instacart.py`) does the Instacart →
canonical translation:

- **Dates** — Instacart has only `days_since_prior_order` / `order_number`.
  Reconstruct absolute `order_date` by cumulatively summing
  `days_since_prior_order` per user, anchored to a synthetic "today." (No judgment
  call — built into the adapter.)
- **Money** — Instacart has none. **Locked decision: hard-require `order_amount`
  for real client uploads (the validator rejects an upload without it), but the
  demo adapter supplies clearly-labelled *synthetic* revenue** (e.g. basket size ×
  a notional unit price). Real path keeps the strong revenue guarantee; the demo
  still exercises the full RFM including Monetary.
- **Items** — map products/departments → `order_items`, so the demo also lights up
  the optional category/basket/reorder levers. The demo is the "rich" dataset
  (**Full** state); an orders-only client upload exercises the **Degraded** state.

`get_app_data()` is retired as a special path; the app's data source becomes
"load demo (Instacart through the adapter)" **or** "upload your file (through the
ingestion pipeline)." Both emit identical canonical tables + tagged feature matrix.
The committed parquet artifacts stay as the demo's fast-start cache — now holding
canonical-shaped demo data.

---

## 7. Testing strategy (Section 6 — approved)

Repo house style: **standalone scripts, `check()` + non-zero exit, no network, no
pytest.**

1. **`test_ingest.py`** — the malfunction firewall (highest value). Nasty inputs:
   missing required column, `DD/MM/YYYY` vs ISO dates, amounts with `$`/commas/
   negatives, duplicate headers, empty file, single-row file, Excel multi-sheet,
   UTF-16/BOM. Each yields a clean canonical table **or** a precise rejection —
   never a stack trace.
2. **`test_canonical.py`** — feature-matrix correctness + **availability tagging**
   (orders-only → optional tagged unavailable; orders+items → available). The core
   of "never malfunctions."
3. **`test_scoring_renorm.py`** — weights renormalise to 1.0 over active levers;
   orders-only scores on RFM core and is non-degenerate; rich data uses all levers.
   (Extends existing `test_scoring.py`.)
4. **`test_degradation.py`** — each surface's three states resolve correctly from
   availability tags (happy_path → Unavailable on orders-only; overview → Full).
5. **`test_demo_adapter.py`** — reconstructed dates monotonic per user; synthetic
   revenue present + flagged; `order_items` populated; output passes the same
   validator a client upload would.
6. **`test_mapping_persist.py`** — fingerprint round-trip: same-shaped re-upload
   reuses the saved mapping; a different shape does not.
7. **Existing suites** (insights / proactive / memory / router / simulation /
   watches) stay green, re-pointed at canonical features.
8. **App boots headless HTTP 200** on both the demo and a synthetic orders-only
   upload.

**`test_ingest.py` and `test_canonical.py` are the trust contract** — if those are
exhaustive, "works flawlessly on a client's unknown data" stops being a hope.

---

## 8. Scope boundaries

- **In scope:** canonical model, ingestion (CSV/Excel upload), mapping persistence
  (recipe only), RFM re-anchoring of every existing analysis/agent surface,
  graceful degradation, Instacart-as-demo, the test suite above.
- **Out of scope (v1):** live API/DB connectors (structure so a connector can feed
  the same pipe later), any *new* agent capability or tab, multi-file joins beyond
  orders + items, auth/multi-tenant. **No new breadth** — depth on the existing
  stack.

---

## 9. Open items for the planning phase

- Module layout under `src/data/ingest/` and `src/data/demo/`; where the canonical
  feature builder lives (likely `src/data/canonical.py`).
- Exact availability-tag data structure the feature matrix carries, and the helper
  every surface calls to query it.
- How the app's data-source selector (demo vs upload) threads into existing
  `st.session_state` keys without disrupting the 6-tab structure.
- Order of execution (suggested: canonical model + builder + tests → demo adapter
  (proves the pipe on known data) → ingestion pipeline → re-anchor each consumer →
  degradation UI → mapping persistence).
