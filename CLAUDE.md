# CLAUDE.md

This file has two jobs:

1. **A project journal** (below) — a plain-language log you can read to see what
   was changed, when, and why. Newest entries first.
2. **Technical guidance** for Claude Code / contributors — how the app is wired.

---

## 📓 Project Journal

### 2026-07-16 — Fix: CSV export crashed on uploaded (canonical) data
Found by runtime verification of the confirm-screen work: driving the full app
through an upload → confirm → analyze flow crashed in `render_sidebar →
generate_csv_export` with `KeyError: ['total_orders', 'dept_diversity',
'total_items'] not in index`. `src/export/generator.py` still hardcoded the
Instacart feature columns (the one BYOD re-anchoring the roadmap missed — `tools.py`,
`deliverables.py`, and `interventions.py` were re-anchored in Phase 5 but the CSV
export was not), so any real client dataset crashed the whole page the moment the
sidebar rendered the download button.
- **`generate_csv_export`** now emits fixed meta columns (Customer ID / Loyalty
  Score / Tier / Is Power User) followed by **whatever feature columns the dataset
  actually has**, each labelled through the existing `tool_context.feature_label`
  (levers → `LEVER_LABELS`, extras like `total_orders`, else title-case). Instacart
  demo output is unchanged; canonical RFM data (`frequency`/`monetary`/`recency_days`)
  now exports instead of crashing.
- **Testing:** NEW `tests/test_export.py` (AppTest) — a canonical scored_df exports
  with no exception + correct headers, and an Instacart-shaped scored_df still keeps
  its "Total Orders" label (7 checks). Verified end-to-end: full `app.py` boot →
  seed upload → confirm → analyze now completes with 0 exceptions (previously
  crashed here). Regression sweep green (export, full_numbers, upload_flow, ingest,
  tools_canonical).
- **Not touched (cosmetic, non-crashing):** `generate_summary_report` still prints
  "Dataset: Instacart Grocery Platform" and Instacart-flavoured intervention copy —
  a label nit, not a crash; left for a later polish pass.

### 2026-07-16 — Confirm-screen locale & grain override controls
Follow-on depth to the BYOD hardening pass. The date-locale and order-grain
decisions used to happen silently inside `build_canonical` *after* Confirm,
surfacing only as post-hoc warnings once analysis had already run. Now the operator
sees the detection and can override both on the confirm screen, before anything
computes.
- **Backend overrides (pure, `None`-default = unchanged auto behavior):**
  `validate(df, mapping, dayfirst=None)` forces the date locale (skipping inference
  + its ambiguity warning) when given `True`/`False`. `build_canonical(df, mapping,
  dayfirst=None, grain=None)` threads `dayfirst` and adds `grain`: `None`=auto rule,
  `"line_item"`=**always sum** lines per order (catches a line-item file whose lines
  happen to cost the same — e.g. 2×$25 → $50, which the auto-rule would keep at $25),
  `"order_level"`=keep first per order (warns if differing amounts were discarded).
  New pure `detect_grain(df, mapping)` mirrors the auto-rule (any order id with >1
  distinct cleaned amount ⇒ line-item) for the confirm-screen display; safe-defaults
  to `order_level` when unmapped or on any error, never raises.
  `apply_mapping(..., dayfirst=None, grain=None)` forwards both.
- **Confirm screen (`src/ui/upload.py` `render_confirm_gate`):** two `st.radio`
  controls after the column dropdowns/preview — "Date format" (Auto / Day-first /
  Month-first) and "Order grain" (Auto / Line-item / Order-level), each with a
  `Detected: …` caption computed live from the currently-chosen columns via
  `_infer_dayfirst` / `detect_grain`. Stable option strings + a separate detected
  caption (rather than a mutating "Auto (detected: …)" label) avoid a Streamlit
  keyed-radio crash when the detected value changes. Confirm translates the two
  selections to `dayfirst`/`grain` overrides → `_build_and_activate` → `apply_mapping`.
  Both new session keys added to `_UPLOAD_KEYS` so a second upload never inherits the
  first file's locale/grain choice. Saved-recipe fast path stays Auto (deliberate).
- **Testing:** `tests/test_ingest.py` — `test_validate_dayfirst_override`,
  `test_build_canonical_grain_override`, `test_detect_grain` (114 checks total).
  `tests/test_upload_flow.py` — `test_apply_mapping_honors_overrides` (pure) +
  `test_confirm_gate_shows_locale_and_grain_radios` (AppTest asserts both radios
  render). Full sweep green (ingest 114, upload_flow, canonical 52, mapping_persist 9,
  dataset_swap); app boots 0 exceptions. Spec + plan in
  `docs/superpowers/{specs,plans}/2026-07-14-confirm-screen-locale-grain*`.

### 2026-07-14 — BYOD validation hardening (real-data correctness)
Depth pass over the ingestion firewall after the chat-first roadmap finished. Two
probes against `validator.validate()` surfaced bugs that produced **wrong numbers
without crashing or warning** — the worst failure mode for a tool whose promise is
"never fabricate a figure", and both hit the most common real e-commerce export
shapes for the Australian client.
- **Date-locale bug (fixed).** `pd.to_datetime` defaults to month-first, so an AU
  `03/04/2025` (3 April) was silently read as March 4 — corrupting recency, tenure,
  avg-gap and churn (the whole RFM core). **`src/data/ingest/validator.py`** now has
  `_infer_dayfirst(raw)`: it reads the evidence in the column — any first component
  >12 ⇒ day-first, any second >12 ⇒ month-first, all-≤12 ⇒ genuinely ambiguous
  (default day-first + a warning naming the column). No blind `dayfirst=True` (that
  would mirror the bug onto US clients). Pure-ISO columns short-circuit to pandas'
  default to avoid a spurious dayfirst reparse warning.
- **Line-item revenue collapse (fixed).** A Shopify/WooCommerce export is
  line-grained (one order across several rows, each its own line price). The builder
  deduped on `order_id` keeping the FIRST amount, so a $100 order booked as 30+45+25
  recorded **$30** — silently under-counting revenue/monetary/AOV. **`src/data/ingest/builder.py`**
  replaces `drop_duplicates` with a per-order `_collapse_amount`: identical line
  amounts are a repeated order total (kept once), differing amounts are line prices
  (**summed**). One rule, correct for one-row-per-order, repeated-total, and true
  line-item files with no double-counting; warns when it summed.
- **Trust invariant held:** code still computes every figure over real data; this
  makes the *inputs* correct on real export shapes and surfaces the remaining honest
  uncertainty (all-ambiguous dates, summed orders) as operator warnings, never
  silently.
- **Testing:** `tests/test_ingest.py` extended — `test_validate_au_dates` (decisive
  both ways, ambiguous default+warn, ISO clean), `test_build_canonical_sums_line_items`
  (+ no-double-count regression), rewrote `test_build_canonical_line_grained_warns`
  for the new summing behavior, and `test_au_shopify_export_end_to_end` (a messy AU
  Shopify export — `$`/commas, parenthesised refund clipped to 0, DD/MM dates, a
  multi-line order — driven through validator→builder→FeatureMatrix with every RFM
  number hand-computed). Full ingest sweep green: `test_ingest` (104), `test_canonical`
  (52), `test_mapping_persist` (9), `test_upload_flow`. Spec + plan in
  `docs/superpowers/{specs,plans}/2026-07-14-byod-validation-hardening*`.

### 2026-07-13 — Intelligence Layer / Chat-First, Phase 9: Recipes + finishing pass
The last roadmap item. A good grounded-query answer can now be saved as a named,
one-click "recipe" that recomputes on live data — closing the chat-first roadmap.
- **`src/agent/recipes.py`** (NEW, pure / Streamlit-free): best-effort JSON store
  at `.app_state/recipes.json` (same shape/guarantees as `watches.py`) holding
  `{id,name,query,created}` — `query` is exactly the `run_grounded_query` arg dict.
  No raw data, numbers, or code at rest. `load_recipes`/`add_recipe`
  (blank name → derived label)/`remove_recipe` + pure `describe_query` (scalar /
  grouped / correlation / filtered labels). NOTE: `path` resolves to the module
  `RECIPES_FILE` at call time (not a bound default) so the UI + a monkeypatched
  test share one store.
