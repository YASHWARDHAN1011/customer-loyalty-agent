# Roadmap: The Proactive Analyst Agent

## Context

Today the agent is **reactive**: it waits for a prompt, runs a tool, answers. That makes it a
good chatbot, but not a standout one — it behaves like every other "ask-me-anything over your
data" assistant. You chose **Proactive Analyst** as the defining differentiator: an agent that
*watches the data and surfaces what matters unprompted*, then offers one-click follow-through.

The app already has the perfect substrate for this: a pure, deterministic analysis layer
(`src/analysis/*`) that computes churn risk, segment gaps, intervention opportunities, and happy
paths. Nothing here needs to be invented — the proactive layer *reads* those functions, detects
noteworthy conditions deterministically (no hallucinated numbers), and uses the LLM only to
*narrate* them. That keeps the agent's existing strength (deterministic deliverables) while adding
a behavior generic chatbots can't fake.

**This session ships Phase 1.** The rest is the roadmap.

---

## Future roadmap (the brainstorm)

```
Phase 1  Proactive Briefing      ← THIS SESSION
         deterministic signal detection + grounded narration + one-click actions
              │
Phase 2  Reflexive Autopilot
         orchestrator gains a reflect→replan loop; exposes its reasoning trace
              │
Phase 3  Memory & Continuity
         persist briefings/decisions to .app_state; "churn was 8% last week, now 12%"
              │
Phase 4  What-If Simulation
         counterfactual tools — "if reorder rate +10%, how does the power-user pool move?"
              │
Phase 5  Provider Abstraction
         wrap generate() behind a provider interface; add Claude for deeper reasoning,
         keep Gemini failover arsenal underneath
              │
Phase 6  Triggered Proactivity
         threshold alerts + scheduled briefing refresh
```

**Provider recommendation (you said "open to either"):** stay **Gemini-only for Phase 1**. The
proactive layer is provider-agnostic — its only LLM call routes through the existing
`generate()` in `caller.py`, so swapping providers later (Phase 5) is a localized change behind one
function, not a rewrite. Adding a provider abstraction now would be scope creep that doesn't serve
the "proactive" goal. Defer it.

---

## Phase 1 — what we build now

A **Proactive Briefing** at the top of the AI Chat tab. The moment analysis has run, the agent
greets the user with the 3-4 most important things happening in their customer base — each as a
card with a deterministic headline, a supporting number, and a one-click action button that hands
a tailored prompt to the existing agent.

### Data flow

```
run_analysis (app.py)  ──►  st.session_state {scored_df, power, regular, power_user_ids, full_data}
                                          │
                                          ▼
                          proactive.get_briefing()   (reads session_state)
                                          │
                  ┌───────────────────────┼───────────────────────┐
                  ▼                                                ▼
        insights.detect_signals(...)                    generate()  ← caller.py
        (PURE: reuses analysis fns,                     narrate digest with
         deterministic numbers)                          PROACTIVE_SYSTEM prompt
                  │                                                │
                  └───────────► {ready, signals[], narrative} ◄────┘
                                          │
                                          ▼
                       render_briefing()  (chat.py)
                       narrative + signal cards
                       each card button → _handle_quick_action(action_prompt)
                                          │
                                          ▼
                              existing call_agent() path  (no new execution route)
```

### Files & changes

**1. `src/agent/insights.py`  (NEW — pure, Streamlit-free, per the `src/analysis` convention)**

- `detect_signals(features, scored_df, power, regular, power_user_ids, full_data, churn_days=30, top_pct=10) -> list[dict]`
  Reuses, do **not** reimplement:
  - `calculate_churn_risk(features, power_user_ids, churn_days)` → `src/analysis/metrics.py`
  - `compute_segment_gaps(power, regular)` → `src/analysis/segmentation.py`
  - `compute_intervention_gaps(power, regular)` + `INTERVENTION_TEMPLATES` → `src/analysis/interventions.py`
  - `get_happy_paths(full_data, power_user_ids, lookback, top_n)` → `src/analysis/happy_path.py`

  Build these signals (each a dict: `{"id", "severity": int 0-100, "icon", "headline", "detail", "action_label", "action_prompt"}`):
  | id | source | headline driver | severity driver | action_prompt |
  |----|--------|-----------------|-----------------|---------------|
  | `churn` | `calculate_churn_risk` | `at_risk` count / `at_risk_pct`; call out `at_risk_power` | scales with pct + power-user exposure | `"Build an action plan for at-risk customers using a 30-day threshold and export the target list."` |
  | `segment_gap` | `compute_segment_gaps`[0] | top feature ratio (e.g. "Power users reorder 2.3× more") | scales with ratio | `"Compare power users vs regular users and draft campaign emails for the biggest gap."` |
  | `intervention` | `compute_intervention_gaps`[0] + template `title`/`action` | top campaign opportunity | scales with gap_pct | `"What campaign should we run first to convert regular users? Generate the recommendations."` |
  | `power_value` | `len(power)/len(scored_df)` | power-user concentration | inverse of pct (smaller elite = higher leverage) | `"Show me the top 20 most loyal customers and what makes them different."` |
  | `happy_path` (guard on `full_data` non-empty) | `get_happy_paths`[0] biggest funnel drop | largest dropoff step | scales with dropoff % | `"Find the happy path to power-user status and where customers drop off."` |

  Return signals sorted by `severity` desc, capped at 4. Use `max(ru_avg, 0.001)`-style guards
  already present in the source functions; skip a signal cleanly if its inputs are missing.

