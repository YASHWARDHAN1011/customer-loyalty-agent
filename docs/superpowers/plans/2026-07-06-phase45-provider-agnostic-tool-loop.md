# Phase 4.5 — Provider-Agnostic Tool Loop + Config-Swappable Backend — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the tool-using chat provider-agnostic (fail over Gemini → Claude via one hand-written tool loop) and make the LLM backend selectable by a single `LLM_BACKEND` config profile, with default behavior identical to Phase 4.

**Architecture:** A neutral tool-spec registry (auto-derived from each tool's typed signature) feeds one pure `run_tool_conversation` loop. Per-provider "turn" adapters translate the neutral loop ⇄ each SDK's native tool protocol. `call_agent` drives the loop over the existing `LLM_ARSENAL`/`model_idx` rotation; config gains named backend profiles with a `base_url` seam.

**Tech Stack:** Python, `google-generativeai`, `anthropic`, Streamlit. Tests are **standalone scripts** (repo convention, not pytest); each `assert`s and exits non-zero on failure. Run with `..\venv\Scripts\python.exe tests\<name>.py`.

**Spec:** `docs/superpowers/specs/2026-07-06-phase45-provider-agnostic-tool-loop-design.md`

---

## Scope

**In:** neutral tool specs + executor; the pure loop; Gemini/Claude turn adapters; config profiles + `base_url`; `call_agent` rework + failover; neutral history + persistence.
**Out (Phase 5):** re-anchoring `tools.py` onto canonical levers (only a catch-and-relay safety net here); conversational "can't run on this dataset" messaging; choosing the prod host.

## File Structure

- **Create** `src/agent/tool_specs.py` — `spec_from_function`, `TOOL_SPECS`, `execute_tool`.
- **Create** `src/agent/tool_loop.py` — `run_tool_conversation` (pure, injectable).
- **Create** `tests/test_tool_specs.py`, `tests/test_tool_loop.py`, `tests/test_config.py`.
- **Modify** `src/agent/providers.py` — add `claude_tool_turn`, `gemini_tool_turn`, thread `base_url`.
- **Modify** `src/config.py` — `LLM_BACKEND`, `BACKEND_PROFILES`, generalize `build_llm_arsenal`.
- **Modify** `src/agent/caller.py` — `call_agent` drives the loop + failover; neutral history.
- **Modify** `src/utils/persistence.py` — save/load neutral messages; guard old sessions.
- **Extend** `tests/test_providers.py` — turn-adapter translation via mocked SDK.

---

## Task 1: Neutral tool specs + executor

**Files:**
- Create: `src/agent/tool_specs.py`
- Test: `tests/test_tool_specs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tool_specs.py — standalone script
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import tool_specs as ts
from src.agent.tools import ALL_TOOLS

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

# spec_from_function derives a JSON-schema spec from a typed signature
def sample(top_percentile: int = 10, note: str = None) -> dict:
    """Do a thing. Second line ignored."""
    return {"ok": True}

spec = ts.spec_from_function(sample)
ok(spec["name"] == "sample", "spec name = function name")
ok(spec["description"].startswith("Do a thing"), "description = first docstring line")
props = spec["input_schema"]["properties"]
ok(props["top_percentile"]["type"] == "integer", "int -> integer")
ok(props["note"]["type"] == "string", "str -> string")
ok(spec["input_schema"]["required"] == [], "params with defaults are optional")
ok(spec["fn"] is sample, "spec carries the callable")

# TOOL_SPECS covers every tool in ALL_TOOLS, keyed by name
names = {s["name"] for s in ts.TOOL_SPECS}
ok(names == {f.__name__ for f in ALL_TOOLS}, "TOOL_SPECS matches ALL_TOOLS")

# execute_tool runs a tool and returns a text summary
def fake_ok(x: int = 1) -> dict:
    """Fake."""
    return {"scored": 5, "power": 2}
specs = [ts.spec_from_function(fake_ok)]
out = ts.execute_tool("fake_ok", {"x": 3}, specs)
ok(isinstance(out, str) and "scored" in out, "execute_tool returns a text summary")

# execute_tool catches a raising tool -> relayable text, never raises
def boom() -> dict:
    """Boom."""
    raise KeyError("total_orders")
specs2 = [ts.spec_from_function(boom)]
out2 = ts.execute_tool("boom", {}, specs2)
ok("failed" in out2.lower() and "total_orders" in out2, "raising tool -> error text")

# unknown tool -> error text, not a crash
ok("unknown" in ts.execute_tool("nope", {}, specs2).lower(), "unknown tool -> error text")

print(f"test_tool_specs: {checks} checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_tool_specs.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.tool_specs'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/agent/tool_specs.py
"""Neutral tool registry: the single source of truth both LLM providers read.

Each spec is {name, description, input_schema (JSON Schema), fn}. Specs are
auto-derived from each tool's typed signature (DRY — no hand-maintained schemas).
`execute_tool` is the ONLY place a tool function is invoked; it summarizes the
tool's return for the model and catches any exception so a broken/Instacart-bound
tool degrades into relayable text instead of crashing the chat.
"""

import inspect
import json

from src.agent.tools import ALL_TOOLS

_PY_TO_JSON = {int: "integer", float: "number", str: "string", bool: "boolean"}


def spec_from_function(fn):
    """Build a neutral tool spec from a function's signature + docstring."""
    sig = inspect.signature(fn)
    props, required = {}, []
    for pname, p in sig.parameters.items():
        if pname.startswith("_"):
            continue
        jtype = _PY_TO_JSON.get(p.annotation, "string")
        props[pname] = {"type": jtype, "description": pname.replace("_", " ")}
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    doc = (inspect.getdoc(fn) or "").strip().splitlines()
    description = doc[0] if doc else fn.__name__
    return {
        "name": fn.__name__,
        "description": description,
        "input_schema": {"type": "object", "properties": props, "required": required},
        "fn": fn,
    }


TOOL_SPECS = [spec_from_function(fn) for fn in ALL_TOOLS]


def _summarize(name, result):
    """Concise text the model can narrate, from a tool's return value."""
    if result is None:
        return f"{name} completed."
    if isinstance(result, (dict, list)):
        try:
            return json.dumps(result, default=str)[:1500]
        except Exception:
            return str(result)[:1500]
    return str(result)[:1500]


def execute_tool(name, args, specs=None):
    """Run the named tool with args; return a text result. Never raises."""
    specs = TOOL_SPECS if specs is None else specs
    spec = next((s for s in specs if s["name"] == name), None)
    if spec is None:
        return f"Unknown tool: {name}"
    try:
        return _summarize(name, spec["fn"](**(args or {})))
    except Exception as e:
        return f"Tool {name} failed: {type(e).__name__}: {e}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_tool_specs.py`
Expected: PASS — `test_tool_specs: N checks passed`

- [ ] **Step 5: Commit**

```bash
git add src/agent/tool_specs.py tests/test_tool_specs.py
git commit -m "feat: neutral tool-spec registry + safe executor"
```

---

## Task 2: The provider-agnostic tool loop

**Files:**
- Create: `src/agent/tool_loop.py`
- Test: `tests/test_tool_loop.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tool_loop.py — standalone script
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent.tool_loop import run_tool_conversation, user_text, assistant_text

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

# a scripted provider: first turn asks for a tool, second turn answers
class ScriptedProvider:
    def __init__(self, turns): self.turns = list(turns); self.calls = 0
    def __call__(self, messages, specs):
        t = self.turns[self.calls]; self.calls += 1
        return t

def fake_executor(name, args, specs):
    return f"result:{name}:{args.get('x')}"

turns = [
    {"tool_calls": [{"id": "a1", "name": "do_it", "args": {"x": 7}}]},
    {"text": "final answer using result 7"},
]
prov = ScriptedProvider(turns)
messages = [user_text("run it")]
text, msgs = run_tool_conversation(messages, [], fake_executor, prov, max_steps=6)
ok(text == "final answer using result 7", "returns provider's final text")
ok(prov.calls == 2, "looped once for the tool, once for the answer")
# messages now contain the tool_call and its tool_result
kinds = [b["type"] for m in msgs for b in m["content"]]
ok("tool_call" in kinds and "tool_result" in kinds, "tool_call + tool_result recorded")
tr = [b for m in msgs for b in m["content"] if b["type"] == "tool_result"][0]
ok(tr["id"] == "a1" and "result:do_it:7" in tr["text"], "tool_result carries id + text")

# max_steps guard: a provider that only ever asks for tools
loop_prov = ScriptedProvider([{"tool_calls": [{"id": "x", "name": "t", "args": {}}]}] * 10)
text2, _ = run_tool_conversation([user_text("go")], [], fake_executor, loop_prov, max_steps=3)
ok("limit" in text2.lower(), "hitting max_steps returns a limit message")
ok(loop_prov.calls == 3, "stopped at max_steps")

print(f"test_tool_loop: {checks} checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_tool_loop.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.tool_loop'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/agent/tool_loop.py
"""The provider-agnostic tool loop.

Pure orchestration: no Streamlit, no SDK imports. `provider_turn` (one SDK
round-trip, neutral-in/neutral-out) and `executor` are injected, so the loop is
unit-testable with a scripted fake provider. Neutral message shape:

    {"role": "user"|"assistant", "content": [block, ...]}
    block: {"type":"text","text":str}
           {"type":"tool_call","id":str,"name":str,"args":dict}   (assistant)
           {"type":"tool_result","id":str,"text":str}             (user turn)
"""

DEFAULT_MAX_STEPS = 6


def user_text(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def assistant_text(text):
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def run_tool_conversation(messages, specs, executor, provider_turn,
                          max_steps=DEFAULT_MAX_STEPS):
    """Drive one user turn to a final text answer, executing tool calls.

    Mutates and returns `messages` (the neutral history) plus the final text.
    """
    for _ in range(max_steps):
        turn = provider_turn(messages, specs)
        calls = turn.get("tool_calls")
        if calls:
            messages.append({
                "role": "assistant",
                "content": [{"type": "tool_call", "id": c["id"],
                             "name": c["name"], "args": c.get("args") or {}}
                            for c in calls],
            })
            results = []
            for c in calls:
                text = executor(c["name"], c.get("args") or {}, specs)
                results.append({"type": "tool_result", "id": c["id"], "text": text})
            messages.append({"role": "user", "content": results})
            continue
        text = turn.get("text", "")
        messages.append(assistant_text(text))
        return text, messages
    limit_msg = ("I reached my step limit while working on that. "
                 "Here's what I have so far — try narrowing the request.")
    messages.append(assistant_text(limit_msg))
    return limit_msg, messages
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_tool_loop.py`
Expected: PASS — `test_tool_loop: N checks passed`

- [ ] **Step 5: Commit**

```bash
git add src/agent/tool_loop.py tests/test_tool_loop.py
git commit -m "feat: pure provider-agnostic tool loop"
```

---

## Task 3: Provider turn adapters (Gemini + Claude) with base_url

**Files:**
- Modify: `src/agent/providers.py` (append adapters; thread `base_url` on Claude)
- Test: extend `tests/test_providers.py` (append checks; keep existing)

- [ ] **Step 1: Write the failing test (append to tests/test_providers.py)**

```python
# --- Phase 4.5: turn adapters translate neutral <-> SDK (mocked, no network) ---
from src.agent.providers import claude_tool_turn, gemini_tool_turn
from src.agent.tool_loop import user_text
from src.agent import tool_specs as _ts

def _sample(x: int = 1) -> dict:
    """Sample."""
    return {}
_specs = [_ts.spec_from_function(_sample)]

# Claude adapter: a mocked client returning a tool_use block -> neutral tool_calls
class _Block:
    def __init__(self, **kw): self.__dict__.update(kw)
class _Resp:
    def __init__(self, content, stop_reason): self.content = content; self.stop_reason = stop_reason
class _FakeMessages:
    def __init__(self, resp): self._resp = resp
    def create(self, **kw): self.kw = kw; return self._resp
class _FakeClient:
    def __init__(self, resp): self.messages = _FakeMessages(resp)

tool_resp = _Resp([_Block(type="tool_use", id="tu1", name="_sample", input={"x": 5})], "tool_use")
turn = claude_tool_turn(user_text("hi") and [user_text("hi")], _specs,
                        key="k", model="m", base_url="http://enterprise",
                        _client_factory=lambda **kw: _FakeClient(tool_resp))
assert turn["tool_calls"][0]["name"] == "_sample", "claude tool_use -> neutral tool_call"
assert turn["tool_calls"][0]["args"] == {"x": 5}, "claude input -> args"

text_resp = _Resp([_Block(type="text", text="done")], "end_turn")
fc = {"client": None}
def _factory(**kw): fc["client"] = kw; return _FakeClient(text_resp)
turn2 = claude_tool_turn([user_text("hi")], _specs, key="k", model="m",
                         base_url="http://enterprise", _client_factory=_factory)
assert turn2["text"] == "done", "claude text -> neutral text"
assert fc["client"]["base_url"] == "http://enterprise", "base_url threaded to client"

print("test_providers: Phase 4.5 turn-adapter checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_providers.py`
Expected: FAIL — `ImportError: cannot import name 'claude_tool_turn'`

- [ ] **Step 3: Write minimal implementation (append to src/agent/providers.py)**

```python
# ── Phase 4.5: provider-agnostic tool-turn adapters ──────────────────────────
# Each takes neutral messages + tool specs, does ONE SDK round-trip, and returns
# either {"text": str} or {"tool_calls": [{"id","name","args"}]}.


def _specs_to_claude(specs):
    return [{"name": s["name"], "description": s["description"],
             "input_schema": s["input_schema"]} for s in specs]


def _messages_to_claude(messages):
    """Neutral messages -> Anthropic messages list."""
    out = []
    for m in messages:
        content = []
        for b in m["content"]:
            if b["type"] == "text":
                content.append({"type": "text", "text": b["text"]})
            elif b["type"] == "tool_call":
                content.append({"type": "tool_use", "id": b["id"],
                                "name": b["name"], "input": b["args"]})
            elif b["type"] == "tool_result":
                content.append({"type": "tool_result", "tool_use_id": b["id"],
                                "content": b["text"]})
        out.append({"role": m["role"], "content": content})
    return out


def claude_tool_turn(messages, specs, *, key, model, system_instruction=None,
                     base_url=None, max_tokens=1024, _client_factory=None):
    """One Claude round-trip over the neutral protocol."""
    if _client_factory is None:
        import anthropic
        _client_factory = anthropic.Anthropic
    client = _client_factory(api_key=key, base_url=base_url)
    kwargs = {"model": model, "max_tokens": max_tokens,
              "tools": _specs_to_claude(specs),
              "messages": _messages_to_claude(messages)}
    if system_instruction:
        kwargs["system"] = system_instruction
    resp = client.messages.create(**kwargs)
    tool_calls = [{"id": b.id, "name": b.name, "args": dict(b.input)}
                  for b in resp.content if getattr(b, "type", None) == "tool_use"]
    if tool_calls:
        return {"tool_calls": tool_calls}
    text = "".join(getattr(b, "text", "") for b in resp.content
                   if getattr(b, "type", None) == "text")
    return {"text": text}


def _specs_to_gemini(specs):
    """Neutral specs -> Gemini function declarations (dict form)."""
    return [{"function_declarations": [
        {"name": s["name"], "description": s["description"],
         "parameters": s["input_schema"]} for s in specs]}]


def _messages_to_gemini(messages):
    """Neutral messages -> Gemini contents (role 'model' for assistant)."""
    import google.generativeai as genai  # noqa: F401 (protos used below)
    from google.generativeai import protos
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        parts = []
        for b in m["content"]:
            if b["type"] == "text":
                parts.append(protos.Part(text=b["text"]))
            elif b["type"] == "tool_call":
                parts.append(protos.Part(function_call=protos.FunctionCall(
                    name=b["name"], args=b["args"])))
            elif b["type"] == "tool_result":
                parts.append(protos.Part(function_response=protos.FunctionResponse(
                    name=b["id"], response={"result": b["text"]})))
        contents.append(protos.Content(role=role, parts=parts))
    return contents


def gemini_tool_turn(messages, specs, *, key, model, system_instruction=None,
                     base_url=None, _model_factory=None):
    """One Gemini round-trip over the neutral protocol (manual function calling)."""
    import google.generativeai as genai
    if _model_factory is None:
        genai.configure(api_key=key)
        _model_factory = lambda: genai.GenerativeModel(
            model_name=model, tools=_specs_to_gemini(specs),
            system_instruction=system_instruction)
    gmodel = _model_factory()
    resp = gmodel.generate_content(_messages_to_gemini(messages),
                                   request_options=_FAST_FAIL)
    tool_calls = []
    for part in resp.candidates[0].content.parts:
        fc = getattr(part, "function_call", None)
        if fc and fc.name:
            tool_calls.append({"id": fc.name, "name": fc.name,
                               "args": dict(fc.args)})
    if tool_calls:
        return {"tool_calls": tool_calls}
    return {"text": resp.text}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_providers.py`
Expected: PASS (existing checks + the new turn-adapter checks). *(Gemini adapter is exercised end-to-end in the boot test, Task 5; its unit path uses the injected `_model_factory`.)*

- [ ] **Step 5: Commit**

```bash
git add src/agent/providers.py tests/test_providers.py
git commit -m "feat: Gemini + Claude tool-turn adapters (neutral <-> SDK) with base_url"
```

---

## Task 4: Config backend profiles + base_url

**Files:**
- Modify: `src/config.py` (add `LLM_BACKEND`, `BACKEND_PROFILES`; generalize `build_llm_arsenal`)
- Test: `tests/test_config.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py — standalone script
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import config

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

# dev profile reproduces the legacy Gemini-first-then-Claude arsenal, with base_url
arsenal = config.build_llm_arsenal_for_profile(
    {"providers": [
        {"provider": "gemini", "keys": ["g1", "g2"], "models": ["mA", "mB"], "base_url": None},
        {"provider": "claude", "keys": ["c1"], "models": ["cX"], "base_url": "http://ent"},
    ]})
ok(arsenal[0]["provider"] == "gemini", "gemini combos come first")
ok(arsenal[0]["base_url"] is None, "gemini base_url defaults None")
ok(arsenal[-1] == {"provider": "claude", "key": "c1", "model": "cX",
                   "label": "Claude+cX", "base_url": "http://ent"},
   "claude combo carries base_url + label")
ok(len(arsenal) == 2 * 2 + 1, "N keys x M models per provider")

# a claude provider with no keys contributes nothing
arsenal2 = config.build_llm_arsenal_for_profile(
    {"providers": [{"provider": "claude", "keys": [], "models": ["cX"], "base_url": None}]})
ok(arsenal2 == [], "no keys -> no combos")

# LLM_BACKEND defaults to 'dev' and the live LLM_ARSENAL still has base_url on every combo
ok(config.LLM_BACKEND in config.BACKEND_PROFILES, "LLM_BACKEND selects a real profile")
ok(all("base_url" in c for c in config.LLM_ARSENAL), "every live combo has base_url")

print(f"test_config: {checks} checks passed")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests\test_config.py`
Expected: FAIL — `AttributeError: module 'src.config' has no attribute 'build_llm_arsenal_for_profile'`

- [ ] **Step 3: Write minimal implementation**

In `src/config.py`, after the existing `build_llm_arsenal(...)` definition, add the profile machinery and rebuild `LLM_ARSENAL` from it. Keep the old `build_llm_arsenal` (still imported/tested elsewhere).

```python
# ── Phase 4.5: config-swappable backend profiles ─────────────────────────────
# One setting (LLM_BACKEND) picks a named profile. 'dev' = today's behavior. A
# 'prod' profile (single provider, company key, enterprise base_url) is added
# later with NO code change. Each combo now carries base_url (default None).

LLM_BACKEND = _get_secret("LLM_BACKEND") or "dev"

BACKEND_PROFILES = {
    "dev": {"providers": [
        {"provider": "gemini", "keys": API_KEYS, "models": MODELS, "base_url": None},
        {"provider": "claude",
         "keys": [ANTHROPIC_API_KEY] if ANTHROPIC_API_KEY else [],
         "models": CLAUDE_MODELS, "base_url": None},
    ]},
}


def build_llm_arsenal_for_profile(profile):
    """Build the combo rotation from a backend profile. Pure; no network.

    Each combo: {"provider","key","model","label","base_url"}. Providers are
    emitted in profile order (so 'dev' keeps Gemini-first-then-Claude). Labels
    match the legacy scheme: gemini -> 'Key{n}+{model}', else '{Provider}+{model}'.
    """
    arsenal = []
    for prov in profile.get("providers", []):
        provider = prov["provider"]
        base_url = prov.get("base_url")
        for i, key in enumerate(prov.get("keys", [])):
            for model in prov.get("models", []):
                if provider == "gemini":
                    label = f"Key{i+1}+{model}"
                else:
                    label = f"{provider.capitalize()}+{model}"
                arsenal.append({"provider": provider, "key": key, "model": model,
                                "label": label, "base_url": base_url})
    return arsenal


_active_profile = BACKEND_PROFILES.get(LLM_BACKEND, BACKEND_PROFILES["dev"])
LLM_ARSENAL = build_llm_arsenal_for_profile(_active_profile)
```

**Important:** delete the old `LLM_ARSENAL = build_llm_arsenal(...)` assignment line (line ~96) so the profile-built arsenal is the live one. Leave the `build_llm_arsenal` *function* in place (other tests import it).

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_config.py`
Expected: PASS — `test_config: N checks passed`

- [ ] **Step 5: Run the existing provider test (ensure legacy arsenal test still holds)**

Run: `..\venv\Scripts\python.exe tests\test_providers.py`
Expected: PASS (the existing `build_llm_arsenal` unit checks are unaffected).

- [ ] **Step 6: Commit**

```bash
git add src/config.py tests/test_config.py
git commit -m "feat: config-swappable LLM backend profiles + base_url seam"
```

---

## Task 5: Rework call_agent to drive the loop with failover

**Files:**
- Modify: `src/agent/caller.py` (`call_agent`; add a `_provider_turn_for` helper)
- Test: boot via `streamlit.testing.AppTest` + a scripted `call_agent`

- [ ] **Step 1: Replace `call_agent` and add the combo→turn dispatcher**

Replace the whole `call_agent` function (lines ~160-172) with the loop-driven version, and add a helper above it. Keep `generate()` and `probe_health()` unchanged.

```python
from functools import partial

from src.agent.tool_specs import TOOL_SPECS, execute_tool
from src.agent.tool_loop import run_tool_conversation, user_text
from src.agent.providers import gemini_tool_turn, claude_tool_turn


def _provider_turn_for(combo, system_instruction):
    """Bind a combo to a neutral provider_turn(messages, specs) callable."""
    if combo["provider"] == "claude":
        return partial(claude_tool_turn, key=combo["key"], model=combo["model"],
                       system_instruction=system_instruction,
                       base_url=combo.get("base_url"))
    return partial(gemini_tool_turn, key=combo["key"], model=combo["model"],
                   system_instruction=system_instruction,
                   base_url=combo.get("base_url"))


def call_agent(prompt: str) -> str:
    """Provider-agnostic tool-using chat over the neutral history + LLM_ARSENAL.

    Rotates combos on quota/permission errors (Gemini first, Claude on
    exhaustion), driving run_tool_conversation with the combo's turn adapter.
    """
    arsenal = LLM_ARSENAL
    if not arsenal:
        return ("⚠️ No API keys configured. "
                "Please add GEMINI_KEY_1 to your .env file.")

    messages = st.session_state.chat_history + [user_text(prompt)]
    history_len = len(st.session_state.chat_history)

    for _ in range(len(arsenal)):
        idx = st.session_state.model_idx % len(arsenal)
        combo = arsenal[idx]
        working = [m for m in messages]  # fresh copy per attempt
        try:
            provider_turn = _provider_turn_for(combo, SYSTEM_PROMPT)
            text, final_msgs = run_tool_conversation(
                working, TOOL_SPECS, execute_tool, provider_turn)
            st.session_state['active_model'] = combo['label']
            st.session_state.chat_history = final_msgs
            return text
        except Exception:
            # rollback any partial turn, advance to the next combo
            st.session_state.chat_history = st.session_state.chat_history[:history_len]
            st.session_state.model_idx += 1
            continue

    return (
        f"⚠️ All {len(arsenal)} API combinations are quota-exhausted right now. "
        f"The analysis tabs still work fully. Gemini quotas reset at midnight "
        f"Pacific time. For more capacity, add API keys or an ANTHROPIC_API_KEY."
    )
```

- [ ] **Step 2: Write a boot + scripted-agent test**

```python
# tests/test_call_agent_boot.py — standalone script
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 1) App boots with 0 exceptions (canonical data, empty + restored chat covered
#    by test_streamlit-style AppTest here just for the chat wiring).
from streamlit.testing.v1 import AppTest
at = AppTest.from_file("app.py", default_timeout=120)
at.run()
assert len(at.exception) == 0, f"boot exceptions: {[e.value for e in at.exception]}"

# 2) The loop wiring: a scripted provider drives a real tool end-to-end without net.
from src.agent.tool_loop import run_tool_conversation, user_text
from src.agent.tool_specs import TOOL_SPECS, execute_tool

turns = [
    {"tool_calls": [{"id": "s1", "name": "get_current_stats", "args": {}}]},
    {"text": "Here is your status."},
]
i = {"n": 0}
def scripted(messages, specs):
    t = turns[i["n"]]; i["n"] += 1; return t

text, msgs = run_tool_conversation([user_text("status?")], TOOL_SPECS,
                                   execute_tool, scripted)
assert text == "Here is your status.", "scripted agent returns final text"
assert any(b["type"] == "tool_result" for m in msgs for b in m["content"]), \
    "a real tool executed and fed a result back"

print("test_call_agent_boot: checks passed")
```

- [ ] **Step 3: Run the boot test**

Run: `..\venv\Scripts\python.exe tests\test_call_agent_boot.py`
Expected: PASS — `test_call_agent_boot: checks passed`. If a tool raises inside `execute_tool` (Instacart-bound tool on canonical data), it is caught and returned as text — the assertion on `tool_result` still holds.

- [ ] **Step 4: Commit**

```bash
git add src/agent/caller.py tests/test_call_agent_boot.py
git commit -m "feat: call_agent drives the provider-agnostic loop with failover"
```

---

## Task 6: Persistence for neutral history

**Files:**
- Modify: `src/utils/persistence.py`
- Test: extend `tests/test_persistence.py` (append)

- [ ] **Step 1: Inspect current save/load**

Read `src/utils/persistence.py`. It currently serializes `ui_history` chart DataFrames and Gemini `chat_history` to `{role, text}`. The `chat_history` is now the **neutral message list** (already plain JSON: text / tool_call / tool_result blocks). Change `save_session` to store `chat_history` **as-is**, and `load_session` to return it as-is only when it matches the neutral shape.

- [ ] **Step 2: Write the failing test (append to tests/test_persistence.py)**

```python
# --- Phase 4.5: neutral chat_history round-trips; old shape is discarded ---
from src.utils import persistence as _p

# a neutral history round-trips unchanged
neutral = [
    {"role": "user", "content": [{"type": "text", "text": "hi"}]},
    {"role": "assistant", "content": [
        {"type": "tool_call", "id": "t1", "name": "get_current_stats", "args": {}}]},
    {"role": "user", "content": [{"type": "tool_result", "id": "t1", "text": "ok"}]},
]
assert _p.is_neutral_history(neutral) is True, "recognizes neutral history"

# an old Gemini-shaped history ({role,text}) is rejected as non-neutral
old = [{"role": "user", "text": "hi"}, {"role": "model", "text": "hello"}]
assert _p.is_neutral_history(old) is False, "old shape is not neutral"
print("test_persistence: Phase 4.5 neutral-history checks passed")
```

- [ ] **Step 3: Implement `is_neutral_history` and use it in load**

Add to `src/utils/persistence.py`:

```python
def is_neutral_history(history):
    """True if `history` is the Phase-4.5 neutral message list.

    Neutral = list of {"role","content":[blocks]} where each block is a dict
    with a "type". Guards restore against pre-4.5 saved sessions.
    """
    if not isinstance(history, list):
        return False
    for m in history:
        if not isinstance(m, dict) or "content" not in m or "role" not in m:
            return False
        if not isinstance(m["content"], list):
            return False
        if not all(isinstance(b, dict) and "type" in b for b in m["content"]):
            return False
    return True
```

In `load_session`, where the saved `chat_history` is read, wrap it:

```python
    saved_chat = data.get("chat_history", [])
    if not is_neutral_history(saved_chat):
        saved_chat = []   # discard incompatible pre-4.5 history (best-effort)
```

In `save_session`, store `st.session_state['chat_history']` directly (it is already
JSON-safe neutral blocks) instead of the old `{role, text}` flattening. Remove any
Gemini-protobuf handling for `chat_history`.

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests\test_persistence.py`
Expected: PASS (existing checks + the new ones).

- [ ] **Step 5: Commit**

```bash
git add src/utils/persistence.py tests/test_persistence.py
git commit -m "feat: persist neutral chat history; discard incompatible old sessions"
```

---

## Task 7: Full suite + boot + journal

**Files:**
- Modify: `CLAUDE.md` (journal entry at top of Project Journal)

- [ ] **Step 1: Run every no-network suite**

```
..\venv\Scripts\python.exe tests\test_tool_specs.py
..\venv\Scripts\python.exe tests\test_tool_loop.py
..\venv\Scripts\python.exe tests\test_providers.py
..\venv\Scripts\python.exe tests\test_config.py
..\venv\Scripts\python.exe tests\test_call_agent_boot.py
..\venv\Scripts\python.exe tests\test_persistence.py
..\venv\Scripts\python.exe tests\test_levers.py
..\venv\Scripts\python.exe tests\test_app_data.py
..\venv\Scripts\python.exe tests\test_metrics.py
..\venv\Scripts\python.exe tests\test_scoring.py
..\venv\Scripts\python.exe tests\test_simulation.py
..\venv\Scripts\python.exe tests\test_canonical.py
..\venv\Scripts\python.exe tests\test_demo_adapter.py
..\venv\Scripts\python.exe tests\test_router.py
..\venv\Scripts\python.exe tests\test_reflexive.py
..\venv\Scripts\python.exe tests\test_orchestrator.py
..\venv\Scripts\python.exe tests\test_insights.py
..\venv\Scripts\python.exe tests\test_proactive.py
..\venv\Scripts\python.exe tests\test_watches.py
..\venv\Scripts\python.exe tests\test_memory.py
```
Expected: every script prints its pass line and exits 0.

- [ ] **Step 2: Final boot smoke test**

Headless `AppTest` boot (Task 5 test already covers it) → 0 exceptions.

- [ ] **Step 3: Add the journal entry**

Prepend to the Project Journal in `CLAUDE.md` a `### 2026-07-06 — Intelligence Layer / Chat-First, Phase 4.5: Provider-agnostic tool loop + config-swappable backend` entry summarizing: neutral tool-spec registry (`tool_specs.py`); pure loop (`tool_loop.py`); Gemini+Claude turn adapters with `base_url`; `call_agent` now fails over Gemini→Claude on the tool path; `LLM_BACKEND` profiles (dev = unchanged); neutral chat history + persistence guard; tools NOT re-anchored (Phase 5). Note default behavior is identical to Phase 4.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: journal entry for Phase 4.5 provider-agnostic tool loop"
```

---

## Self-Review notes (author)

- **Spec coverage:** neutral loop ✅ (T2); tool specs + executor safety net ✅ (T1); Gemini+Claude turn adapters + base_url ✅ (T3); config profiles + base_url seam ✅ (T4); call_agent failover + neutral history ✅ (T5); persistence round-trip + old-session guard ✅ (T6); success criteria (Claude-on-exhaustion, config-swap, identical default, no-crash tool, suites green) exercised across T3–T7.
- **Deferred, documented, not gaps:** tools.py canonical re-anchoring + conversational degradation → Phase 5; prod host selection / Gemini-via-Vertex → later (base_url seam only).
- **Type consistency:** neutral block shapes identical across `tool_loop.py`, providers adapters, and persistence guard (`{"type","text"}` / `{"type":"tool_call","id","name","args"}` / `{"type":"tool_result","id","text"}`). Combo shape `{"provider","key","model","label","base_url"}` consistent T4/T5. `execute_tool(name, args, specs)` signature identical T1/T2/T5.
- **Risk flagged for execution:** the Gemini `protos` translation in `gemini_tool_turn` (function_call/function_response) is the one spot needing live-SDK verification; its unit test uses an injected `_model_factory`, and the real path is covered by the boot test. Adjust protobuf specifics during execution if the SDK differs.
