# Provider Abstraction (Gemini → Claude failover) — Design

**Date:** 2026-06-19
**Phase:** Proactive Analyst roadmap, Phase 5 (Provider Abstraction + Claude)
**Status:** Approved design, pre-implementation

## Goal

Stop Gemini daily-quota exhaustion from being a hard wall. Today, when every
Gemini key×model combo is quota-exhausted, the agent's text/reasoning calls fail
with an "all combos exhausted, try after midnight Pacific" message. This phase
adds Claude as a **failover tier** for the text-generation calls: when Gemini is
exhausted, those calls automatically fall through to Claude and keep working.

## Decisions locked during brainstorming

- **Abstraction scope:** **text-generation calls only** — the plain
  system+prompt→text calls (router, proactive briefing, memory narration,
  reflexive `decide_next_step`, `synthesize_goal`). The **tool-using chat**
  (`call_agent`, which relies on Gemini automatic function calling) stays
  **Gemini-only**; provider parity for tool-use is deferred to a later phase.
- **Claude's role:** a **failover tier appended after Gemini** in the rotation —
  no user selector, not the default.
- **Selection:** automatic, via the existing `model_idx` rotation extended over a
  unified arsenal (Gemini combos first, then Claude combos).
- **Graceful degradation:** if no Anthropic key is configured, no Claude combos
  are added and behavior is identical to today.
- **Model:** one cheap-but-capable Claude model by default — **Haiku 4.5**
  (`claude-haiku-4-5-20251001`). No streaming.

## Boundary (important, stated honestly)

Because tool-using chat stays Gemini-only, **Claude combos are eligible only for
tool-less text calls.** When Gemini is fully exhausted:
- ✅ briefing, memory continuity, router, and goal-runs (`decide_next_step` +
  `synthesize_goal`) keep working via Claude;
- ❌ the reactive tool-calling chat (`call_agent`) still returns the exhausted
  message until Gemini quota resets.

## Architecture

A thin **provider-adapter seam** — no class hierarchy, just dispatch.

### Files

- **Create `src/agent/providers.py`** (no Streamlit): two adapters with one shared
  signature —
  - `gemini_generate_text(prompt, *, system_instruction, key, model) -> str`
  - `claude_generate_text(prompt, *, system_instruction, key, model) -> str`
  Each performs one non-streaming text completion for its SDK and returns the
  text (raising on error so the caller can rotate). The Claude adapter uses the
  `anthropic` SDK and applies prompt caching to the system prompt (per the
  `claude-api` skill).
- **Modify `src/config.py`**:
  - Load `ANTHROPIC_API_KEY` via the existing `_get_secret`.
  - Add `CLAUDE_MODELS = ["claude-haiku-4-5-20251001"]`.
  - Build `LLM_ARSENAL`: the existing Gemini combos first, then — only if an
    Anthropic key exists — Claude combos appended. Each entry is
    `{"provider": "gemini"|"claude", "key", "model", "label"}`. `MODEL_ARSENAL`
    stays as-is (the Gemini-only subset) for any existing references / the
    tool-using path.
- **Modify `src/agent/caller.py`**:
  - `generate()` rotates over `LLM_ARSENAL` (not `MODEL_ARSENAL`), keeping its
    existing `model_idx` rotation, retry loop, and `ui_history` rollback.
  - For each attempt, pick the combo; **if `tools` is provided, skip non-Gemini
    combos** (tool-using path is Gemini-only) — i.e. the tool path iterates only
    Gemini combos and uses today's `genai` chat code unchanged (returns `chat`).
  - For **tool-less** calls, dispatch by `combo["provider"]`: Gemini → the
    existing genai text path; Claude → `claude_generate_text(...)`. Return
    `{"text", "model_label", "chat": None}` for Claude.
  - `call_agent` is unchanged (it calls `generate(..., tools=ALL_TOOLS)`).
- **Modify `requirements.txt`** — add `anthropic`.
- **Modify `src/ui/sidebar.py` and `src/ui/tabs/chat.py`** — the "combos
  remaining" / active-model indicators currently compute `model_idx %
  len(MODEL_ARSENAL)` and `len(MODEL_ARSENAL) - used`. Since `model_idx` now
  rotates over `LLM_ARSENAL`, switch these displays to `LLM_ARSENAL` so the
  counters stay accurate (Gemini + Claude combos). Display-only change; no logic
  impact.
- **Create `tests/test_providers.py`** (standalone, no-network).
- **Modify `CLAUDE.md`** — dated Project Journal entry.

## Failover behavior

`generate()` keeps the same structure: a loop of `len(LLM_ARSENAL)` attempts,
`idx = model_idx % len(LLM_ARSENAL)`, advancing `model_idx` and rolling back
`ui_history` on each quota/auth/permission failure, exactly as today — just over
the larger arsenal. Order: Gemini key1×{3 models} → … → Gemini keyN → Claude
model(s). When all are exhausted, the same final "all combinations exhausted"
message is returned (now counting both providers). With no Anthropic key,
`LLM_ARSENAL == MODEL_ARSENAL` and behavior is byte-for-byte today's.

For the **tool-using path** (`tools` passed): the loop considers only Gemini
combos. If those are all exhausted, it returns the exhausted message even if
Claude combos exist (Claude can't run the AFC tool path).

## The adapters & grounding

Each adapter is a pure function of `(prompt, system_instruction, key, model)` →
`str`, no Streamlit, raising on SDK error so `generate()`'s try/except rotates.
Grounding is untouched: providers only *narrate*; the deterministic
engines/tools still compute every number, and the only path that *acts* (tools)
stays on Gemini.

## Testing

`tests/test_providers.py` — standalone (not pytest), no-network,
`test_proactive.py` style. Covers (with the SDK adapters injected/monkeypatched,
never hitting the network):

- **Arsenal construction:** a builder helper produces Gemini combos first, then
  Claude combos when an Anthropic key is supplied; and Gemini-only (no Claude
  combos) when the Anthropic key is absent.
- **Dispatch:** `generate()` calls the Gemini adapter for a Gemini combo and the
  Claude adapter for a Claude combo (tool-less path), returning the adapter's
  text with `chat=None` for Claude.
- **Tool-path stays Gemini:** when `tools` is passed, Claude combos are never
  selected (only Gemini combos are tried).
- **Failover across providers:** simulated Gemini quota errors advance the rotation
  into a Claude combo, which then succeeds.

To keep these no-network and deterministic, `generate()` will be refactored so
the arsenal and the two adapters are injectable (default to the real
`LLM_ARSENAL` / real adapters; tests pass fakes) — mirroring the `generate_fn`
seam used elsewhere. The thin real adapters are otherwise exercised by an opt-in
live smoke check (skipped when the relevant key is absent), analogous to the
existing `tests/test_gemini.py`.

Existing suites must stay green (especially `test_gemini.py` and anything reading
`MODEL_ARSENAL`); app boots headless HTTP 200. A dated entry is added to the top
of the CLAUDE.md Project Journal.

## Scope guardrails (YAGNI)

Explicitly **out of scope**:

- tool-using-chat provider parity (Claude tool-use loop) — a later phase;
- a UI provider selector or per-call provider choice;
- multiple Claude models / streaming / cost dashboards;
- changing the reactive `call_agent` behavior or the grounding contract;
- retries beyond the existing rotation logic.
