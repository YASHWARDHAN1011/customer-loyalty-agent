# Phase 6 — Upload + Mapping-Confirm UI

**Date:** 2026-07-09
**Status:** Approved (brainstorming)
**Roadmap:** Chat-first agent roadmap §Phase 6 (build order `4 → 4.5 → 5 → 6 → 7 → 8 → 9`).
**Builds on:** Phase 3 ingestion backend (`src/data/ingest/`), Phase 4 canonical
wiring (`src/data/app_data.py`), Phase 5 tool re-anchoring.

## 1. Purpose

The ingestion backend (read → profile → LLM-propose mapping → validate → build
canonical) already exists and is tested (Phase 3). Phase 4 wired the app to run on
canonical data, but only ever loads the **built-in Instacart demo**. There is no way
for a user to upload their own CSV/Excel and drive that pipeline.

Phase 6 builds the **front door**: an in-app upload control, an LLM-proposed
**column mapping the user confirms before any analysis runs** (the trust gate — a
wrong mapping means silently wrong numbers), and the wiring that makes the confirmed
dataset the app's active data for the session. Scope is **MINIMAL / functional, not
fancy** — it orchestrates existing, tested backend units and renders Streamlit
widgets. No new intelligence.

## 2. Locked decisions (from brainstorming)

- **Location:** upload control + dataset indicator live in the **sidebar**; the
  mapping-confirm screen renders in the **main area** (full-width decision), gated
  above the tabs.
