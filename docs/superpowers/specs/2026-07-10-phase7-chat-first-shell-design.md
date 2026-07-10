# Phase 7 — Chat-First Shell + Dispatch Ladder

**Date:** 2026-07-10
**Status:** Approved (brainstorming)
**Roadmap:** Chat-first agent roadmap §Phase 7 (build order `4 → 4.5 → 5 → 6 → 7 → 8 → 9`).
**Builds on:** Phase 6 (upload UI / active-dataset seam), Phase 5 (canonical tools),
Phase 4.5 (provider-agnostic tool loop), the existing router/reflexive/proactive stack.

## 1. Purpose

Turn the app from a 6-tab dashboard (where chat is the last tab) into a **chat-first
shell**: chat is the landing page, the 5 analytical tabs collapse into one optional
**"Full numbers"** panel, and every message flows through a **dispatch ladder** — one
ordered decision structure with named extension points for the rungs Phases 8 and 9
add. Scope is MINIMAL: reuse the existing router/`call_agent`/`run_reflexive` for the
two live rungs; the recipe (Phase 9) and grounded-query (Phase 8) rungs are explicit
empty slots that fall through today.

The **trust invariant holds**: the LLM chooses what to do and narrates; every number
is computed deterministically. Phase 7 changes layout and flow, not how figures are
produced.

## 2. Locked decisions (brainstorming 2026-07-10)

| # | Decision |
|---|----------|
| Q1 | **Build a real `dispatch()` abstraction now** with the two live rungs (known-tool, multi-step-goal) + explicit empty slots for recipe (front) and grounded-query (back). Not a deferral. |
| Q2 | **"Full numbers" is a new lean, dataset-agnostic panel** (scored table + segment comparison + key metrics from the canonical engine). The 5 legacy tab modules are **retired**, not wrapped. |
| Q3 | **Single scrolling page, no `st.tabs`.** The page is the chat; "Full numbers", briefing, deliverables are expanders. Sidebar unchanged (plus Q4). |
| Q4 | **Declutter:** API-status metrics move to the sidebar; keep briefing + deliverables; replace the 8 quick-action buttons + examples expander with ~4 starter suggestion chips shown only on an empty conversation. |

## 3. Architecture

### 3.1 Dispatch ladder (`src/agent/dispatch.py`, NEW)

A single entry point the chat calls for every message:

```
dispatch(prompt, *, on_step=None, route_fn=route, agent_fn=call_agent,
         reflexive_fn=run_reflexive) -> DispatchResult
```

Walks the ladder in order, stopping at the first rung that handles the message:

1. **Recipe** — `match_recipe(prompt)` hook returns `None` today (Phase 9 slot).
2. **Known tool** — if `route_fn(prompt)` classifies `"answer"` → `agent_fn(prompt)`;
   `DispatchResult(kind="answer", text=…)`.
3. **Multi-step goal** — if `route_fn(prompt)` classifies `"goal"` →
   `reflexive_fn(goal, status_callback=on_step)`; `DispatchResult(kind="goal",
   history=…, goal=…)`.
4. **Grounded query** — `grounded_query(prompt)` hook returns `None` today (Phase 8 slot).

`DispatchResult` is a small dataclass/dict describing what happened so `chat.py`
renders it (answer text, or a goal run to summarize). `dispatch` imports **no
Streamlit** — the goal rung's live progress is delivered through the injected
`on_step` callback (same pattern `run_reflexive` already uses), keeping the ladder
unit-testable with fakes. The two empty rungs are functions returning `None` so the
walk falls through; Phases 8/9 each replace one hook with a real implementation and
change nothing in `chat.py`.

Today's behavior is preserved exactly: the same `route`→`call_agent`/`run_reflexive`
split the chat uses now, just expressed as one ordered ladder.

### 3.2 Chat-first page (`app.py` + `src/ui/tabs/chat.py`)

`app.py` stops rendering `st.tabs([...])`. Inside the existing Phase-6 gate
(`if not render_confirm_gate(run_analysis):`) the main area becomes a single flow,
rendered by a restructured `render_chat(features, orders)`:

1. Header (dynamic badge) — unchanged, stays at top of `app.py`.
2. `render_watch_alerts()` + `render_upload_notices()` — unchanged banners.
3. `maybe_show_onboarding(run_analysis)` — unchanged.
4. **Briefing** expander (`render_briefing`) — kept.
5. **Conversation**: `ui_history` rendered, then `st.chat_input`. On an empty
   conversation, a compact welcome + a row of **starter suggestion chips** (Q4).
6. **"Full numbers"** expander (§3.3), collapsed by default, below the input.
7. **Deliverables** expander (`_deliverables_panel`) — kept.