- **`src/agent/tools.py`**: `run_grounded_query` now stashes
  `session_state["last_grounded_query"] = {query, label}` on every SUCCESS (failures
  never overwrite it) — the one seam the save form reads.
- **`src/ui/tabs/chat.py`**: a "💾 Save as recipe" form (name pre-filled with the
  derived label) after a grounded answer; a "🍳 Your recipes" chip row; and
  `_run_recipe` — deterministic replay that calls `run_grounded_query(**query)`
  directly (NOT through `dispatch`, NO LLM), so recipes work even with Gemini quota
  exhausted. `render_chat` consumes a `run_recipe_id` flag set by the sidebar; a
  replay clears `last_grounded_query` so the save form doesn't re-offer an existing
  recipe.
- **`src/ui/sidebar.py`**: a "🍳 Recipes" section (mirrors Watches) — list each
  saved recipe with ▶ Run (sets the flag) and 🗑 delete.
- Dispatch `recipe_fn` rung STAYS inert — recipes are chip-triggered with known
  args, no NL matching. Recipes are dataset-agnostic: replaying one whose column is
  absent on a swapped dataset yields the engine's clean "No such column" message,
  never a crash.
- **Finishing pass:** pinned `anthropic>=0.111.0`; **converted `requirements.txt`
  from UTF-16 to UTF-8** — the hardening pass found pip cannot parse a UTF-16
  requirements file, so `pip install -r requirements.txt` (and therefore a Streamlit
  Cloud deploy) had been silently broken since the file went UTF-16 in Phase 5; now
  `pip install -r` resolves cleanly. Also added the missing `openpyxl>=3.1` — the
  ingest reader's `pd.read_excel` path for `.xlsx` uploads had no declared/installed
  backend, so a real client Excel upload would have crashed on a fresh deploy
  (verified a round-trip `.xlsx` now reads through `reader.read_table`). Rewrote
  `README.md` (what it is / run / deploy /
  trust + data-portability story). **Verified 2026-07-14:** live headless server
  boots HTTP 200 with 0 tracebacks (full recipe UI wired into chat + sidebar); the
  recipe save-form → chip-run interaction is covered by `test_recipes_ui.py`
  (AppTest); and a programmatic non-Instacart BYOD dry-run (client headers
  cust/invoice/when/total → `build_canonical` → RFM matrix → grounded query returns
  real numbers) confirms the client-data path end to end.
- **Testing:** `tests/test_recipes.py` (store round-trip, describe_query, corrupt
  store, blank-name), `tests/test_recipes_ui.py` (AppTest: save form appears; chip
  renders and running it produces a card, 0 exceptions), extended
  `tests/test_tools_canonical.py` (stash assertion). Full no-network sweep green;
  app boots 0 exceptions. **Roadmap 4→9 complete.**

### 2026-07-13 — Intelligence Layer / Chat-First, Phase 8: Grounded data-query tool
The agent got an out-of-box escape hatch: one constrained tool that computes real
aggregates, group-bys, and correlations over the canonical tables, so the chat can
answer novel questions no purpose-built tool covers — without ever letting the LLM
invent a number.
- **`src/analysis/query.py`** (NEW, pure / Streamlit-free): `run_query(tables, ...)`
  — the engine. Flat scalar params; whitelisted `table` / `operation` / `agg` /
  `filter_op`; validates every referenced column against the REAL dataframe columns
  (never assumes Instacart names); coerces the one optional filter value to the
  column's type; runs a scalar or grouped aggregate (sorted, capped at `limit`, hard
  max 50, `truncated` flagged, all-null groups dropped) or a Pearson correlation
  (needs ≥2 non-null pairs). NEVER raises — every guard returns
  `{"ok": False, "error": <plain message>}`, and the whole body is wrapped so a bad
  query degrades into relayable text, never a crash. On success it echoes the resolved
  `query` dict (exactly what Phase 9 will freeze into a recipe).
- **`src/agent/tools.py`** → `run_grounded_query(...)` (NEW tool, added to
  `ALL_TOOLS`): assembles `{"customers": features, "orders": orders,
  "order_items": full_data}` from `session_state`, calls the engine, and renders the
  result into `ui_history` — a metric card for a scalar, a sorted table + bar chart
  for a group-by, an r + plain-language strength/direction label for a correlation —
  then returns a "narrate ONLY these numbers" instruction. Auto-registers through
  `spec_from_function` (all-scalar signature); its first docstring line tells the
  model this is for novel questions and that numbers are computed here, not by it.
- **Trust invariant held:** the LLM only picks the query and narrates; code computes
  every figure over real data. On the artifact/cloud path `full_data` is `None`, so
  `order_items` questions degrade with an honest "product-level data isn't loaded"
  message. The dispatch `grounded_fn` rung stays inert — this tool is reached via
  normal function calling.
- **Testing:** `tests/test_query.py` (NEW) — engine contract on hand-computable
  fixtures: every agg, group-by correctness + sort, Pearson r, every `filter_op`
  incl. `between` and string-equality, `limit` cap + `truncated`, all-null-group
  drop, and every guard (bad table/op/agg/column, non-numeric metric,
  `order_items=None`, empty population, <2 correlation pairs).
  `tests/test_tools_canonical.py` (EXTENDED) — drives `run_grounded_query` through a
  real Streamlit runtime on orders-only canonical data: a scalar and a correlation
  return real numbers; bad-column and `order_items` queries degrade cleanly
  (0 exceptions). Full no-network sweep green; app boots 0 exceptions.
- **Out of scope (v1):** multiple/OR filters, joins, raw-row listing (search_users
  owns that), time-series, and saving recipes (Phase 9 — Phase 8 only makes the
  args recipe-shaped via the `query` echo).

### 2026-07-11 — Intelligence Layer / Chat-First, Phase 7: Chat-first shell + dispatch ladder
Chat is now the app. The 6-tab dashboard is gone; the conversation is the landing
page, and every message flows through one ordered decision structure instead of the
old route-then-branch code inside the chat tab.
- **`src/agent/dispatch.py`** (NEW, Streamlit-free): `dispatch(prompt, ...)` — the
  ladder. Rungs, first match wins: (1) saved recipe [Phase 9 slot — `recipe_fn`,
  None today], (2) known tool (`route` → "answer" → `call_agent`), (3) multi-step
  goal (`route` → "goal" → `run_reflexive`), (4) grounded query [Phase 8 slot —
  `grounded_fn`, reached only if the tool path returns nothing, None today]. All
  collaborators (`route_fn`/`agent_fn`/`reflexive_fn`/`recipe_fn`/`grounded_fn`) are
  injected so the module is fully unit-testable with fakes; the goal rung streams
  live progress through an injected `on_step(reason, label)`. Any exception in a rung
  is caught and returned as a relayable ⚠️ answer — a dispatch never crashes the chat.
  Slots (1) and (4) are wired but inert, so Phases 8/9 drop in with no ladder change.
- **`src/ui/full_numbers.py`** (NEW): `render_full_numbers()` — one dataset-agnostic
  figures panel replacing the 5 retired analytical tabs. Reads the canonical feature
  matrix + the same lever-agnostic helpers the agent tools use (`calculate_churn_risk`,
  `compute_segment_gaps`/`build_comparison_data`, `generate_csv_export`): 4 key metrics
  (customers / power users / at-risk 30d / avg loyalty score), a top-500 scored table
  with a full-CSV download, and a power-vs-regular-by-lever bar chart. Best-effort —
  any failure collapses to a one-line hint instead of crashing the page.
