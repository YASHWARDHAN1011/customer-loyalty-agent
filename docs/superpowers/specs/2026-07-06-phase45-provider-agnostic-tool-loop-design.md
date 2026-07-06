# Phase 4.5 — Provider-Agnostic Tool Loop + Config-Swappable Backend — Design

**Roadmap:** `docs/superpowers/specs/2026-07-05-chat-first-agent-roadmap-design.md` §6
(build order `4 → 4.5 → 5 → 6 → 7 → 8 → 9`). Phase 4 shipped; this is the next step.

## 1. Why

The reactive tool-using chat (`call_agent`) is **Gemini-only** because it relies on
Gemini's `enable_automatic_function_calling`. When every Gemini free-key/model combo
hits its daily quota, the chat dies — and the chat-first pivot (Phase 7) makes the
whole app depend on it. So we harden the tool path *before* the pivot: make it
provider-agnostic (fail over Gemini → Claude) and make the LLM backend selectable by
one config setting (dev free keys → a production endpoint) with **no code change** to
swap.

Grounding is unaffected: tools still compute every number; the LLM only decides which
tool to call and narrates the result.

## 2. Scope

**In scope (plumbing only):**
- A provider-agnostic, hand-written tool loop that both Gemini and Claude drive.
- A neutral tool-spec registry (JSON schemas) as the single source of truth.
- Per-provider "turn" adapters translating the neutral loop ⇄ each SDK's tool protocol.
- Neutral conversation history (replaces Gemini-native `chat.history`); persistence
  updated to round-trip it.
- Config: `LLM_BACKEND` profile selector + a `base_url` seam per combo.
- Gemini → Claude failover on the tool path, reusing the existing `LLM_ARSENAL` /
  `model_idx` rotation.

**Explicitly NOT in scope (deferred):**
- **Re-anchoring `tools.py` / `deliverables.py` onto canonical levers** → Phase 5.
  Phase 4.5 adds only a thin safety net: a tool that raises is caught and returned as
  a text error the model can relay, so the chat never crashes. It does not make the
  Instacart-bound tools *compute correctly* on canonical data.
- "I can't run that on this dataset" **conversational** degradation messaging → Phase 5.
- Choosing/standing up the final production LLM host → later (the seam exists; wiring a
  specific host is a profile addition). Gemini-via-Vertex auth is not built now.
- Streaming responses (kept non-streaming, as today).

## 3. Components

| Module | Change | Responsibility |
|---|---|---|
| `src/agent/tool_specs.py` | **NEW** | `TOOL_SPECS`: one `{name, description, input_schema, fn}` per tool; the neutral registry both providers derive from. `execute_tool(name, args, specs) → str`. |
| `src/agent/tool_loop.py` | **NEW** | `run_tool_conversation(...)`: the pure, injectable, provider-neutral loop. No Streamlit, no SDK imports. |
| `src/agent/providers.py` | extend | `gemini_tool_turn(...)`, `claude_tool_turn(...)`: one SDK round-trip each, neutral-in / neutral-out. `base_url` support on the Claude adapters. |
| `src/agent/caller.py` | rework | `call_agent` drives `run_tool_conversation` with the current combo's turn adapter, over `LLM_ARSENAL` + `model_idx` failover. Tool-less `generate()` text path unchanged. |
| `src/config.py` | extend | `LLM_BACKEND` selector + `BACKEND_PROFILES`; generalize `build_llm_arsenal` to read the active profile and emit combos (now with `base_url`). `dev` reproduces today exactly. |
| `src/utils/persistence.py` | update | Save/load the neutral message list as plain JSON; guard-discard an incompatible pre-4.5 saved session (best-effort). |

The 8 tool functions in `tools.py` are **not modified**.

## 4. Data shapes

**Neutral message** (both providers + the session store read this):
```python
{"role": "user" | "assistant", "content": [block, ...]}
# blocks:
#   {"type": "text", "text": str}
#   {"type": "tool_call", "id": str, "name": str, "args": dict}      # assistant
#   {"type": "tool_result", "id": str, "text": str}                  # user turn
```

**Neutral turn result** (what a `*_tool_turn` adapter returns):
```python
{"text": str}                                   # final answer
# or
{"tool_calls": [{"id": str, "name": str, "args": dict}, ...]}
```

**Tool spec:**
```python
{"name": str, "description": str,
 "input_schema": {json-schema object}, "fn": callable}
```

**Combo** (unchanged + one field): `{"provider", "key", "model", "label", "base_url"}`.

## 5. The loop

