# Phase 9 — Recipes + Finishing/Hardening Pass: Design

**Date:** 2026-07-13
**Status:** Implemented 2026-07-13 (plan: docs/superpowers/plans/2026-07-13-phase9-recipes-and-hardening.md).
**Roadmap:** `docs/superpowers/specs/2026-07-05-chat-first-agent-roadmap-design.md` §Phase 9 (the LAST roadmap item).
**Builds on:** Phase 8 grounded-query tool (`run_grounded_query` echoes a recipe-shaped `query` dict), Phase 7 chat-first shell + dispatch ladder (the inert `recipe_fn` rung), the existing `.app_state/*.json` best-effort stores (`memory.py`, `watches.py`, `mapping_store.py`).

This spec covers two parts shipped together to finish the project:
- **Part A — Recipes** (the final roadmap feature).
- **Part B — Trust / hardening pass** (no new feature breadth; makes the deliverable presentable and verified).

---

## 1. Purpose

**Part A.** After the grounded-query tool answers a novel question well, let the user **save it as a named, reusable, one-click action** ("recipe"). A recipe stores the *parameterised query* (which tool + arguments), never raw data or generated code. Re-running a recipe recomputes fresh numbers on the current dataset. This closes the roadmap.

**Part B.** Verify and polish the end-to-end product: browser-smoke the live chat flow, prove the bring-your-own-data path on a non-Instacart CSV, pin the optional Claude dependency, and write a presentable README.

### Trust invariant (unchanged, must hold)

> Every figure the user sees is computed deterministically by code over real data. A recipe stores only the query arguments; replaying it runs the same deterministic engine. No stored numbers (never stale), no stored code (nothing executed blindly), no LLM in the replay path.

---

## 2. Locked decisions (from brainstorming, 2026-07-13)

| Decision | Choice | Why |
|---|---|---|
| Recipe scope | **Grounded queries only** | The `query` arg dict is already stored by Phase 8; deterministic replay. Goals (reflexive loop) re-plan via the LLM and wouldn't replay identically — weaker trust, more work. YAGNI. |
| Trigger + management | **One-click chips (chat) + a sidebar "🍳 Recipes" list (Run / 🗑)** | Unambiguous; no NL name-matching to misfire. Mirrors the existing Watches sidebar section. |
| Dispatch `recipe_fn` rung | **Stays inert** | Chips call the tool directly with known args — no routing/matching needed. Consistent with Phase 8 leaving `grounded_fn` inert. Documented hook for a future typed-matching version. |
| Recipe ↔ dataset binding | **Dataset-agnostic storage; graceful degradation** | A recipe references column names. On a *different* uploaded dataset lacking a column, replay yields the engine's clean "No such column…" message, never a crash. Per-dataset scoping is out of scope. |
| Replay LLM narration | **None — render the deterministic card only** | The tool's metric/table/correlation card already shows the real computed numbers. Skipping the LLM makes recipes work even when Gemini quota is exhausted (a feature). |
| Save trigger | **User-confirmed, one-click** (not auto-save) | Per roadmap §7 out-of-scope: no auto-saving every answer, no similarity-based auto-recipe. |

---

## 3. Architecture — Part A (Recipes)

Three units. One new pure store, plus thin wiring into the existing tool wrapper, chat body, and sidebar.

### 3.1 `src/agent/recipes.py` (NEW — pure, Streamlit-free)

Best-effort JSON store at `.app_state/recipes.json`, same shape and guarantees as `watches.py` / `mapping_store.py` (tolerates a missing or corrupt store; never raises; no raw data at rest).

A recipe record:
```python
{"id": "<hex8>", "name": "<user string>",
 "query": { ...the exact run_grounded_query arg dict... },
 "created": "<iso timestamp>"}
```