- **`src/ui/tabs/chat.py`** (rewritten): the chat-first page body. Drops the 3-metric
  status row, the 8-button quick-action wall, and the examples expander. Now: an API
  banner, the proactive briefing, the conversation, 4 starter chips (only while the
  user hasn't spoken), the chat input, a collapsible "📊 Full numbers" expander, the
  deliverables panel, and "New conversation". Every message (chips, briefing actions,
  input) goes through `_submit` → `dispatch`; goal results still inline tool output and
  post a synthesized summary + neutral-shape continuity turns.
- **`app.py` / `src/ui/tabs/__init__.py`**: dropped `st.tabs(...)` and the 5 tab
  imports; `render_chat(features, orders)` is now the whole page (below the existing
  watch alerts / upload notices / onboarding). `__init__.py` exports only `render_chat`.
- **Deleted** `src/ui/tabs/{overview,scoring,segments,happy_path,interventions}.py` —
  the Instacart-shaped tabs Phase 4 had left degrading behind guards. Their one useful
  surface (the figures) now lives in `full_numbers.py`, dataset-agnostic.
- **Chrome declutter**: the model-status metrics (active model / combos left) moved
  from the chat into the sidebar's 🔑 API Status section.
- **Testing**: `tests/test_dispatch.py` (6 checks — each rung, slot short-circuits,
  fall-through, exception-caught, all with fakes), `tests/test_full_numbers.py` (hint
  before analysis + metrics after, via AppTest), `tests/test_chat_shell.py` (app boots
  0 exceptions, chat input present, no retired tab labels). Full no-network sweep green:
  dispatch, full_numbers, chat_shell, upload_flow, dataset_swap, tools_canonical,
  canonical (52), levers (18), app_data (6).

### 2026-07-10 — Intelligence Layer / Chat-First, Phase 6: Upload + mapping-confirm UI
The app now has a front door. A user can upload their own CSV or Excel file, confirm
the LLM-proposed column mapping in the UI, and the app swaps to their dataset and runs
the full analysis on it. This is the Streamlit interface wired onto the Phase-3
ingestion backend.
- **`src/ui/dataset.py`** (NEW, pure): `set_active_dataset(state, ...)` — the single
  seam that installs a dataset into `session_state`, resets `weights` to the new
  dataset's active levers (`default_weights`), and clears stale analysis. Both the
  upload path and "Back to demo" go through it so there is exactly one place that
  swaps datasets.
- **`app.py` refactor**: the demo now boots THROUGH `set_active_dataset` (called above
  the header so the badge can read it); everything reads the active dataset from
  `session_state`; `run_analysis` reads `session_state['features']`; the header badge
  is now dynamic (reads `dataset_label`/`dataset_counts`, no longer hardcodes
  "Instacart // 206,209 customers").
- **`src/ui/upload.py`** (NEW): pure `prepare_upload` (profiles the file, hits the
  saved-recipe fast path via header fingerprint if known, else calls `propose_mapping`
  with a fuzzy fallback) + `apply_mapping` (validates/builds via `build_canonical`,
  persists the recipe on success). Streamlit layer: `render_upload_section` (sidebar
  uploader + dataset indicator + "Back to demo") and `render_confirm_gate` (main-area
  confirm screen — a dropdown per canonical field pre-filled from the proposal, a data
  preview, Confirm auto-runs analysis, Cancel); `_build_and_activate` swaps and
  analyzes, keeping the confirm screen on failure with plain-language error messages.
- **State-machine robustness**: the `st.file_uploader` uses a nonce key so
  Cancel/Back-to-demo truly dismisses the widget (Streamlit otherwise retains the
  file); stale per-field `map_*` widget keys are cleared on new-file/Cancel/Back/
  success so a second upload is never silently pre-filled from the first run.
- **Trust gate held**: nothing analyzes until `build_canonical` validates the mapping;
  the confirm step is required for any first-seen file shape; a known fingerprint
  fast-paths with a "using your saved mapping" note shown to the user.
- **Testing**: `tests/test_dataset_swap.py` (swap helper, 9 checks) +
  `tests/test_upload_flow.py` (pure `prepare_upload`/`apply_mapping` with a fake
  `generate_fn`, plus an AppTest demo-boot check). All 9 no-network suites from
  this task ran green; overall suite (9 suites) confirmed green in the regression
  sweep.

### 2026-07-07 — Intelligence Layer / Chat-First, Phase 5: Re-anchor agent tools on canonical levers
Closes the big Phase-4 caveat ("agent tools still Instacart-bound"). The analysis
engine already ran on any dataset; now the **agent's tools** do too. Before this,
asking the chat to "score customers", "show me user 123", or "export a target
list" on a client's canonical data threw `KeyError` on hardcoded Instacart columns.
Now every tool reads whatever features the dataset actually has.
- **`src/agent/tool_context.py`** (NEW, pure): the single place tools resolve
  columns — `feature_label`, `present_feature_cols` (drops the `user_id`/
  `customer_id` ids), `order_count_col` (`total_orders`→`frequency`), `churn_gap_col`
  (`recency_days`→`avg_days_between_orders`), `summary_stats`.
- **`src/agent/tools.py`** — re-anchored 6 tools: `run_scoring_analysis` builds
  default weights from the dataset's `active_levers` and renormalizes any stale
  session weights (drops Instacart keys); `get_current_stats` summarizes available
  features; `analyze_churn_risk` reports the resolved churn column; `get_user_profile`
  builds from present features; `search_users` filters/displays resolved columns;
  `simulate_campaign` validates against `active_levers` (and its docstring — the
  schema Gemini reads — no longer lists dead Instacart levers).
- **`src/agent/deliverables.py`** — `select_target_users` exports whatever features
  exist (no fixed `_TARGET_COLS`); email/action-plan builders use the generic
  template fallback.
- **`src/analysis/interventions.py`** — `template_for(col)` returns the hand-authored
  template when one exists else a generic label-driven one, so campaigns/emails/
  plans produce content on ANY levers; `compute_intervention_gaps` is now
  column-agnostic (prefers the curated order, falls back to numeric levers,
  excludes ids/score/churn-direction).
- **`src/config.py`** — `SYSTEM_PROMPT` is dataset-agnostic: no "Instacart /
  206,209 customers / departments", and it tells the model features vary and to
  relay unavailability rather than invent numbers.
- **Trust invariant held:** tools compute real numbers or say a feature is
  unavailable — never a crash, never a fabricated figure. Scope was **minimal**
  (generic campaign copy; no hand-authored per-lever e-commerce templates yet).
- **Testing (new pattern):** `tests/test_tools_canonical.py` runs the real tools on
  an orders-only canonical dataset via `AppTest.from_string` (a real Streamlit
  runtime, so `st.session_state` works) and asserts zero exceptions + correct
  behavior — the first suite that exercises tools on data, not stubs. Plus
  `test_tool_context.py` (15) and `test_interventions_generic.py` (4) and
  `test_system_prompt.py` (7). All 25 no-network suites green; app boots 0 exceptions.
- Default Instacart-demo behavior is unchanged (the demo's canonical artifacts
  already use the canonical column names).

### 2026-07-07 — Expand Gemini model buckets (more free-tier headroom)
Refreshed `config.MODELS` from the aging 2.0-era list to current models, ordered
best-first: `gemini-2.5-flash`, `-flash-lite`, `gemini-3.5-flash`,
`gemini-3.1-flash-lite`, then `gemini-2.5-pro` and the legacy `2.0-flash`/`-lite`
as last-resort. Each model is a SEPARATE daily free-tier quota bucket, so this is
a direct capacity increase — with 4 keys the rotation grows 12 → 28 combos.
Verified live against `list_models` + a real ping per model on key 1: the four
newer flash buckets answer; `2.5-pro` and both `2.0` buckets report free-tier
`limit:0` (kept last as insurance — they auto-activate on a billed key / reset).
Newer buckets also raise output limit 8k → 64k. Pairs with the Phase 4.5 failover
(Gemini→Claude) — add an `ANTHROPIC_API_KEY` for a whole extra provider tier.

### 2026-07-06 — Intelligence Layer / Chat-First, Phase 4.5: Provider-agnostic tool loop + config-swappable backend
The tool-using chat is no longer Gemini-only. Its quota exhaustion was the chat's
single point of failure — the text/reasoning path already failed over to Claude
(Phase 5), but the path that actually matters (function calling) did not. Phase 4.5
closes that gap with one hand-written tool loop both providers can drive, and makes
the whole LLM backend selectable by a single config value.
- **`src/agent/tool_specs.py`** (NEW, pure): a neutral tool registry auto-derived
  from each tool's typed signature (`spec_from_function`, `TOOL_SPECS`) — one
  source of truth both providers read, no hand-maintained schemas. `execute_tool`
  is the ONLY place a tool runs; it summarizes the return for the model and
  **catches any exception** so an Instacart-bound tool degrades into relayable text
  instead of crashing the chat.
- **`src/agent/tool_loop.py`** (NEW, pure): `run_tool_conversation` — the loop.
  No Streamlit, no SDK imports; the provider "turn" and executor are injected, so
  it's unit-testable with a scripted fake. Neutral message shape:
  `{role, content:[{type:"text"|"tool_call"|"tool_result", …}]}`. Step-capped.
- **`src/agent/providers.py`**: added `gemini_tool_turn` + `claude_tool_turn` —
  each translates neutral messages ⇄ its SDK's native tool protocol, does ONE
  round-trip, returns either `{text}` or `{tool_calls}`. Claude threads a
  `base_url` so an enterprise endpoint (Vertex/Bedrock) can be pointed at later.
- **`src/config.py`**: `LLM_BACKEND` picks a named profile from `BACKEND_PROFILES`;
  `build_llm_arsenal_for_profile` builds the combo rotation, each combo now
  carrying `base_url`. The `dev` profile reproduces today's Gemini-first-then-Claude
  behavior exactly. A `prod` profile (one company key + enterprise `base_url`) drops
  in later with NO code change.
- **`src/agent/caller.py`**: `call_agent` now drives `run_tool_conversation` over
  the neutral history + `LLM_ARSENAL`, binding each combo to its turn adapter and
  **rotating Gemini→Claude on quota/permission errors** — the tool path fails over
  at last. `generate()`/`probe_health()` unchanged.
- **`src/ui/tabs/chat.py`**: the goal path's synthetic continuity turns now use the
  neutral shape (was Gemini `{role, parts}`) so follow-ups replay cleanly.
- **`src/utils/persistence.py`**: `chat_history` (now neutral, already JSON-safe) is
  saved verbatim; `is_neutral_history` guards load so a pre-4.5 saved session is
  discarded rather than replayed into the loop.
- **Default behavior is identical to Phase 4** (no Anthropic key ⇒ Gemini-only).
- **Deferred to Phase 5 (documented, not gaps):** `tools.py` is NOT re-anchored onto
  canonical levers — `execute_tool`'s catch is only a safety net; a tool invoked on
  canonical data still returns an error string. Conversational "can't run on this
  dataset" messaging + choosing the prod host are Phase 5+.
- Verified: all 20 no-network suites green (incl. new `test_tool_specs`,
  `test_tool_loop`, `test_config`, `test_call_agent_boot`); app boots through the
  chat wiring with **zero exceptions** on canonical data via `AppTest`.

### 2026-07-05 — Intelligence Layer, Phase 4: Re-anchor + wire canonical data
The app now runs on the **canonical FeatureMatrix** instead of the hardcoded
Instacart path — the point where Phases 1–3 stop being inert and start powering
the app. Every scoring surface is now lever-agnostic: it reads which loyalty
levers exist from the data's availability map, never a fixed column list.
- **`src/data/levers.py`** (NEW, pure): `SCORING_LEVERS` (higher-is-better RFM +
  optional features; recency/avg-gap excluded — those are churn, not loyalty),
  `LEVER_LABELS`, `active_levers(matrix)`, `default_weights`, `renormalize_weights`
  (drops unavailable levers, rescales to 1.0, equal-weight fallback on all-zero).
- **`src/data/app_data.py`** (NEW): the single wiring seam. `features_from_matrix`
  aliases `customer_id`→`user_id` so legacy consumers/tools keep working and
  returns `(features, available, active_levers)`. `load_demo_app_data()` prefers
  committed canonical artifacts, else falls back to the demo adapter reading raw
  CSVs.
- **`scripts/build_canonical_artifacts.py`** (NEW) + committed
  `data/artifacts/canonical/` (**35MB**: `features.parquet` = the per-customer
  matrix, `availability.json`, slim `orders.parquet`). **Design change vs the
  plan:** we commit the *computed matrix*, NOT the raw `order_items` table — that
  is ~293MB for Instacart (over GitHub's 100MB limit) and its only committed
  consumers (optional features) are already baked into the matrix. Item-level
  surfaces (happy-path) degrade where items aren't shipped; `order_items` is
  `None` on the artifact path.
- **Re-anchored engine:** `scoring.get_thresholds(power, regular, feature_cols=None)`
  derives comparison columns from the frame (skips absent, no `KeyError`);
  `metrics.calculate_churn_risk` uses `recency_days` (RFM) with an
  `avg_days_between_orders` legacy fallback and an id-column-agnostic lookup;
  `simulation.simulate_campaign(..., levers=None)` accepts the dataset's active
  levers. `app.py` loads via `app_data`, defaults weights from active levers, and
  stores `available`/`active_levers`. `sidebar.py` renders one weight slider per
  active lever (labels from `LEVER_LABELS`), renormalized at scoring time.
- **Degradation, not deletion:** the 5 legacy dashboard tabs
  (Overview/Scoring/Segments/Happy Path/Interventions) key on Instacart columns
  that canonical data lacks. `src/ui/tabs/_guard.py` (`needs_columns`) makes each
  show a "not available for this dataset — use AI Chat" info card instead of a
  traceback. **Deep re-anchoring of these tabs' charts + `tools.py` column names
  is deliberately deferred to Phase 7** (the chat-first shell deletes these tabs,
  so re-skinning them now is throwaway).
- **Also fixed (pre-existing, out of the plan):** a restored *artifact* chat
  message crashed `renderer.render_message` (its binary payload doesn't
  round-trip through the JSON session store) — now guarded, honoring the stated
  "persistence must never crash the app" convention.
- Verified: all 21 no-network suites green (incl. new `test_levers`,
  `test_app_data`, `test_metrics`); app boots through **every tab with zero
  exceptions** via `streamlit.testing.AppTest` on canonical data (HTTP 200 alone
  hid a tab crash — AppTest surfaced it); the full analysis engine (score →
  power/regular → thresholds → recency-churn → simulation) runs end-to-end on the
  206,209-customer canonical demo.
- Note: on the demo, recency-churn flags ~92% at-risk — a synthetic-date artifact
  of the Instacart demo (no real order timestamps), not a bug; meaningful on a
  client's real dates.

### 2026-07-03 — Intelligence Layer, Phase 3: Ingestion pipeline
Built the upload path + malfunction firewall so a client's own CSV/Excel becomes
canonical data (spec §3; plan: docs/superpowers/plans/2026-07-03-ingestion-pipeline.md).
New package `src/data/ingest/` (all pure / Streamlit-free):
- **`reader.py`** — CSV/Excel → all-string DataFrame; sniffs encoding (BOM +
  utf-8/latin-1 fallback) and delimiter. Reads every cell as `str` so raw
  amounts/dates/ids survive verbatim to the validator.
- **`profiler.py`** — per-column profile (guessed kind, ≤5 samples, %null,
  %unique-of-non-blank, deterministic random sampling); the ONLY thing the mapper
  sends to the LLM — never the full dataset. (The profile includes ≤5 example
  values per column, so a few real cell values — possibly PII — do reach the LLM;
  the bulk of the data never leaves the machine. Sample masking is a Phase 4+
  option.)
- **`mapper.py`** — `propose_mapping` (injected `generate_fn`; drops hallucinated /
  non-string headers) with a deterministic `fuzzy_map` fallback (global-best
  header→field assignment) so mapping works with zero LLM.
- **`validator.py`** — the firewall: strips `$`/commas, reads `(50.00)` accounting
  notation as negative, clips negatives to 0 with a warning, parses dates, rejects
  (with human messages naming the column + % bad, never a stack trace) on unmapped
  or absent-in-file columns, empty files, >10% unparseable date/amount, or zero
  surviving rows; builds `order_items` only for mapped optional columns (no all-None
  columns that would fool Phase 1's availability tagging).
- **`builder.py`** — validate → dedupe orders on order_id (order-grained: amount is
  a repeated per-order total; warns if a file looks line-grained) → Phase-1
  `build_feature_matrix`; returns a plain result dict (ok/errors/warnings/orders/
  order_items/matrix) so the UI never catches exceptions.
- **`mapping_store.py`** — persist the confirmed mapping recipe keyed by a header
  fingerprint (`.app_state/mappings.json`); same-shaped re-upload reuses it. No raw
  rows at rest; best-effort (tolerates a corrupt/non-dict store), never raises.
- Scope (narrow): pure pipeline + persistence + tests only. The Streamlit confirm
  screen, upload UI, and app wiring are Phase 4 integration — app.py untouched.
- Tests: `tests/test_ingest.py` (reader/profiler/mapper/validator/builder — the
  firewall contract, 78 checks) + `tests/test_mapping_persist.py` (9). No network.
  Existing canonical (52), demo-adapter (40), scoring (6), simulation (21) suites
  still green.

### 2026-07-02 — Intelligence Layer, Phase 2: Instacart demo adapter
Instacart now flows into the canonical shape through the same pipe a client
upload will (spec §6; plan: docs/superpowers/plans/2026-07-02-demo-adapter.md).
- **`src/data/demo/instacart.py`** (NEW, pure / Streamlit-free): `reconstruct_order_dates`
  (cumulative-sum days_since_prior_order from a fixed anchor), `assign_synthetic_prices`
  (deterministic per-product prices — Instacart has no money; REVENUE_IS_SYNTHETIC
  flag), `build_canonical_orders` (prior-only, synthetic order_amount),
  `build_canonical_order_items` (product/category lines, quantity 1), `to_canonical`
  orchestrator, and `load_demo_canonical(data_dir)` reading the 4 CSVs -> canonical
  tables + a Phase 1 FeatureMatrix.
- The demo is the RICH dataset: end-to-end it produces a Full FeatureMatrix
  (all core + optional features available), verified against hand-computed values.
- Scope (narrow): adapter + tests only. app.py untouched, parquet artifacts NOT
  rebuilt — get_app_data() still the live path. App wiring + canonical artifact
  rebuild is a later integration step.
- Tests: `tests/test_demo_adapter.py` — date reconstruction, price determinism,
  canonical tables, end-to-end composition through build_feature_matrix, and a
  CSV round-trip via load_demo_canonical (temp-dir fixtures, no 690MB read).
  No network. Existing suites (canonical 52, scoring, simulation) still green.

### 2026-07-02 — Intelligence Layer, Phase 1: Canonical data model
Added the one internal data shape every surface will read from (spec:
docs/superpowers/specs/2026-06-26-intelligence-layer-byod-design.md; plan:
docs/superpowers/plans/2026-07-02-canonical-foundation.md).
- **`src/data/canonical.py`** (NEW, pure / Streamlit-free): canonical `orders`
  + `order_items` contracts; `FeatureMatrix` (per-customer frame + per-feature
  `available` map with `is_available` / `available_features`); `build_core_features`
  (RFM core from orders alone — recency/frequency/monetary/AOV/tenure/avg-gap,
  all always available; avg-gap vectorized as span/(n-1) for 200k-customer scale),
  `build_optional_features` (category_diversity/avg_basket_size/reorder_rate, each
  tagged available only when its column exists; items merge dedups order_id to
  prevent basket fan-out), and `build_feature_matrix(orders, order_items=None)`
  merging both.
- Availability tagging is the "never malfunctions" mechanism: orders-only input
  tags all optional features unavailable; downstream phases degrade on the tag,
  never on a raw column name. Module assumes ALREADY-VALIDATED input (the
  ingestion-validator firewall is a later phase).
- Tests: `tests/test_canonical.py` — the trust contract (feature math on a
  hand-computable fixture + availability across orders-only / full / partial /
  edge / duplicate-order_id inputs; 52 checks). No network. Existing suites
  (scoring, simulation) still green.
- Scope: model + builder + tests only. App still runs the old Instacart path;
  demo adapter / ingestion / re-anchoring / degradation / persistence are the
  next phases (Phases 2-6).

### 2026-06-23 — Proactive Analyst, Phase 6: Triggered Proactivity (Watches)
Completed the roadmap: the agent now watches metrics you care about and speaks
up only when a line you set is crossed.
- **`src/agent/watches.py`** (NEW, pure / Streamlit-free): `WATCHABLE_METRICS`
  (churn risk %, at-risk power users, power-user cutoff, largest segment gap —
  each computes a deterministic value from an analysis snapshot dict via the
  existing analysis funcs), `evaluate_watches(watches, snapshot)` (fires on
  strict above/below; templated message; `error` severity for upward breaches
  of churn/at-risk-power, else `warning`; an unavailable metric never fires),
  and a best-effort JSON store at `.app_state/watches.json`
  (`load_watches`/`add_watch`/`remove_watch`, like `memory.py`). Watches
  persist across restart; no LLM in the path.
- **`src/ui/sidebar.py`**: a "🔔 Watches" section — a form to add one (metric /
  above-below / threshold) plus a list of current watches each with a delete
  button.
- **`app.py`**: `render_watch_alerts()` assembles a snapshot from
  `session_state` and renders fired watches as `st.error`/`st.warning` banners
  above the tabs, so an alert shows on whatever tab you're on. Guards on
  analysis readiness; best-effort (never crashes).
- Grounding unchanged: every number is deterministic; alert text is templated.
- Tests: `tests/test_watches.py` (metric math, fire logic incl. strict
  inequality + unavailable-metric, persistence round-trip + bad-input guards).
  No network. Full suite green; app boots headless HTTP 200.
- Scope: 4 metrics, structured-form input, banner surface — no NL parsing, no
  background scheduling, no alert history, no new tab. Phase 6 completes the
  Proactive Analyst roadmap.

### 2026-06-19 — Phase 5: Provider Abstraction (Gemini → Claude failover)
Gemini daily-quota exhaustion is no longer a hard wall for text/reasoning calls.
- **`src/config.py`**: loads `ANTHROPIC_API_KEY`, adds `CLAUDE_MODELS`
  (`claude-haiku-4-5-20251001`) and a pure `build_llm_arsenal(...)`; `LLM_ARSENAL`
  = Gemini combos first, then Claude combos (only if an Anthropic key exists).
  `MODEL_ARSENAL` kept as the Gemini-only subset.
- **`src/agent/providers.py`** (NEW, no Streamlit): `gemini_generate_text` /
  `claude_generate_text` adapters (Claude system prompt cached, anthropic SDK
  imported lazily) + pure `is_eligible` (tool calls are Gemini-only) and
  `provider_text` (dispatch by provider).
- **`src/agent/caller.py`**: `generate()` rotates over `LLM_ARSENAL`; tool-less
  text calls dispatch via the adapters and fall through Gemini→Claude on
  exhaustion; the Gemini tool path (`call_agent`) is unchanged and stays
  Gemini-only.
- **`requirements.txt`**: added `anthropic`.
- **`src/ui/sidebar.py` / `src/ui/tabs/chat.py`**: combo counters now reflect the
  full `LLM_ARSENAL`.
- Boundary: only the narration/reasoning layer fails over to Claude; the reactive
  tool-using chat still needs Gemini. Grounding unchanged.
- Graceful degradation: no Anthropic key ⇒ `LLM_ARSENAL == MODEL_ARSENAL` ⇒
  identical to before.
- Tests: `tests/test_providers.py` (arsenal build, eligibility, dispatch,
  simulated failover). No network. Full suite green; app boots HTTP 200.

### 2026-06-19 — Agentic Chat (chat absorbs Autopilot)
Made the AI Chat a real agent and retired the separate Autopilot tab.
- **`src/agent/router.py`** (NEW, pure): `route(message)` classifies each message
  as a quick `answer` or a multi-step `goal` via one small LLM call under
  `ROUTER_SYSTEM`; defaults to `answer` on any failure (safe + cheap).
- **`src/config.py`**: added `ROUTER_SYSTEM`.
- **`src/ui/tabs/chat.py`**: free-form messages are routed — `answer` → the
  existing reactive `call_agent`; `goal` → the reflexive loop
  (`run_reflexive`) run inline with live 🧠 reason / ▶️ action, then
  `synthesize_goal`; the summary lands in the conversation and a synthetic
  `{user,goal}/{model,summary}` pair is pushed into `chat_history` so follow-ups
  have context. The consolidated "📦 Deliverables" panel moved here from the
  Autopilot tab.
- **`app.py`**: dropped from 7 tabs to 6 — the Autopilot tab is removed.
- **Deleted `src/ui/tabs/autopilot.py`** — its engine (`orchestrator`) is reused
  by the chat unchanged.
- Grounding unchanged: routing is a judgment call (no business numbers); the loop
  and tools stay grounded.
- Tests: `tests/test_router.py` (classification + default-to-answer). No network.
  Full suite green; app boots headless HTTP 200. Quick-action buttons still call
  `call_agent` directly (deliberate single actions, no routing).
- Gemini-only; provider abstraction is still a later phase.

### 2026-06-19 — Proactive Analyst, Phase 4: What-If Simulation
Gave the agent a grounded campaign simulator — it can now project the impact of a
behavioral lift before you run the campaign.
- **`src/analysis/scoring.py`**: refactored into `compute_scaler` (fit caps +
  max_raw) and `apply_scoring` (score with a *provided* scaler); `score_users`
  now delegates to them and is behavior-identical. This lets a hypothetical
  population be scored on the baseline's frozen yardstick.
- **`src/analysis/simulation.py`** (NEW, pure): `LEVERS` (the 5 weighted scoring
  features) + `simulate_campaign(features, weights, top_pct, feature, lift_pct)`
  — lifts one feature for regular users only, re-scores with the frozen scaler,
  and counts how many clear the original cutoff. Returns conversions +
  projected power count/% + the feature's before→after average. `reorder_rate`
  is clipped to ≤ 1.0; the lifted column is cast to float first (pandas 2.x
  refuses to write floats into an int column).
- **`src/agent/tools.py`**: `simulate_campaign(feature, lift_pct)` tool — validates
  the lever + range, calls the engine, renders a 🔮 card, returns a
  narrate-only-these-numbers instruction. Added to `ALL_TOOLS`.
- **`src/agent/orchestrator.py`**: registered in `TOOL_REGISTRY` so Autopilot can
  plan it.
- Grounding unchanged: the engine computes every number; the LLM only narrates.
- Tests: `tests/test_scoring.py` (refactor + frozen-scaler property),
  `tests/test_simulation.py` (conversions, monotonicity, clip, shape). No network.
  Full suite green; app boots headless HTTP 200.
- Scope: single-feature lever, regulars only, % lift, conversions + deltas only —
  no churn modelling, no new tab. Gemini-only; provider abstraction is Phase 5.

### 2026-06-18 — Proactive Analyst, Phase 3: Memory / Continuity
Gave the briefing a durable, cross-session memory so it stops being amnesiac.
- **`src/agent/memory.py`** (NEW, Streamlit-free, best-effort like
  `persistence.py`): a JSON store at `.app_state/agent_memory.json` holding the
  last briefing `snapshot` (signal id/severity/headline + params + when) and an
  `action_log`. Pure logic: `diff_signals` (new / still_present / resolved, each
  with an `acted_on` flag via `ACTION_SIGNAL_MAP`) and `continuity_line`
  ("Since last session: churn risk is still present (you've already acted on
  it)…"). I/O: `load_memory`, `record_snapshot` (overwrite-guarded by params),
  `record_action`, `clear_memory`.
- **`src/config.py`**: added `MEMORY_SYSTEM` — narrate continuity ONLY from the
  given note, never invent prior sessions.
- **`src/agent/proactive.py`**: `get_briefing` now loads memory, diffs, prepends
  the deterministic continuity line to the digest, narrates under
  `MEMORY_SYSTEM`, and records the new snapshot — all on the cache-miss path, so
  reruns neither re-call the model nor re-record. New `load_memory_fn`/
  `record_snapshot_fn` seams keep tests off disk.
- **`src/agent/tools.py`**: the three deliverable tools log their action.
- **`src/ui/sidebar.py`**: "🧠 Forget what you remember" button clears memory.
- Tests: `tests/test_memory.py` (pure logic + disk round-trip), updated
  `tests/test_proactive.py` (continuity + snapshot). No network. App boots
  headless HTTP 200.
- Provider stays Gemini-only; provider abstraction is still Phase 5.

### 2026-06-16 — Proactive Analyst, Phase 2: Reflexive Autopilot
Turned the Autopilot from open-loop (plan everything upfront, execute blindly)
into a closed "Grounded ReAct" loop. It now runs one step, reads the real numbers
that step produced, and decides the next move — adapting, digging deeper, or
stopping early — with its reasoning shown live.
- **`src/agent/orchestrator.py`**: added `run_reflexive(goal, status_callback,
  generate_fn)` — the loop — plus `decide_next_step` (one grounded Gemini call
  returning a single JSON decision or `done`), `_digest_history` (pure: flattens
  prior steps' scalar result fields — the ONLY numbers the controller may cite),
  `_parse_decision`, and guardrails: scoring forced first, `MAX_STEPS=6`,
  no-repeat of an identical (tool,args), and a parse-fallback to the unrun
  remainder of `DEFAULT_PLAN` after two unusable decisions. The old
  `plan_goal`/`execute_plan` stay (still tested) but are no longer the primary
  path.
- **`src/config.py`**: added `REFLEXIVE_SYSTEM` — choose only catalog tools,
  cite only digest numbers, never invent, stop when the goal is met.
- **`src/ui/tabs/autopilot.py`**: the run now shows 🧠 reasoning then ▶️ action
  per step in the live `st.status` log; summary and deliverables unchanged.
- Tests: `tests/test_reflexive.py` (no network) covers the digest, the decision
  parser, `decide_next_step`, and the loop (scoring-first, step cap, no-repeat,
  parse-fallback, status callback). All existing suites still pass; app boots
  headless HTTP 200.
- Provider stays Gemini-only; provider abstraction is still Phase 5.

### 2026-06-12 — Proactive Analyst, Phase 1: Proactive Briefing
Turned the chat agent from reactive to proactive. The moment analysis has run,
the AI Chat tab now opens with a "💡 Today's Briefing" panel: a grounded
narrative plus up to 4 signal cards, each with a one-click action button that
hands a tailored prompt to the existing agent.
- **`src/agent/insights.py`** (NEW, pure/Streamlit-free): `detect_signals(...)`
  reuses the analysis layer (`calculate_churn_risk`, `compute_segment_gaps`,
  `compute_intervention_gaps`+`INTERVENTION_TEMPLATES`, `get_happy_paths`) to
  build churn / segment_gap / intervention / power_value / happy_path signals,
  each `{id,severity,icon,headline,detail,action_label,action_prompt}`, sorted
  by severity, capped at 4. `briefing_digest(signals)` flattens them to plain
  text. Every number is deterministic — the LLM only narrates.
- **`src/config.py`**: added `PROACTIVE_SYSTEM` — narrate ONLY the digest's
  numbers, 2-3 sentences, end with the most urgent recommendation.
- **`src/agent/proactive.py`** (NEW): `get_briefing()` reads `scored_df`/
  `power`/`regular`/`power_user_ids`/`full_data`/`features` from session_state,
  detects signals, narrates via the existing `generate()`, caches the narrative
  keyed by `(top_pct, churn_days, len(scored_df))`, and falls back to a
  deterministic templated briefing on any LLM failure. `generate_fn`/`state`
  are injectable for testing.
- **`src/ui/tabs/chat.py`**: `render_briefing()` in a "Today's Briefing"
  expander above the conversation; cards reuse the existing
  `_handle_quick_action(action_prompt)` route (no new execution path).
- Tests: `tests/test_insights.py` (16 checks), `tests/test_proactive.py`
  (12 checks, no network). All existing no-network tests still pass; app boots
  headless HTTP 200. (Browser visual of the cards still wants a human glance.)
- Provider stays Gemini-only; provider abstraction is deferred to Phase 5.

### 2026-06-11 — Recolor: navy + cream + red palette
Reskinned the whole app onto a 4-color palette while keeping the neo-brutalist
structure and chart readability:
- **Tokens:** canvas navy `#002F49`, lifted surfaces `#0A3D5C`, deep inset
  `#00263C`, cream "ink" `#FEF0D5` (every border/shadow/text/axis), interactive
  red `#C1121F`, structural oxblood `#780001`. Cream is now the single line color
  and also the on-accent text (all accents are dark-red, so cream reads on them).
  Rewrote `:root` in `renderer.py`, the palette consts, the intervention-card
  severity ramp (oxblood→`#8E1D1D`→red), `color_ratio` (teal), the `app.py`
  header block, and `.streamlit/config.toml`.
- **Charts (kept fully legible):** panels are the lifted navy with cream axes and
  near-black-navy `#00141F` mark outlines. Fills use brand red + cream plus three
  harmonious helpers so multi-series stay distinct — 5-tier bar =
  steel·teal·amber·orange·red; 2-series bar + donut = red vs cream; single bars =
  red / teal / amber / steel across overview, scoring, segments, happy_path.
- All touched files byte-compile; app boots headless HTTP 200. (Visual look +
  onboarding dialog still want a human glance in the browser.)

### 2026-06-08 — Agentic tools + Autopilot
Turned the chat agent into a goal-driven agent with downloadable deliverables.
- **Deliverable tools** (`src/agent/deliverables.py` pure builders +
  `src/agent/tools.py` wrappers): `export_target_list` (CSV of target users),
  `draft_campaign_emails` (markdown drafts), `build_action_plan` (dated
  checklist). Each stores a downloadable artifact in
  `st.session_state.artifacts` and appends a `type="artifact"` chat entry.
- **Autopilot** (`src/agent/orchestrator.py` + `src/ui/tabs/autopilot.py`,
  new 7th tab): a goal is planned by Gemini into a JSON tool plan
  (`plan_goal`, with a parse fallback ladder to `DEFAULT_PLAN`), executed
  step-by-step with a live `st.status` log (`execute_plan`), then summarized
  (`synthesize_goal`). `TOOL_REGISTRY` is the shared catalog/executor source.
- **Caller refactor:** extracted `generate()` (key×model failover) from
  `call_agent`; chat and orchestrator now share it.
- Tests: `tests/test_deliverables.py`, `tests/test_orchestrator.py` (no network).
  App boots headless HTTP 200.

### 2026-06-04 — Neo-brutalist theme → DARK variant
Flipped the brutalist theme from light/cream to **dark**, keeping the same pop
color scheme (red/yellow/violet/mint):
- **Canvas:** near-black `#141416` + faint light dot-grid; surfaces `#1F1F23`.
- **Ink:** off-white `#F5F2E6` for borders, hard offset shadows, and body text
  (so the brutalist outline/shadow reads on a dark bg). Bright accent blocks
  (h2, primary/download buttons, selected tab, badges, code) keep **dark**
  (`#0A0A0A`, `--on-accent`) text + borders for contrast.
- Charts: dark panel fill `#1F1F23`, off-white axes/grid; bars stay bright
  accents with black strokes. `.streamlit/config.toml` base flipped to `dark`
  so Streamlit-internal widgets (dataframe, dropdowns) match.
- Same files as the redesign below + `.streamlit/config.toml`. Booted HTTP 200.

### 2026-06-04 — Drastic redesign → NEO-BRUTALIST POP
Replaced the dark "calm glass aurora" look with a loud neo-brutalist theme
(chosen from the ui-ux-pro-max library). Originally light/cream; see the dark
variant entry above for the current canvas.
- **Canvas:** cream `#FFFDF5` with a faint pop dot-grid; ink `#0A0A0A` text.
- **Palette:** hot red `#FF5C5C`, vivid yellow `#FFD93D`, soft violet `#B9A4FF`,
  mint `#3DDC84` — solid color blocking, no gradients/blur.
- **Borders/shadows:** 4px black borders + hard offset shadows (`6/8px 0`, no blur).
  Buttons/tabs/metrics use a mechanical press (translate on click).
- **Type:** Space Grotesk (display) + Space Mono (labels/data), replacing Inter.
- All Altair charts recolored to solid brutalist fills with 2px black strokes on a
  white panel; `color_ratio()` and the intervention cards rebuilt in the new key.
- Files touched: `src/ui/renderer.py` (full `apply_theme` + card + chart helpers),
  `app.py` (header block), and the chart blocks in `tabs/{overview,scoring,segments,happy_path}.py`.
- Booted headless cleanly (HTTP 200). Light-first only — no dark mode.

### 2026-06-04 — Published to GitHub + doc cleanup
- Created public repo **github.com/YASHWARDHAN1011/customer-loyalty-agent** and pushed everything.
- Removed stray `Tempsl` junk files from tracking and gitignored them.
- Fixed `tests/test_data.py` (it pointed at a nonexistent `data/raw/`; now checks
  the real `data/instacart/` and samples big files so it runs fast).
- Rewrote this file to be readable and to carry this journal.

### 2026-06-04 — Four "ship-ready" features
Goal: make the app demo-ready and deployable. Built in this order:

1. **Cloud deploy readiness.** The raw CSVs are ~690MB and can't go to the cloud,
   so `scripts/build_artifacts.py` precomputes three small parquet files into
   `data/artifacts/` (~25MB total, committed). The app now calls
   `get_app_data()`, which loads those parquets when present and falls back to the
   raw CSVs locally. Secrets read from `st.secrets` (cloud) then `.env` (local).
   `requirements.txt` was replaced with a clean minimal list. Added
   `.streamlit/config.toml` + `secrets.toml.example`.
2. **Staged loading.** "Run Full Analysis" now shows a step-by-step status log
   (scoring → top % → thresholds) instead of one vague spinner.
3. **Onboarding wizard.** First-time visitors get a 3-step welcome dialog that
   ends by running an initial analysis. A "Replay tour" button lives in the sidebar.
4. **Persistent chat memory.** The AI chat now survives a restart (saved to
   `.app_state/chat_session.json`); a "New conversation" button clears it.

Specs for the above live in `docs/superpowers/specs/`.

### 2026-06-04 — UI polish ("calm, seamless glass")
- Removed the animated WebGL shader background → a still aurora gradient.
- Stopped entrance animations from replaying on every Streamlit rerun (the page
  no longer "jumps" when you click).
- Slimmed the heavy glass shadows, calmed hover effects, and re-tinted the icon
  chips so they match the background.

---

## Running the app

The venv lives in the **outer** directory; launch from **this (inner)** directory
because data paths are resolved relative to it.

```powershell
# From customer-loyalty-agent/customer-loyalty-agent/
..\venv\Scripts\python.exe -m streamlit run app.py
```

On first run the app reads `data/artifacts/*.parquet` if present (fast). To
(re)build those artifacts from the raw CSVs:

```powershell
..\venv\Scripts\python.exe scripts/build_artifacts.py
```

## Running tests

Standalone scripts (not pytest); each exits non-zero on failure:

```powershell
..\venv\Scripts\python.exe tests/test_data.py         # raw CSVs present & parse
..\venv\Scripts\python.exe tests/test_artifacts.py    # parquet artifacts + get_app_data()
..\venv\Scripts\python.exe tests/test_persistence.py  # chat save/load/clear round-trip
..\venv\Scripts\python.exe tests/test_gemini.py       # smoke-tests Gemini API
..\venv\Scripts\python.exe tests/test_streamlit.py    # Streamlit session state
```

## Environment

API keys live in **`.env` in this directory** as `GEMINI_KEY_1` … `GEMINI_KEY_N`
(up to 10), plus an optional `ANTHROPIC_API_KEY`. `src/config.py` reads each via
`_get_secret()` — which checks `st.secrets` first (Streamlit Cloud) then
`os.getenv` (local `.env`). It builds `MODEL_ARSENAL` (every Gemini key × model
combination) and `LLM_ARSENAL` = those Gemini combos followed by Claude combos
(appended only when `ANTHROPIC_API_KEY` is set). `generate()` rotates over
`LLM_ARSENAL`, so when Gemini quota is exhausted the text/reasoning calls fail
over to Claude. With no Anthropic key, `LLM_ARSENAL == MODEL_ARSENAL` and
behavior is unchanged.

Core dependencies (see `requirements.txt`): `streamlit`, `pandas`, `numpy`,
`altair`, `google-generativeai`, `anthropic`, `python-dotenv`, `pyarrow`.

Runtime state (gitignored) lives in `.app_state/`: `onboarding.json` (first-run
flag) and `chat_session.json` (saved chat).

## Deployment (Streamlit Community Cloud)

1. Push to GitHub (already done).
2. New app → point at this repo, main file `app.py`.
3. In the app's **Secrets**, add `GEMINI_KEY_1 = "..."`.
The committed parquet artifacts supply the data, so no CSV upload is needed.

## Architecture

**Entry point:** `app.py` — calls `get_app_data()`, initialises `st.session_state`,
restores any saved chat, shows onboarding, then renders the sidebar and 6 tabs.

### Data pipeline (`src/data/loader.py`)

Pure functions hold the pandas logic (no Streamlit) so the artifact builder can
reuse them; `@st.cache_data` wrappers are thin shells:

- `_merge_raw()` / `load_data()` → merge the 5 Instacart CSVs into `orders` and
  `full_data` (line items with department labels).
- `_compute_features(...)` / `build_features(...)` → one-row-per-user matrix:
  `total_orders, avg_days_between_orders, reorder_rate, dept_diversity,
  avg_basket_size, total_items`.
- `get_app_data()` → returns `(orders, full_data, features)`. Prefers
  `data/artifacts/*.parquet`; falls back to raw CSVs + feature computation.
  In the artifact path `full_data` holds only early orders (`order_number <= 5`,
  the max sidebar lookback) to keep the parquet small.

### Analysis layer (`src/analysis/`)

No Streamlit imports — pure Python, independently testable.

| Module | Key exports |
|--------|-------------|
| `scoring.py` | `score_users(features, weights)`; `get_power_users(scored_df, top_pct)` → `(power, regular, cutoff)`; `get_thresholds(power, regular)` |
| `segmentation.py` | `compute_segment_gaps(power, regular)`; `build_comparison_data(gaps)` |
| `happy_path.py` | `get_happy_paths(full_data, power_user_ids, lookback, top_n)` |
| `interventions.py` | `INTERVENTION_TEMPLATES`; `compute_intervention_gaps(power, regular)` |
| `metrics.py` | `calculate_churn_risk(features, power_user_ids, churn_days)` |

### AI agent (`src/agent/`)

- **`caller.py`** — `generate()` rotates over `LLM_ARSENAL` via
  `model_idx % len(LLM_ARSENAL)`, advancing `model_idx` and rolling back
  `ui_history` on quota/permission/not-found errors. **Tool-less text calls**
  dispatch to a provider adapter and fail over Gemini→Claude; the **tool-using
  chat** (`call_agent`, automatic function calling) is Gemini-only and uses the
  inline chat path unchanged.
- **`providers.py`** — `gemini_generate_text` / `claude_generate_text` adapters
  (one non-streaming text call each), plus pure `is_eligible` (tool calls are
  Gemini-only) and `provider_text` (dispatch a tool-less call to the combo's
  provider). The `anthropic` SDK is imported lazily.
- **`tools.py`** — functions in `ALL_TOOLS` that Gemini calls via function calling;
  each reads/writes `st.session_state` and appends to `ui_history`.

### UI layer (`src/ui/`)

- **`renderer.py`** — `apply_theme()` (CSS + static aurora background);
  `render_message(msg)` renders `ui_history` entries (text / table / Altair chart);
  `render_intervention_card(...)`; `color_ratio(val)`.
- **`sidebar.py`** — `render_sidebar(features, orders, run_btn_callback)`: weight
  sliders, `top_pct`/`lookback` dropdowns, "Run Full Analysis", exports,
  "Replay tour", and Reset.
- **`onboarding.py`** — `maybe_show_onboarding(run_analysis)` (3-step `@st.dialog`
  first-run tour) and `start_tour()`.
- **`tabs/`** — one module per tab (`overview`, `scoring`, `segments`, `happy_path`,
  `interventions`, `chat`). Tabs read only from `st.session_state`.

### Persistence & Export

- **`src/utils/persistence.py`** — `save_session()` / `load_session()` /
  `clear_session()` over `.app_state/chat_session.json`. Serializes chart
  DataFrames to records and Gemini history to `{role, text}` (tool-call protobufs
  are not round-tripped).
- **`src/export/generator.py`** — `generate_csv_export()` (adds a `loyalty_tier`
  column); `generate_summary_report()` (markdown).

## Key session state variables

| Key | Type | Set by |
|-----|------|--------|
| `features` / `full_data` | DataFrame | `app.py` (`get_app_data`) at startup |
| `scored_df` | DataFrame | scoring / tools |
| `power` / `regular` | DataFrame | scoring |
| `cutoff` | float | scoring |
| `thresholds_df` | DataFrame | scoring |
| `power_user_ids` | set | scoring |
| `top_pct` / `lookback` | int | sidebar / tools |
| `weights` | dict | sidebar (5 keys summing to 1.0) |
| `model_idx` | int | `caller.py` (failover counter) |
| `chat_history` | list | `caller.py` (Gemini history) |
| `ui_history` | list[dict] | chat tab (rendered messages + inline charts) |
| `session_loaded` | bool | `app.py` (restore-once guard) |
| `show_onboarding` / `onboarding_step` / `onboarding_run` | various | onboarding flow |

A `ui_history` entry has `role`, `type` (`"text"`, `"table"`, or `"chart"`), plus
`content` (text) or `data`/`chart_type`/`x`/`y`/`color` (table/chart).

## Conventions

- Keep `src/analysis/` Streamlit-free.
- `@st.cache_data` functions prefix large DataFrame args with `_` to skip hashing.
- `LLM_ARSENAL` entries are `{"provider", "key", "model", "label"}` (`MODEL_ARSENAL`
  is the Gemini-only subset); `model_idx` wraps with `% len(LLM_ARSENAL)`. Claude
  combos are eligible only for tool-less text calls.
- Persistence and onboarding state are best-effort and must never crash the app.
- **Keep this journal updated**: when you make a notable change, add a dated entry
  at the top of the Project Journal.
