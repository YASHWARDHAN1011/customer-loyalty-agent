# Agentic Tools + Autopilot — Design Spec

**Date:** 2026-06-08
**Project:** customer-loyalty-agent (inner dir)
**Status:** Approved design, ready for implementation plan

## Goal

Turn the existing Gemini chat (already a function-calling agent with 8 read/analyze
tools) into a **proper working agent** that can (a) take real actions by producing
**downloadable deliverables**, and (b) pursue **autonomous multi-step goals** via a
visible plan-then-execute flow.

The agent today can only *observe and explain* its in-memory Instacart data. After
this work it can *act* (produce campaign files marketing would really use) and
*orchestrate* (chain several tools toward a goal on its own, with a visible plan and
a live step log).

### Out of scope (explicit YAGNI)

- No external sends (no SMTP/Slack/Sheets). Deliverables are downloadable only — keeps
  the public Streamlit Cloud deploy safe, needs no new secrets, nothing can misfire.
- No PDF strategy report (the action-plan checklist covers the summary role).
- No LLM-authored email prose in v1 — drafts are template-driven with real numbers
  (deterministic, downloadable, reliable). Upgrade path noted but not built now.
- Artifacts are ephemeral per session (not persisted across restarts).

## Architecture overview

Three new categories of work, all reusing the existing analysis layer and Gemini
failover:

1. **Deliverable tools** — new functions producing downloadable files (CSV / markdown).
2. **Orchestrator** — plan → execute → synthesize, driving the existing + new tools.
3. **Autopilot tab** — a new 7th UI tab surfacing the orchestrator with a visible plan
   and staged-loading step log.

A caller refactor extracts the Gemini failover into a reusable primitive both chat and
orchestrator share.

```
User goal ──> Autopilot tab ──> orchestrator.plan_goal()  ── Gemini (no tools) ──> JSON plan
                                       │
                                       ├─> render numbered plan card
                                       │
                                orchestrator.execute_plan()  ── calls TOOL_REGISTRY funcs directly
                                       │                          (existing + new deliverable tools)
                                       │                          each appends charts/tables/artifacts
                                       │
                                orchestrator.synthesize_goal() ── Gemini (no tools) ──> exec summary
                                       │
                                Deliverables panel (download buttons over st.session_state.artifacts)
```

## Section 1 — Deliverable tools

New pure module `src/agent/deliverables.py` (no Streamlit; testable) builds file
content. New thin wrappers in `src/agent/tools.py` store the artifact + append a chat
entry with a download button.

| New tool | Output | Built from |
|----------|--------|------------|
| `export_target_list(segment, min_orders, churn_days, limit)` | **CSV** of target users: `user_id`, key stats, `loyalty_score`, `segment` | `features`/`scored_df`; reuses filtering logic shared with `search_users` / `analyze_churn_risk` |
| `draft_campaign_emails(segment)` | **Markdown**: subject + personalized body per top campaign, numbers filled in | `INTERVENTION_TEMPLATES` + `compute_intervention_gaps` (deterministic) |
| `build_action_plan(churn_days)` | **Markdown**: prioritized dated checklist — campaign → segment → target count → expected impact | intervention gaps + churn analysis |

**Artifact mechanism:**

- New `st.session_state.artifacts: list[dict]`. Each artifact =
  `{id, filename, mime, content, label}` (`content` is `str` or `bytes`).
- New `ui_history` entry `type="artifact"` → rendered by `renderer.render_message()`
  via `st.download_button`.
- Artifacts live in session_state, so they survive Streamlit reruns within a session.
- `draft_campaign_emails` and `build_action_plan` produce `text/markdown`;
  `export_target_list` produces `text/csv` bytes.

**Determinism note:** email drafts are template + data interpolation, NOT a nested LLM
call — so they are downloadable and reproducible. Upgrade to LLM-authored copy is a
future option, not in this spec.

## Section 2 — Orchestrator (`src/agent/orchestrator.py`)

Single source of truth: `TOOL_REGISTRY` mapping `name -> {func, description, args_schema}`,
covering the existing analysis tools plus the new deliverable tools. Both the plan
catalog and the executor read from this registry so they cannot drift.

**Phase 1 — `plan_goal(goal: str) -> list[dict]`**

- Build a tool-catalog string from `TOOL_REGISTRY` (name, one-line purpose, args).
- One `generate()` call (no tools) with a strict planning system prompt: output ONLY a
  JSON array of steps; each step `{"tool", "args", "label"}`; choose 2–6 steps; scoring
  must precede segmentation/happy_path/interventions.
