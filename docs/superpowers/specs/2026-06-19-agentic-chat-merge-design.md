# Agentic Chat (Chat ⊃ Autopilot) — Design

**Date:** 2026-06-19
**Phase:** Proactive Analyst roadmap — Agentic Chat merge (chosen over the
originally-planned Phase 5 Provider Abstraction, to close the "is the chat really
an agent?" gap first)
**Status:** Approved design, pre-implementation

## Goal

Make the AI Chat itself a real agent, not a reactive tool-using assistant. Today
the chat answers one prompt at a time (Gemini automatic function-calling chains a
few tools internally, but the agency is hidden and reactive); the autonomous,
goal-pursuing loop lives in a separate Autopilot tab. This merge folds the
reflexive loop **into** the chat: a single conversational surface that can either
answer a question (reactive) or pursue a multi-step goal autonomously — deciding
each next step from grounded results, showing its reasoning live — and the
separate Autopilot tab is removed.

## Decisions locked during brainstorming

- **Surface model:** the chat **absorbs** the Autopilot; the Autopilot tab is
  removed. One unified agent surface.
- **Routing:** an **auto-detect LLM router** classifies each message as a quick
  *answer* or a multi-step *goal*. No user-facing mode toggle.
- **Reasoning visibility:** during a goal-run, show **live steps** (🧠 reason →
  ▶️ action → result) in the chat, then a final synthesized summary that stays in
  the conversation.
- **Conversational flow:** a goal **runs to completion** (with the existing
  guardrails); its summary + findings land in the conversation so follow-up
  questions are answered in context. No mid-run clarifying questions, no proactive
  next-step suggestions.
- **Provider:** Gemini-only. Provider abstraction remains a later phase.

## Architecture

A new pure router decides the path; the existing reflexive engine
(`orchestrator.run_reflexive` / `synthesize_goal`) is reused unchanged; the chat
tab becomes the single agent surface and the Autopilot tab is deleted.

### Files

- **Create `src/agent/router.py`** (pure, no Streamlit): `route(message,
  generate_fn=generate) -> {"mode": "answer" | "goal", "goal": str}`. One small
  LLM classification call under `ROUTER_SYSTEM`. **Defaults to `"answer"` on any
  failure, empty, or unparseable output** (cheaper and safer than wrongly looping).
  `generate_fn` is injectable for tests. For `mode == "goal"`, `goal` is the
  goal text to hand the loop (defaults to the original message if the model omits
  it); for `mode == "answer"`, `goal` is `""`.
- **Modify `src/config.py`** — add `ROUTER_SYSTEM`.
- **Modify `src/ui/tabs/chat.py`** — on each user message: call `route()`; for
  `answer`, the current `call_agent` reactive path; for `goal`, run the reflexive
  loop inline (live `st.status`, mirroring the current `autopilot.py`), render the
  tools' inline output, `synthesize_goal`, append the summary to the conversation,
  and inject a synthetic turn into `chat_history` for follow-up continuity. Also
  add the consolidated **deliverables panel** (moved from the Autopilot tab) so no
  capability is lost.
- **Modify `app.py`** — remove the Autopilot tab: drop the
  `from src.ui.tabs.autopilot import render_autopilot` import, the
  `"🚀 Autopilot"` entry in `st.tabs([...])`, and the `with tabs[6]:
  render_autopilot(...)` line. The app drops from 7 tabs to 6.
- **Delete `src/ui/tabs/autopilot.py`** — its behavior now lives in chat. The
  engine in `orchestrator.py` is untouched and is now driven by the chat.
- **Create `tests/test_router.py`** (standalone, no-network).
- **Modify `CLAUDE.md`** — dated Project Journal entry.

## The router (`src/agent/router.py`)

`route(message, generate_fn=generate) -> dict`

- Builds a prompt from the user message; calls `generate_fn(prompt,
  system_instruction=ROUTER_SYSTEM)`.
- Parses a small JSON object `{"mode": "...", "goal": "..."}` (tolerant parse:
  strip ``` fences, then a `{...}` regex fallback — same tactic as
  `orchestrator._parse_decision`).
- Returns `{"mode": "goal", "goal": <text or message>}` only when the parsed
  `mode` is exactly `"goal"`; otherwise `{"mode": "answer", "goal": ""}`.
- Any exception, empty text, or unparseable output → `{"mode": "answer",
  "goal": ""}`.

`ROUTER_SYSTEM` (new in `config.py`) instructs the model to classify the message:
- **answer** — a question, a concept/explanation, a single lookup, or a single
  action (e.g. "who are our power users?", "what does reorder rate mean?",
  "show user 1", "score the customers").
- **goal** — a multi-step objective requiring several analyses/deliverables
  (e.g. "build a retention strategy for at-risk power users", "find and target my
  churners and draft win-back emails").
- Output ONLY `{"mode": "answer"|"goal", "goal": "<goal text if goal else empty>"}`.

Routing is a *judgment* classification, not a business number, so it does not
touch the grounding contract; the loop and tools stay grounded exactly as before.

## Data flow (per user message, in `chat.py`)

1. Append the user message to `ui_history`; call `route(message)`.
2. **answer:** `response = call_agent(message)` (unchanged reactive path: full
   history + automatic function-calling over `ALL_TOOLS`). Append the text reply.
3. **goal:**
   - Open a live `st.status`; pass a `status_callback(reason, label)` that writes
     `🧠 reason` then `▶️ label` per step.
   - `history = run_reflexive(goal, status_callback=...)`.
   - Render the inline analysis output the tools appended to `ui_history` during
     the run (charts/tables/text; artifacts go to the deliverables panel).
   - `summary = synthesize_goal(goal, history)`; append it to `ui_history` as an
     assistant message.
   - **Continuity:** append a synthetic pair to `chat_history` —
     `{"role": "user", "parts": [goal]}` and `{"role": "model", "parts":
     [summary]}` — so a subsequent reactive follow-up has context. This matches
     the `{role, parts:[text]}` shape the persistence layer already produces.
4. `save_session()` and rerun, as today.

## UI changes in the chat tab

- The deliverables panel (moved from `autopilot.py`): under a "📦 Deliverables"
  section, list every artifact in `st.session_state.artifacts` with a download
  button. `chat.py` already imports `render_message`; it will additionally import
  `download_key` from `src.ui.renderer` (the same helper the current Autopilot tab
  uses). Best-effort; absent artifacts → no panel.
- The existing briefing, quick-action buttons, and "New conversation" button stay.

## Testing

`tests/test_router.py` — standalone script (not pytest), exits non-zero on
failure, no network, `test_proactive.py` style. Covers:

- `route()` returns `{"mode": "goal", "goal": ...}` when the injected
  `generate_fn` yields a `goal` classification (incl. JSON wrapped in ``` fences).
- `route()` returns `{"mode": "answer", "goal": ""}` for an `answer`
  classification.
- **Default-to-answer** on: an exception-raising `generate_fn`, empty text, and
  unparseable garbage.
- `goal` text falls back to the original message when the model omits it.

`chat.py` and `app.py` need the Streamlit runtime, so they are syntax-checked +
registration-verified and confirmed by the app booting headless HTTP 200 plus a
human chat check (one answer-type message, one goal-type message). Existing suites
(`test_orchestrator.py`, `test_reflexive.py`, etc.) must stay green as a
regression gate, since the engine is reused unchanged. A dated entry is added to
the top of the CLAUDE.md Project Journal.

## Scope guardrails (YAGNI)

Explicitly **out of scope**:

- mid-run clarifying questions, proactive next-step suggestions/buttons;
- new tools or deliverable types;
- changes to the reflexive engine, guardrails, or `MAX_STEPS`;
- a user-facing mode toggle (routing is automatic);
- provider abstraction / non-Gemini providers.