Every submitted message (typed or chip) goes through **`dispatch(...)`** (§3.1):
`kind="answer"` appends the text; `kind="goal"` runs the reflexive loop live in an
`st.status` and synthesizes a summary (the existing `_run_goal_in_chat` logic, now
driven by the dispatch result). `save_session()` + `st.rerun()` as today.

`app.py` **removes** the 5 tab render calls; the header, watch alerts, upload notices,
onboarding, sidebar, and upload section all stay.

### 3.3 Full numbers panel (`src/ui/full_numbers.py`, NEW)

`render_full_numbers()` — a best-effort, dataset-agnostic panel rendered inside the
collapsed expander. After analysis has run (`scored_df` present):

- **Key metrics row**: total customers, power-user count + score cutoff, at-risk
  count (recency churn), average loyalty score — from `session_state`.
- **Scored customer table**: `scored_df` sorted by `loyalty_score`, with a CSV
  download via `generate_csv_export()`.
- **Segment comparison**: power vs regular across the dataset's active levers via
  the column-agnostic `compute_segment_gaps` / `build_comparison_data` (bar chart).

Before analysis: a one-line hint (*"No analysis yet — ask the agent to 'score
customers', or use Run Full Analysis in the sidebar."*). Any exception collapses to
the hint rather than crashing the page.

### 3.4 Sidebar API status (`src/ui/sidebar.py`)

A small **"🔌 Model status"** section shows active model / keys loaded / combos
remaining (moved verbatim from the chat's 3-metric row). The chat's upfront
"all keys exhausted" banner (`_render_api_banner`) stays in the chat flow (actionable
warning, not a diagnostic).

## 4. Error handling

- Dispatch never crashes the chat: a rung raising is caught and surfaced as a
  relayable error message (consistent with `execute_tool`'s existing safety net).
- The Full numbers panel and briefing are best-effort (any failure → hint / skip).
- The trust invariant is unchanged — no rung invents a number.

## 5. Out of scope (YAGNI)

- Implementing the recipe (Phase 9) or grounded-query (Phase 8) rungs — empty slots only.
- Re-anchoring the 5 legacy tabs onto canonical columns (they are retired, not fixed).
- Any new analysis math — Full numbers reuses existing `src/analysis/*`.
- Changing the LLM backend / provider selection (Phase 4.5 already did this).
- Persisting a "Full numbers open/closed" preference.

## 6. Testing

Repo convention: standalone `tests/test_*.py` scripts, no pytest, no network;
`streamlit.testing.v1.AppTest` for wiring.

- **`tests/test_dispatch.py`** (new) — the ladder with injected fakes: recipe +
  grounded slots return `None` → fall through; `route`→`"answer"` fires the
  known-tool rung (fake `agent_fn`); `route`→`"goal"` fires the goal rung (fake
  `reflexive_fn`, `on_step` called); order honored; a rung exception is caught.
- **`tests/test_full_numbers.py`** (new) — `AppTest.from_string` on canonical data:
  before analysis (hint shown, 0 exceptions) and after a scoring run (metrics + table
  + chart, 0 exceptions).
- **`tests/test_chat_shell.py`** (new) — `AppTest.from_file("app.py")` boots the
  chat-first app with 0 exceptions on the demo; asserts the chat input exists and no
  6-tab dashboard remains.
- **Regression:** existing no-network suites stay green — especially
  `test_tools_canonical`, `test_upload_flow`, `test_dataset_swap`. Before deleting the
  5 tab modules, confirm nothing else imports them (currently only `app.py` and
  `src/ui/tabs/__init__.py`).

## 7. Files

**New:** `src/agent/dispatch.py`, `src/ui/full_numbers.py`, `tests/test_dispatch.py`,
`tests/test_full_numbers.py`, `tests/test_chat_shell.py`.
**Changed:** `app.py` (drop tabs + 5 render calls, single-page flow, Full-numbers
expander), `src/ui/tabs/chat.py` (route→dispatch; starter chips; drop the 3-metric
row + button wall + examples expander), `src/ui/sidebar.py` (add Model status
section), `src/ui/tabs/__init__.py` (drop the 5 tab imports, keep `chat`).
**Deleted:** `src/ui/tabs/{overview,scoring,segments,happy_path,interventions}.py`.

## 8. Build order

1. `dispatch.py` + `test_dispatch.py` (pure ladder, no UI change yet).
2. `full_numbers.py` + `test_full_numbers.py` (panel in isolation).
3. Retire the 5 tabs: delete modules, trim `__init__.py` + `app.py` imports/calls;
   confirm no other importers.
4. Chat-first re-layout: `app.py` single-page flow + `chat.py` route→dispatch, starter
   chips, chrome removal; wire Full numbers expander.
5. Sidebar Model-status section.
6. Regression sweep (`test_chat_shell` + existing suites) + CLAUDE.md journal entry.