Functions:
```python
def load_recipes() -> list[dict]: ...          # [] on missing/corrupt store
def add_recipe(name: str, query: dict) -> dict: ...   # returns the stored record
def remove_recipe(recipe_id: str) -> None: ...
def describe_query(query: dict) -> str: ...     # pure human label
```

`describe_query` turns a query dict into a label, reused for the default recipe name and chip/list captions. Rules (deterministic, no data access):
- `operation == "correlate"` → `"Correlation: {column_a} vs {column_b} ({table})"`.
- `operation == "aggregate"` with `group_by` → `"{Agg} of {metric} by {group_by} ({table})"`.
- `operation == "aggregate"` scalar → `"{Agg} of {metric} ({table})"`.
- Append `", filtered"` when a `filter_column` + `filter_op` are present.
- `_` in column names rendered as spaces; `agg` title-cased.

### 3.2 `src/agent/tools.py` → `run_grounded_query` (MODIFY — stash last query)

On every **successful** grounded query (all three kinds), before returning, stash:
```python
st.session_state["last_grounded_query"] = {
    "query": result["query"],
    "label": recipes.describe_query(result["query"]),
}
```
This is the only change to the tool — the one seam the "Save as recipe" form reads. (Add `from src.agent import recipes` import.) A failed query does not set/overwrite it.

### 3.3 `src/ui/tabs/chat.py` (MODIFY — save form, recipe chips, run handler)

- **Save form.** After the conversation render, if `st.session_state.get("last_grounded_query")` is set, show a compact **"💾 Save as recipe"** expander: a `text_input` pre-filled with the stashed `label`, and a Save button. On save → `recipes.add_recipe(name, query)`, `st.toast`, clear `last_grounded_query`, `st.rerun()`.
- **Recipe chips.** When saved recipes exist, render a **"🍳 Your recipes"** row of buttons (one per recipe, label = recipe `name`), placed near the starter chips. Clicking a chip calls `_run_recipe(recipe)`.
- **`_run_recipe(recipe)` (NEW helper).** Deterministic replay, NOT through `dispatch`:
  1. append a `{"role":"user","type":"text","content": f"▶ {recipe['name']}"}` marker to `ui_history`;
  2. `mark = len(ui_history)`; call `tools.run_grounded_query(**recipe["query"])` inside an `st.status`;
  3. render the cards the tool appended (`ui_history[mark:]`);
  4. `save_session()`; `st.rerun()`.
  On the rare error return (e.g. column missing on a swapped dataset), the tool returns `{"status":"error","error":...}` and appends nothing to `ui_history`; `_run_recipe` appends a one-line assistant note with that error message so the user sees a clean explanation.

### 3.4 `src/ui/sidebar.py` (MODIFY — "🍳 Recipes" section)

Mirror the Watches section (`sidebar.py:174-207`): a `### 🍳 Recipes` header + caption, then a list of `load_recipes()` — each row shows the recipe name (caption = `describe_query`), a **Run** button (sets a pending-run flag the chat consumes, or calls the same `_run_recipe` path), and a **🗑** delete button (`remove_recipe` + `st.rerun()`). "No recipes yet." when empty.

> Wiring note: the sidebar renders before the chat body in `app.py`. To keep one run path, the sidebar Run button sets `st.session_state["run_recipe_id"] = id`; the chat body, early in `render_chat`, consumes that flag and calls `_run_recipe`. This avoids duplicating the render/replay logic in the sidebar.

---

## 4. Data flow — Part A

1. User asks a novel question → LLM calls `run_grounded_query` (Phase 8) → deterministic card rendered; `last_grounded_query` stashed.
2. User clicks **💾 Save as recipe**, keeps or edits the name → `add_recipe` writes `.app_state/recipes.json`.
3. Later (any session — the store persists), a recipe chip / sidebar Run → `_run_recipe` → `run_grounded_query(**query)` → **fresh** card on current data. No router, no LLM.
4. Delete via 🗑 → `remove_recipe`.

---

## 5. Safety / never-malfunctions — Part A

