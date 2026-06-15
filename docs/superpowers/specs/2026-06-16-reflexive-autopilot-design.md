# Reflexive Autopilot — Design

**Date:** 2026-06-16
**Phase:** Proactive Analyst roadmap, Phase 2 (Reflexive Autopilot)
**Status:** Approved design, pre-implementation

## Goal

Turn the Autopilot from an **open-loop** runner into a **closed-loop** one. Today
the agent plans every step upfront and executes them blindly. Reflexive Autopilot
runs one step, looks at what it found, and decides the next move — skip a now-
pointless step, dig deeper, adjust an argument, or stop early when the goal is met
— with its reasoning shown live.

Approach chosen: **Grounded ReAct (Approach C).** The LLM is the controller (it
adapts and reasons in real time), but every decision is constrained by
construction — it may only choose a real tool from `TOOL_REGISTRY`, args are
validated, and its stated reasoning must cite the actual numbers produced by prior
steps. The model routes and explains using real data; it never invents numbers.
This matches the project's grounding ethos (same principle as `PROACTIVE_SYSTEM`).

Decisions locked during brainstorming:
- **Core behavior:** adapt mid-run / re-plan (closed loop) — not just self-critique.
- **Rollout:** the reflexive loop **replaces** the current Autopilot (old open-loop
  planner retired as primary; its fallback plan is retained as a guardrail).
- **Transparency:** the agent's reasoning is shown **live** at each step.

## Architecture

Evolve `src/agent/orchestrator.py`. The open-loop trio
`plan_goal → execute_plan → synthesize_goal` is replaced by a single closed loop.
The shared `TOOL_REGISTRY`, the arg validation, and `DEFAULT_PLAN` are all reused.

### Functions

```
decide_next_step(goal, history, generate_fn=generate)
    -> {"tool", "args", "label", "reason"} | {"done": True, "reason"}
_digest_history(history) -> str          # pure, no LLM
run_reflexive(goal, status_callback=None, generate_fn=generate)
    -> [{label, tool, args, reason, result}, ...]  # the executed step list
synthesize_goal(goal, results, generate_fn=generate) -> str  # kept ~as-is
```

### The loop (`run_reflexive`)

1. Start with empty `history`.
2. **First-step rule:** if scoring has not run, force step 1 to
   `run_scoring_analysis` (everything depends on it) — no LLM call needed.
3. Call `decide_next_step(goal, history)`: one Gemini call that sees the goal, the
   compact digest of prior results (`_digest_history`), and the tool catalog
   (`_tool_catalog`). It returns the next `{tool, args, label, reason}` or
   `{done: True, reason}`.
4. Validate the choice against `TOOL_REGISTRY` (reuse existing `_validate_steps`
   logic: unknown tool dropped, unknown arg keys stripped). Enforce scoring-first:
   if it picks a tool that needs scoring before scoring ran, redirect that step to
   `run_scoring_analysis`.
5. Execute the tool (reuse the existing per-step try/except: never raise on a step
   failure). Append `{label, tool, args, reason, result}` to `history` and report
   via `status_callback`.
6. Repeat until `done` or a guardrail trips.

### Guardrails (deterministic — independent of the model)

- **Max 6 steps** total, then stop and synthesize.
- **No-repeat:** reject an identical `(tool, args)` already in `history`; forces
  forward progress and prevents infinite loops. If the only choice is a repeat,
  treat as `done`.
- **Parse/validate fallback:** if `decide_next_step` returns something
  unparseable/invalid twice in a row, fall back to the unrun remainder of
  `DEFAULT_PLAN`, execute those, and finish — a flaky model never breaks a run.
- **Scoring-first** is always enforced (step 1 rule above + per-step redirect).

### Grounding contract

A new `REFLEXIVE_SYSTEM` prompt (`src/config.py`) instructs the controller:
choose only from the provided catalog; output the decision as strict JSON; your
`reason` must reference the numbers in the digest; never state a number that is
not in the digest; signal `done` when the goal is satisfied. The digest's numbers
come straight from tool result dicts, so they are deterministic.

## Data flow

```
goal ─▶ run_reflexive
          │  (loop)
          ├─ _digest_history(history) ─┐
          ├─ _tool_catalog() ──────────┤─▶ decide_next_step ─▶ {tool,args,reason}|done
          │                            │        (Gemini, REFLEXIVE_SYSTEM)
          ├─ validate + scoring-first guard
          ├─ TOOL_REGISTRY[tool].func(**args)  ─▶ result dict
          └─ append to history; status_callback(reason, label)
        │
        ▼
   synthesize_goal(goal, history) ─▶ executive summary
```

### The digest

`_digest_history(history)` flattens each prior step into a few grounded lines from
the headline numbers already present in each tool's result dict (no new fields, no
computation, no LLM). Example:

```
Step 1 — Score customers: 206,209 customers scored, 20,626 power users (top 10%).
Step 2 — Churn risk: 4,812 at-risk (2.3%), 312 of them power users.
```

It is the only source the controller may cite numbers from. Pure and unit-tested.

## UI (`src/ui/tabs/autopilot.py`)

Keeps the existing `st.status` container. Each loop iteration now renders two
lines:

- 🧠 **reasoning** — the `reason` from `decide_next_step`
  ("Churn is only 2.3%, so retention isn't the priority — digging into the segment
  gap instead.")
- ▶️ **action** — the step label, then ✅ when the result lands.

The final `synthesize_goal` summary renders below, as today. Deliverable artifacts
(CSV / campaign emails / action plan) continue to flow through the existing
`st.session_state.artifacts` path — untouched.

## Error handling

- Step execution: existing best-effort try/except — a failed step records
  `{"error": ...}` and the loop continues (the controller sees the error in the
  next digest and can route around it).
- LLM decision failure / unparseable: parse-fallback ladder → `DEFAULT_PLAN`
  remainder (see guardrails).
- All session/persistence behavior unchanged; nothing here can crash the app.

## Testing

New standalone script (repo convention; exits non-zero on failure; no network),
`tests/test_reflexive.py`:

- `_digest_history`: correct formatting from sample result dicts (incl. an error
  result and an empty history).
- `decide_next_step` with a **fake `generate_fn`**: valid pick parsed correctly;
  unparseable text → invalid/fallback signal; scoring-first redirect; `done`
  signal recognized.
- `run_reflexive` end-to-end with a **scripted fake controller**: stops on `done`;
  honors the 6-step cap; rejects an identical repeat; forces scoring as step 1.

Existing suites must still pass; app must boot headless HTTP 200.

## Blast radius

- **Changed:** `src/agent/orchestrator.py` (loop rewrite; registry/validator/
  fallback reused), `src/ui/tabs/autopilot.py` (live reasoning UI),
  `src/config.py` (new `REFLEXIVE_SYSTEM`).
- **Untouched:** `tools.py`, `caller.py`, `insights.py`, `proactive.py`, analysis
  layer, persistence.
- **Retired as primary path:** `plan_goal` / `execute_plan` (logic absorbed into
  the loop). `DEFAULT_PLAN` retained as guardrail fallback.

## Out of scope (later phases)

Memory/continuity across runs (Phase 3), what-if simulation (Phase 4), provider
abstraction / Claude support (Phase 5), triggered proactivity (Phase 6). Provider
stays Gemini-only here.