```
run_tool_conversation(messages, tool_specs, executor, provider_turn,
                      max_steps=6):
    for _ in range(max_steps):
        turn = provider_turn(messages, tool_specs)   # one SDK round-trip
        if "tool_calls" in turn:
            messages.append(assistant(tool_call blocks))
            for call in turn["tool_calls"]:
                result = executor(call["name"], call["args"], tool_specs)
                messages.append(user(tool_result block for call["id"]))
            continue
        messages.append(assistant(text block))
        return turn["text"], messages
    return "<hit tool-step limit>", messages
```
- `provider_turn` and `executor` are injected → the loop is unit-testable with a
  scripted fake provider and fake tools, no network.
- `max_steps` caps tool iterations (no infinite loops).

## 6. Failover

`call_agent` keeps the existing rotation: pick `LLM_ARSENAL[model_idx % n]`, build that
combo's `provider_turn`, run the conversation; on a quota / permission / not-found error
raised by the adapter, advance `model_idx` and retry with the next combo. Gemini combos
come first, Claude after (per the `dev` profile). Fail-fast (`FAST_FAIL`, no SDK backoff)
is preserved. **Failover happens between whole turns/conversations, not mid-tool-
sequence** — simple and predictable. If all combos are exhausted, return the existing
"all combinations quota-exhausted" message.

## 7. Executor contract

`execute_tool(name, args, specs)`:
- looks up the spec, calls `fn(**args)`;
- returns a concise **text summary** of what the tool produced (mirrors what Gemini's
  auto-calling fed back), synthesizing a brief "done" when the tool returns `None`;
- **catches any exception** and returns `"Tool <name> failed: <msg>"` so a broken /
  Instacart-bound tool degrades into relayable text and never crashes the chat.

The executor is the only place tools are invoked, so the loop never touches
`st.session_state` directly.

## 8. Config

```python
LLM_BACKEND = _get_secret("LLM_BACKEND") or "dev"

BACKEND_PROFILES = {
  "dev": {"providers": [
     {"provider": "gemini", "key_source": "GEMINI_KEY_*", "models": MODELS,
      "base_url": None},
     {"provider": "claude", "key_source": "ANTHROPIC_API_KEY",
      "models": CLAUDE_MODELS, "base_url": None},
  ]},
  # "prod": single provider, company key env var, base_url = enterprise endpoint
  #         — added later, NO code change.
}
```
`build_llm_arsenal` reads the active profile and emits the same combo list it does now,
plus `base_url` (default `None`). `dev` preserves the exact Gemini-first-then-Claude
ordering and labels → **default behavior is byte-for-byte unchanged**. The Anthropic
adapters pass `base_url=combo.get("base_url")` into `anthropic.Anthropic(...)`.

## 9. Persistence

`chat_history` in `session_state` becomes the neutral message list. `persistence.py`
saves/loads it as plain JSON (all block types are JSON-safe, including `tool_call` /
`tool_result` — an improvement: restored chats keep tool context). The loader guards:
an old session whose shape doesn't match the neutral format is discarded, not crashed
(best-effort, per the existing convention).

## 10. Testing (standalone scripts, repo convention)

- `tests/test_tool_loop.py` — the loop with a **scripted fake provider** (returns a
  tool_call turn, then a text turn) and **fake tools**: verifies tool dispatch, result
  feedback, multi-step, `max_steps` cap, and text termination. No network.
- `tests/test_tool_specs.py` — every tool in `ALL_TOOLS` has a spec; schema shape is
  valid; `execute_tool` runs a tool, summarizes a result, and catches a raising tool.
- `tests/test_providers.py` (extend) — `gemini_tool_turn` / `claude_tool_turn`
  neutral⇄SDK translation via **mocked SDK responses** (no real calls); `base_url`
  threaded into the Anthropic client.
- `tests/test_config.py` (new or extend) — `build_llm_arsenal` for the `dev` profile
  equals today's arsenal; an added fake profile changes ordering; missing `LLM_BACKEND`
  defaults to `dev`.
- Boot: `streamlit.testing.AppTest` — app boots 0 exceptions; a scripted `call_agent`
  (fake provider) drives a tool end-to-end.

## 11. Success criteria

- The tool-using chat answers via Claude when all Gemini combos are exhausted (verified
  with a simulated exhaustion + fake Claude turn).
- Switching the LLM backend is a config edit (`LLM_BACKEND` / a new profile), not a code
  change; an enterprise Anthropic endpoint drops in via `base_url`.
- With no new config, behavior is identical to Phase 4 (same arsenal, same ordering).
- No tool call can crash the chat — a raising tool becomes relayable text.
- All existing no-network suites stay green; app boots 0 exceptions.