- **After Confirm (Q1):** auto-run the full analysis immediately and land on results
  (same as the onboarding wizard's finish). One click.
- **Validation timing (Q2):** validate on the **Confirm click** via `build_canonical`
  (the firewall). On failure, stay on the confirm screen and show the backend's
  plain-language `errors`; on success, proceed showing any non-fatal `warnings`.
- **Saved-mapping shortcut (Q3):** a header-fingerprint match **auto-applies** the
  saved recipe and goes straight to build + analyze, with a visible "Using your saved
  mapping — [Review mapping]" note whose link reopens the confirm screen.
- **Back to demo (Q4):** the sidebar shows the active dataset and offers an explicit
  **"Back to demo data"** control; the demo remains one click away.
- **Persistence:** mapping-only (no raw rows at rest — locked in the parent design). A
  refresh/restart boots back to the demo; the saved mapping makes re-upload a
  confirm-free step.

## 3. Architecture

### 3.1 The active-dataset seam (refactor `app.py`)

Today `app.py` binds the demo as **module-top locals**
(`orders, order_items, features, available, active_levers = load_demo_app_data()`)
and passes them into the sidebar, `run_analysis`, and tabs. `run_analysis` closes
over the demo `features`. There is no seam to swap the dataset.

**Change:** hold the **active dataset in `session_state`** under a stable set of keys:

| key | meaning |
|-----|---------|
| `features` | per-customer feature matrix frame (already used) |
| `full_data` | line-item `order_items` (or None) — used by happy-path |
| `orders` | canonical orders table |
| `available` | availability map |
| `active_levers` | active scoring levers |
| `dataset_label` | human label, e.g. `Instacart` / `sales_export.csv` |
| `dataset_source` | `"demo"` \| `"upload"` |
| `dataset_counts` | `{customers, orders}` for the header badge / sidebar |

On boot these are populated from `load_demo_app_data()` exactly as today (no behavior
change for the demo path). `run_analysis`, `render_sidebar`, and the tabs read the
active dataset from `session_state` rather than module locals.

A single **swap helper** `set_active_dataset(...)` (new; `src/data/app_data.py` or a
small `src/ui/dataset.py`) centralizes a dataset switch:

1. write the dataset keys above,
2. reset `weights = default_weights(active_levers)`,
3. clear stale analysis results (`scored_df`, `power`, `regular`, `cutoff`,
   `thresholds_df`, `power_user_ids`),
4. (caller then triggers `run_analysis`).

Both **upload** and **back-to-demo** go through this one helper (opposite directions).

### 3.2 Upload + confirm module (`src/ui/upload.py`, new)

A small **state machine** in `session_state["upload_stage"]` (Streamlit reruns on
every interaction):

- **`idle`** — sidebar "📁 Your data" section: active-dataset indicator + a
  CSV/Excel `st.file_uploader`. On a new file: `reader.read_table` → `profiler.profile_columns`
  → `mapping_store.fingerprint(headers)`.
  - **fingerprint match** → `mapping_store.load_mapping` → stage `build` (fast path),
    and set a flag so a "Using your saved mapping — [Review mapping]" note renders;
    "Review mapping" sets stage `confirm`.
  - **no match** → `mapper.propose_mapping(profile, generate_fn=generate)` (the app's
    existing `generate`; the deterministic `fuzzy_map` fallback is already inside the
    mapper, so it works with no keys / exhausted quota) → stage `confirm`.
- **`confirm`** — main-area screen (above tabs). For each canonical field
  (`customer_id`, `order_id`, `order_date`, `order_amount` required; `product`,
  `category`, `quantity` optional) an `st.selectbox` of the file's columns, pre-filled
  with the proposal; required fields caption the LLM confidence/reasoning; optional
  fields include "— none —". A ~5-row preview of the chosen columns. Buttons:
  **Confirm** and **Cancel** (→ idle, keep current dataset).
- **`build`** (transient) — run `builder.build_canonical(df, mapping)`.
  - `ok == False` → stage `confirm`, render `errors` as red messages.
  - `ok == True` → `mapping_store.save_mapping(headers, mapping)`; render `warnings`;
    `features_from_matrix(matrix)` → `set_active_dataset(source="upload", label=filename, …)`
    → `run_analysis(top_pct)` → stage `idle`.

The module **only orchestrates** already-built, already-tested units (reader,
profiler, mapper, validator, builder, mapping_store, `features_from_matrix`) and
renders widgets. It imports `generate` for the mapping proposal and `run_analysis`
via an injected callback (mirrors `render_sidebar(run_btn_callback)`).

### 3.3 Dataset indicator + header badge

- Sidebar "📁 Your data" always shows the active dataset (`📊 Demo data · Instacart`
  or `📊 Your data · <filename>`) with `dataset_counts`. When `dataset_source ==
  "upload"`, an **"↩ Back to demo data"** button calls `load_demo_app_data()` →
  `set_active_dataset(source="demo", …)` → `run_analysis`.
- The `app.py` header badge (currently the hardcoded string
  *"Instacart // 206,209 customers // 3.4M orders"*) reads `dataset_label` /
  `dataset_counts` so it never misreports a loaded client dataset.

## 4. Error handling

- **Validation failures** surface as the backend's plain-language `errors`
  (e.g. "Order amount: 14% of values aren't numeric") on the confirm screen; nothing
  analyzes until `build_canonical` returns `ok`. This is the hard gate.
- **Read failures** (unreadable file, empty, unknown format) → a single friendly
  error in the sidebar; stage stays `idle`, active dataset unchanged.
- **LLM unavailable** (no keys / quota) → `propose_mapping`'s deterministic
  `fuzzy_map` fallback still proposes a mapping; the user confirms as normal.
- Best-effort throughout: a failure in the upload flow never crashes the app or
  corrupts the active dataset (consistent with the persistence/onboarding convention).

## 5. Out of scope (YAGNI)

- Persisting raw uploaded rows across restart (locked: mapping-only).
- Multi-file merge / appending datasets.
- Column *type* overrides beyond the field mapping.
- Editing the mapping after analysis has run (to re-map, re-upload — one confirm via
  the saved recipe).
- Live per-field validation as dropdowns change (rejected Q2 option B).
- Deep re-skin of the legacy dashboard tabs (they degrade via `_guard`; the
  chat-first shell in Phase 7 supersedes them).

## 6. Testing

Repo convention: standalone `tests/test_*.py` scripts, no pytest, no network.

- **`tests/test_upload_flow.py`** (new) — drives `src/ui/upload.py` via
  `AppTest.from_string` (real Streamlit runtime so the state machine + `session_state`
  execute) with a tiny in-memory CSV and an **injected fake `generate_fn`** (no
  network). Asserts: full happy path (upload → profile → proposed mapping → confirm →
  `build_canonical` → active dataset swaps to upload → analysis runs → 0 exceptions);
  failure path (bad amount column → stays on `confirm` with an error, dataset
  unchanged); fingerprint-match fast path (skips confirm, note shown).
- **`tests/test_dataset_swap.py`** (new) — unit-tests `set_active_dataset` directly:
  demo→upload→back-to-demo leaves `session_state` consistent (weights renormalized to
  the new active levers, stale analysis cleared, labels/counts correct).
- **Regression:** the existing 25 no-network suites stay green, and `AppTest` boots
  the app with **0 exceptions** on the demo (proves the `app.py` active-dataset
  refactor didn't regress the demo path).

## 7. Files

**New:** `src/ui/upload.py`, `tests/test_upload_flow.py`, `tests/test_dataset_swap.py`;
`set_active_dataset` helper (in `src/data/app_data.py` or new `src/ui/dataset.py`).
**Changed:** `app.py` (active-dataset seam + dynamic header badge + render the upload
confirm gate), `src/ui/sidebar.py` (read active dataset from `session_state`; the
"Your data" section may live here or in `upload.py` and be called from the sidebar).

## 8. Build order

1. Active-dataset seam: `set_active_dataset` + refactor `app.py`/`sidebar`/`run_analysis`
   to read from `session_state`; demo path unchanged. (`test_dataset_swap.py`)
2. Upload module state machine + confirm screen + build/analyze wiring. (`test_upload_flow.py`)
3. Dataset indicator, "Back to demo", dynamic header badge.
4. Regression sweep (25 suites + `AppTest` boot) + CLAUDE.md journal entry.