- Store is best-effort like the sibling stores: missing file → `[]`; corrupt/non-list JSON → `[]`; write failure swallowed. Never raises, never crashes the app.
- No raw rows, no computed numbers, no code persisted — only the arg dict + a name.
- Replay reuses the Phase-8 engine, which never raises and validates every column against the live dataset; a stale/mismatched recipe degrades to a clean message.
- Empty/whitespace recipe name → fall back to the derived `label`; never store a blank name.

---

## 6. Part B — Trust / hardening pass

No new features; four finishing tasks. These are verification + polish, so most are not TDD.

1. **Browser-smoke the live flow.** Launch the real Streamlit app; exercise: a normal analysis, a grounded-query question, **save a recipe**, **run the recipe** (incl. re-run after a rerun), and delete it. Confirm cards render, numbers recompute, 0 tracebacks. Capture evidence (screenshots / notes). This is the surface AppTest can't fully drive (buttons + file widgets).
2. **Real BYOD dry-run.** Feed a small **non-Instacart** synthetic CSV (own column names, real money + dates) through the Phase-6 upload → mapping-confirm → analyze path; confirm the app swaps datasets, runs analysis, and the chat + a grounded query work on it. Proves the "runs on a client's own data" claim end to end.
3. **Pin `anthropic`** in `requirements.txt` so the Claude failover tier installs reproducibly. NOTE: the file is UTF-16 — edit preserving encoding (verify `pip install -r` still parses it afterward).
4. **README pass.** A presentable top-level README: what the tool is (customer-loyalty intelligence agent, chat-first, BYOD), how to run locally, how to deploy (Streamlit Cloud + secrets), and the data-portability / trust story (canonical model, every number computed, recipes).

---

## 7. Testing

- **`tests/test_recipes.py`** (NEW, no network): store round-trip (`add`/`load`/`remove`), `describe_query` for scalar / grouped / correlation / filtered queries, corrupt-store tolerance (write junk → `load_recipes()` returns `[]`), blank-name fallback, and a dataset-mismatch note (replaying a query whose column is absent returns the engine's error — exercised at the engine level).
- **`tests/test_recipes_ui.py`** (NEW, AppTest): boot the app, seed one recipe into `session_state`/store, assert its chip renders; drive `_run_recipe` (or the tool directly) and assert a result card lands in `ui_history` with **0 exceptions**; assert the save form appears when `last_grounded_query` is set.
- Regression: full no-network suite green (recipes, recipes_ui, query, tools_canonical, tool_specs, dispatch, chat_shell, full_numbers, upload_flow, dataset_swap, canonical, levers, app_data, …); app boots 0 exceptions.
- Part B item 1 (browser-smoke) and item 2 (BYOD dry-run) are manual verification with captured evidence, not automated tests.

---

## 8. Out of scope (YAGNI)

- Saving multi-step **goals** as recipes (non-deterministic replay).
- Typed / NL name-matching to run a recipe (chips only; `recipe_fn` rung stays inert).
- Editing a saved recipe's arguments, "run all recipes" digest (recipe-management depth — deferred).
- Per-dataset recipe scoping, recipe sharing/export, scheduling.
- Auto-saving answers or similarity-based auto-recipe-on-repeat (roadmap §7).

---

## 9. Success criteria

- After a grounded-query answer, the user can save it (one click, editable name); the recipe persists across restart in `.app_state/recipes.json` (no raw data at rest).
- A saved recipe runs from a chat chip and from the sidebar, recomputes fresh numbers on the current dataset, and works with the LLM quota exhausted.
- A recipe run on a dataset missing a referenced column shows a clean message, never a crash.
- Deleting a recipe removes it everywhere.
- Browser-smoke and a non-Instacart BYOD dry-run both pass with evidence; `anthropic` is pinned; README is presentable.
- All no-network suites green; app boots 0 exceptions. **Roadmap 4→9 complete.**