- Parse with a **fallback ladder:** (a) strict `json.loads` after stripping ``` fences →
  (b) regex-extract first `[...]` block → (c) default plan
  `run_scoring_analysis → analyze_churn_risk → export_target_list → build_action_plan`.
- Validate each step: `tool` must be in `TOOL_REGISTRY`; args validated/repaired against
  the schema (drop unknown keys). Returns cleaned step list. Never dead-ends.

**Phase 2 — `execute_plan(steps, status_callback) -> list[dict]`**

- Loop steps. Per step: `status_callback(label)` (UI passes a closure writing into
  `st.status`), then call the registry's Python function directly with validated args;
  collect the return dict.
- Tools self-append charts/tables/artifacts to `ui_history`, so output builds naturally.
- Each call wrapped in try/except → a failed step records an error and continues
  (best-effort, never crashes the run).
- Dependency guard: tools already return `{"error": "Run scoring first"}` when
  prerequisites are missing; the executor detects and surfaces these gracefully.

**Phase 3 — `synthesize_goal(goal, step_results) -> str`**

- Final `generate()` call (no tools): summarize what was discovered (3–5 bullets) and
  name the deliverables produced. Returns markdown for the closing message.

## Section 3 — Caller refactor (`src/agent/caller.py`)

Extract the failover loop (currently entangled with chat logic) into a reusable
primitive the orchestrator also needs:

- New `generate(prompt, *, system_instruction, tools=None, history=None) -> dict`
  owns `MODEL_ARSENAL` rotation, all `except` branches (ResourceExhausted, NotFound,
  InvalidArgument tool-schema, PermissionDenied), `model_idx` advancement, and the
  all-exhausted message. Returns `{text, model_label}`.
- `call_agent(prompt)` becomes a thin wrapper preserving today's exact behavior:
  chat history + `enable_automatic_function_calling=True` + `ui_history` rollback.
- `plan_goal` / `synthesize_goal` call `generate(...)` with **no tools** → same quota
  failover protects them.

This is a targeted improvement the new work requires (one failover implementation, not
two copies) — not unrelated refactoring.

## Section 4 — Autopilot tab (`src/ui/tabs/autopilot.py`, new 7th tab)

Registered alongside the existing six tabs in `app.py`.

1. **Goal input:** text box + "Run goal" button, plus 2–3 example-goal chips that
   prefill (e.g. "Build a full retention strategy for at-risk power users",
   "Find and target my churning customers"). Open-ended but discoverable.
2. **On submit:**
   - `plan_goal(goal)` → render the plan as a numbered checklist card (brutalist style).
   - One `st.status("Running plan…")`; call `execute_plan(steps, status_callback)`;
     each step writes `▸ {label}` then ✓ — reuses the staged-loading pattern from
     `run_analysis`.
   - Inline charts/tables/artifacts from each tool render in the tab.
   - `synthesize_goal(...)` → render the executive summary.
3. **Deliverables panel:** list all `st.session_state.artifacts` with download buttons —
   one place for every file produced.

Autopilot and Chat **share the same tools and artifacts**: a file made in chat also
appears in the deliverables panel, and vice versa.

## Section 5 — Testing strategy

Per test-driven-development: deterministic pieces get tests written first; LLM-dependent
pieces get stubbed smoke tests. Standalone scripts exiting non-zero on failure (matches
existing convention).

- `tests/test_deliverables.py` (**write first**): synthetic `features`/`power`/`regular`
  fixture → `export_target_list` returns valid CSV bytes with expected columns;
  `draft_campaign_emails` includes real gap numbers; `build_action_plan` produces a
  non-empty dated checklist.
- `tests/test_orchestrator.py`: `plan_goal`'s parser tested with a fake-`generate` stub
  returning (a) clean JSON, (b) fenced ```json```, (c) garbage → asserts fallback ladder
  reaches the default plan. `execute_plan` tested with stub tools for sequencing +
  error-resilience. **No real network** — `generate` monkeypatched.
- Existing suites (`test_artifacts`, `test_persistence`, `test_data`) must still pass
  (regression guard).

## Section 6 — Cross-cutting concerns

- **Persistence:** artifacts ephemeral per session (not saved to `chat_session.json`).
- **Deployment safety:** in-process only, no new secrets, no external sends → deploys to
  Streamlit Cloud unchanged. No new dependencies.
- **Failover:** plan + synthesize add 2 Gemini calls/goal, both protected by shared
  `generate()`; quota exhaustion degrades gracefully (fallback plan still runs the
  no-LLM analysis tools).
- **Journal:** add a dated CLAUDE.md journal entry when built.
- **Process skills:** implement on an isolated git worktree (using-git-worktrees);
  TDD for deliverables + parser; verification-before-completion (boot headless, all
  tests pass, HTTP 200) before any done-claim; requesting-code-review before merge;
  finishing-a-development-branch to land.

## Files touched

**New:** `src/agent/deliverables.py`, `src/agent/orchestrator.py`,
`src/ui/tabs/autopilot.py`, `tests/test_deliverables.py`, `tests/test_orchestrator.py`.

**Modified:** `src/agent/tools.py` (3 new tool wrappers + registry entries),
`src/agent/caller.py` (extract `generate()`), `src/ui/renderer.py` (artifact render
branch), `app.py` (register 7th tab; init `artifacts` session state), `CLAUDE.md`
(journal entry).

## Success criteria

1. In Autopilot, entering a goal shows a numbered plan, a live step log, inline
   analysis output, an executive summary, and downloadable deliverables.
2. The three deliverable tools work from both Chat and Autopilot and produce valid,
   downloadable CSV/markdown with real numbers.
3. Plan parser survives clean/fenced/garbage model output (fallback ladder).
4. All new + existing tests pass; app boots headless HTTP 200.
5. No new secrets/deps; still deployable to Streamlit Cloud.