- `briefing_digest(signals) -> str` — compact plaintext block (headline + detail per signal) to
  feed the LLM for narration. No numbers the model has to compute.

**2. `src/config.py`  (add one constant next to `SYSTEM_PROMPT`)**

- `PROACTIVE_SYSTEM` — instructs: *"You are a proactive customer-loyalty analyst opening the
  conversation. You are given a digest of detected signals with exact numbers. Write a 2-3 sentence
  briefing in a confident consultant voice. Use ONLY numbers from the digest — never invent figures.
  End with the single most urgent recommendation."*

**3. `src/agent/proactive.py`  (NEW — reads `st.session_state`, mirrors `tools.py` style)**

- `get_briefing() -> dict`:
  - If `scored_df`/`power` not in session_state (analysis not run) → return `{"ready": False}`.
  - Else call `insights.detect_signals(...)` pulling args from session_state
    (`features`, `scored_df`, `power`, `regular`, `power_user_ids`, `full_data`, `top_pct`, churn default 30).
  - Narrate via `generate(digest, system_instruction=PROACTIVE_SYSTEM)` (import from
    `src.agent.caller`). Wrap in try/except → on any failure fall back to a templated narrative
    built from `signals[0]` (best-effort, never crash — matches the app's persistence/onboarding convention).
  - **Cache the LLM narrative** in `st.session_state['_briefing_cache']` keyed by a signature
    (`top_pct`, churn_days, `len(scored_df)`) so it isn't re-generated on every Streamlit rerun.
    `detect_signals` itself is cheap pandas over already-computed frames — recompute freely.
  - Return `{"ready": True, "signals": [...], "narrative": str}`.

**4. `src/ui/tabs/chat.py`  (add `render_briefing()`, call it inside `render_chat`)**

- Define `render_briefing()` and call it after the status-metrics block / before `st.divider()`
  at line ~53, so the briefing sits above the conversation.
- Behavior:
  - `b = get_briefing()`. If `not b["ready"]` → a single compact callout: *"Run an analysis to get
    your proactive briefing"* with a button that calls `_handle_quick_action("Run the full analysis
    and identify our power users")` (reuses the agent's `run_scoring_analysis` tool — no app.py coupling).
  - If ready → render `b["narrative"]` in a styled container, then the signal cards in
    `st.columns(len(signals))`. Each card shows `icon + headline + detail` and a button
    `f"→ {signal['action_label']}"` that calls the **existing** `_handle_quick_action(signal['action_prompt'])`.
    No new execution path — proactivity reuses the proven chat route.
  - Put the whole thing in an expander titled **"💡 Today's Briefing"**, expanded by default, so it
    doesn't crowd returning users.

**5. `tests/test_insights.py`  (NEW — pytest, mirrors `tests/test_deliverables.py`)**

- Build small synthetic `features`/`scored_df`/`power`/`regular` DataFrames with the real column
  names (`user_id, total_orders, avg_days_between_orders, reorder_rate, dept_diversity,
  avg_basket_size, total_items, loyalty_score`).
- Assert: `detect_signals(...)` returns a non-empty list; ids are unique; results sorted by
  `severity` desc and capped at 4; the `churn` signal appears when `avg_days_between_orders` is set
  high; every signal has a non-empty `action_prompt`; `briefing_digest(signals)` returns a string
  containing each headline. Pure — no network, no Streamlit import.

### What we deliberately do NOT do in Phase 1
- No provider swap (Phase 5). No memory/persistence of past briefings (Phase 3). No background
  refresh (Phase 6). No new analysis math — only orchestration of existing functions.

---

## Verification

1. **Unit (no network):**
   `python tests/test_insights.py` (and confirm `tests/test_deliverables.py` still passes — same style).
2. **Byte-compile** the touched/new modules:
   `python -m py_compile src/agent/insights.py src/agent/proactive.py src/ui/tabs/chat.py src/config.py`
3. **App boots headless:** launch Streamlit headless and confirm HTTP 200 (the project's standard smoke check).
4. **Manual path (browser, brief):** open AI Chat with no analysis → see the "Run an analysis"
   prompt; run analysis → the briefing populates with narrative + 3-4 signal cards; click a card
   button → it routes through the normal agent and appends a response. Confirm numbers in the cards
   match the Scoring/Interventions tabs (deterministic, not hallucinated).
5. **Update the journal:** add a dated entry to the top of `CLAUDE.md`'s Project Journal describing
   the proactive briefing, per the repo convention.

After approval I'll implement on a new branch and open a PR.

---

## Implementation note (added when saved locally, 2026-06-11)

Two convention corrections to apply during PR review:
- `caller.py`'s `generate(prompt, *, system_instruction, tools=None, history=None, automatic_function_calling=False)`
  returns a **dict** `{"text", "model_label", "chat"}` — `proactive.py` must read `result["text"]`,
  not the raw return value.
- Despite the plan calling `tests/test_insights.py` "pytest", this repo's tests are **standalone
  scripts** (a `check()` helper, exit non-zero on failure), e.g. `tests/test_deliverables.py`.
  Match that style.
