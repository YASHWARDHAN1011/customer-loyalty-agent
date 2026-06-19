# Phase 5 — Provider Abstraction (Gemini → Claude failover) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When all Gemini key×model combos are quota-exhausted, the agent's text/reasoning calls automatically fall through to Claude instead of failing.

**Architecture:** A unified `LLM_ARSENAL` (Gemini combos first, then Claude combos if an Anthropic key exists) drives `generate()`'s existing `model_idx` rotation. Tool-less text calls dispatch to a per-provider adapter; the tool-using chat path stays Gemini-only with today's inline code unchanged. New logic lives in pure, unit-testable helpers (`build_llm_arsenal`, `is_eligible`, `provider_text`).

**Tech Stack:** Python, `google-generativeai`, `anthropic` (new), Streamlit (caller/UI only), standalone test scripts (not pytest).

---

## Conventions (read once)

- **Tests are standalone scripts**, not pytest. Each defines `check(name, cond)` printing `PASS`/`FAIL`, `sys.exit(1)` on failure (harness shown in Task 1). Run from the inner dir (`customer-loyalty-agent/customer-loyalty-agent/`): `..\venv\Scripts\python.exe tests/test_providers.py`
- **Keep new pure logic Streamlit-free and network-free** so it's unit-testable: `build_llm_arsenal` (in `config.py`), and `is_eligible` / `provider_text` (in `providers.py`). The real SDK adapters and `caller.generate()` are Streamlit/network-bound and are verified via the app booting HTTP 200 + the existing suites.
- **NO "Co-Authored-By: Claude" trailer** on commits (repo convention).
- **Claude model id:** `claude-haiku-4-5-20251001`.
- **Combo dict shape:** `{"provider": "gemini"|"claude", "key": str, "model": str, "label": str}`.
- **Existing `generate()` contract:** returns `{"text", "model_label", "chat"}` (`chat` is a Gemini chat object for the tool path, else `None`). Callers of the tool-less path read only `result["text"]`.

---

## File Structure

- **Modify** `src/config.py` — load `ANTHROPIC_API_KEY`, add `CLAUDE_MODELS`, add pure `build_llm_arsenal(...)`, build `LLM_ARSENAL` (keep `MODEL_ARSENAL` as-is).
- **Create** `src/agent/providers.py` — `gemini_generate_text`, `claude_generate_text` adapters + pure `is_eligible` / `provider_text`.
- **Modify** `src/agent/caller.py` — `generate()` rotates over `LLM_ARSENAL`, dispatches via adapters for tool-less calls, keeps the Gemini tool path inline & unchanged.
- **Modify** `requirements.txt` — add `anthropic`.
- **Modify** `src/ui/sidebar.py` and `src/ui/tabs/chat.py` — combo counters use `LLM_ARSENAL`.
- **Create** `tests/test_providers.py`.
- **Modify** `CLAUDE.md` — journal entry.

---

## Task 1: Unified arsenal in config

Add the Anthropic key + Claude models and a pure arsenal builder.

**Files:**
- Modify: `src/config.py`
- Test: `tests/test_providers.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_providers.py`:

```python
"""Standalone tests for provider abstraction. No network, no Streamlit."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def main():
    from src.config import build_llm_arsenal

    # With an Anthropic key: Gemini combos first, then Claude combos.
    a = build_llm_arsenal(["k1", "k2"], ["m1", "m2"], "anthro", ["c1"])
    check("count = gemini*models + claude", len(a) == 2 * 2 + 1)
    check("gemini combos first", all(c["provider"] == "gemini" for c in a[:4]))
    check("claude combo last", a[-1]["provider"] == "claude")
    check("gemini combo shape",
          set(a[0].keys()) == {"provider", "key", "model", "label"})
    check("claude combo uses anthropic key + model",
          a[-1]["key"] == "anthro" and a[-1]["model"] == "c1")
    check("gemini labels keyed", a[0]["label"] == "Key1+m1")

    # No Anthropic key -> Gemini-only (identical to today).
    b = build_llm_arsenal(["k1"], ["m1"], None, ["c1"])
    check("no key -> no claude", all(c["provider"] == "gemini" for c in b))
    check("no key -> len 1", len(b) == 1)

    # Empty-string key is falsy -> no claude.
    e = build_llm_arsenal(["k1"], ["m1"], "", ["c1"])
    check("empty key -> no claude", all(c["provider"] == "gemini" for c in e))

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run, confirm it FAILS** (no `build_llm_arsenal`):

Run: `..\venv\Scripts\python.exe tests/test_providers.py`
Expected: FAIL — `ImportError: cannot import name 'build_llm_arsenal'`.

- [ ] **Step 3: Implement in `src/config.py`.** Find the existing block that ends the model config (right after the `MODEL_ARSENAL = [...]` list comprehension, lines ~59-63). Immediately AFTER that `MODEL_ARSENAL` list, add:

```python
# ── Provider abstraction: Claude failover tier ───────────────────────────────
# When Gemini combos are quota-exhausted, tool-less text calls fall through to
# Claude. If no Anthropic key is configured, the arsenal is Gemini-only and
# behavior is identical to before.

ANTHROPIC_API_KEY = _get_secret("ANTHROPIC_API_KEY")

CLAUDE_MODELS = ["claude-haiku-4-5-20251001"]


def build_llm_arsenal(api_keys, models, anthropic_key, claude_models):
    """Build the unified provider rotation: Gemini combos first, then Claude.

    Pure (no Streamlit, no network). Each entry is
    {"provider", "key", "model", "label"}. Claude combos are appended only when
    `anthropic_key` is truthy.
    """
    arsenal = [
        {"provider": "gemini", "key": k, "model": m, "label": f"Key{i+1}+{m}"}
        for i, k in enumerate(api_keys)
        for m in models
    ]
    if anthropic_key:
        arsenal += [
            {"provider": "claude", "key": anthropic_key, "model": m,
             "label": f"Claude+{m}"}
            for m in claude_models
        ]
    return arsenal


LLM_ARSENAL = build_llm_arsenal(API_KEYS, MODELS, ANTHROPIC_API_KEY, CLAUDE_MODELS)
```

- [ ] **Step 4: Run, confirm ALL checks PASS:**

Run: `..\venv\Scripts\python.exe tests/test_providers.py`
Expected: PASS — "10 checks passed."

- [ ] **Step 5: Commit:**

```bash
git add src/config.py tests/test_providers.py
git commit -m "Phase 5: unified LLM_ARSENAL with Claude failover tier in config"
```

---

## Task 2: Provider adapters + dispatch helpers

The two SDK adapters and the pure `is_eligible` / `provider_text` helpers.

**Files:**
- Create: `src/agent/providers.py`
- Test: `tests/test_providers.py`

- [ ] **Step 1: Append failing tests.** In `tests/test_providers.py`, insert this block in `main()` immediately before the final `print(...)` line:

```python
    # --- dispatch helpers (pure) ---
    from src.agent.providers import is_eligible, provider_text

    g = {"provider": "gemini", "key": "k", "model": "m", "label": "Key1+m"}
    c = {"provider": "claude", "key": "a", "model": "c1", "label": "Claude+c1"}

    # eligibility: tool-using calls are Gemini-only
    check("gemini eligible with tools", is_eligible(g, True) is True)
    check("claude NOT eligible with tools", is_eligible(c, True) is False)
    check("claude eligible without tools", is_eligible(c, False) is True)

    # provider_text dispatches to the right adapter
    def gfn(prompt, *, system_instruction, key, model):
        return f"G:{prompt}:{model}"

    def cfn(prompt, *, system_instruction, key, model):
        return f"C:{prompt}:{model}"

    check("dispatch gemini",
          provider_text(g, "hi", system_instruction="s", gemini_fn=gfn,
                        claude_fn=cfn) == "G:hi:m")
    check("dispatch claude",
          provider_text(c, "hi", system_instruction="s", gemini_fn=gfn,
                        claude_fn=cfn) == "C:hi:c1")

    # simulated cross-provider failover: gemini adapter fails, claude succeeds
    def boom_g(prompt, *, system_instruction, key, model):
        raise RuntimeError("quota")

    def ok_c(prompt, *, system_instruction, key, model):
        return "ANSWER"

    arsenal = [g, dict(g, label="Key2+m"), c]
    result, landed = None, None
    idx = 0
    for _ in range(len(arsenal)):
        combo = arsenal[idx % len(arsenal)]
        if not is_eligible(combo, False):
            idx += 1; continue
        try:
            result = provider_text(combo, "p", system_instruction="s",
                                   gemini_fn=boom_g, claude_fn=ok_c)
            landed = combo["provider"]
            break
        except Exception:
            idx += 1; continue
    check("failover reaches claude", result == "ANSWER" and landed == "claude")
```

- [ ] **Step 2: Run, confirm it FAILS** (no `providers` module):

Run: `..\venv\Scripts\python.exe tests/test_providers.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.providers'`.

- [ ] **Step 3: Create `src/agent/providers.py`:**

```python
"""
LLM provider adapters + dispatch helpers.

Two thin, non-streaming text adapters with one shared signature
(prompt, *, system_instruction, key, model) -> str, plus pure helpers used by
caller.generate() to route a combo to the right provider and to keep tool-using
calls on Gemini. The adapters raise on SDK error so the caller's rotation can
fail over. Grounding is unaffected — providers only narrate.
"""

import google.generativeai as genai


def gemini_generate_text(prompt, *, system_instruction, key, model):
    """One non-streaming Gemini text completion."""
    genai.configure(api_key=key)
    m = genai.GenerativeModel(model_name=model,
                              system_instruction=system_instruction)
    response = m.generate_content(prompt)
    return response.text


def claude_generate_text(prompt, *, system_instruction, key, model):
    """One non-streaming Claude text completion (system prompt is cached)."""
    import anthropic  # lazy: only needed when a Claude combo is actually used
    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": system_instruction,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    )


def is_eligible(combo, has_tools):
    """Tool-using calls are Gemini-only; tool-less calls accept any provider."""
    return (not has_tools) or combo["provider"] == "gemini"


def provider_text(combo, prompt, *, system_instruction,
                  gemini_fn=gemini_generate_text,
                  claude_fn=claude_generate_text):
    """Dispatch a tool-less text call to the combo's provider adapter."""
    if combo["provider"] == "claude":
        return claude_fn(prompt, system_instruction=system_instruction,
                         key=combo["key"], model=combo["model"])
    return gemini_fn(prompt, system_instruction=system_instruction,
                     key=combo["key"], model=combo["model"])
```

- [ ] **Step 4: Run, confirm ALL checks PASS:**

Run: `..\venv\Scripts\python.exe tests/test_providers.py`
Expected: PASS — "18 checks passed."

- [ ] **Step 5: Add the dependency.** Append a line to `requirements.txt`:

```
anthropic
```

- [ ] **Step 6: Install it (so the app can import it later):**

Run: `..\venv\Scripts\python.exe -m pip install anthropic`
Expected: installs successfully (or "already satisfied").

- [ ] **Step 7: Commit:**

```bash
git add src/agent/providers.py tests/test_providers.py requirements.txt
git commit -m "Phase 5: provider adapters (Gemini/Claude) + dispatch helpers"
```

---

## Task 3: Route `generate()` through the arsenal

Make `generate()` rotate over `LLM_ARSENAL`, dispatch tool-less calls via adapters, and keep the Gemini tool path inline & unchanged.

**Files:**
- Modify: `src/agent/caller.py`

- [ ] **Step 1: Update imports.** Replace this line in `src/agent/caller.py`:

```python
from src.config import MODEL_ARSENAL, API_KEYS, MODELS, SYSTEM_PROMPT
from src.agent.tools import ALL_TOOLS
```

with:

```python
from src.config import LLM_ARSENAL, API_KEYS, SYSTEM_PROMPT
from src.agent.tools import ALL_TOOLS
from src.agent.providers import (
    gemini_generate_text, claude_generate_text, is_eligible, provider_text,
)
```

- [ ] **Step 2: Replace the entire `generate()` function** with this version (keeps the Gemini tool path's behavior exactly; adds tool-less adapter dispatch + Claude failover; adds injectable `arsenal`/adapter seams used by callers only in tests):

```python
def generate(
    prompt: str,
    *,
    system_instruction: str,
    tools=None,
    history=None,
    automatic_function_calling: bool = False,
    arsenal=None,
    gemini_text_fn=None,
    claude_text_fn=None,
) -> dict:
    """Send one message to an LLM, rotating through LLM_ARSENAL on failure.

    Tool-using calls (tools is not None) are Gemini-only and use the inline chat
    path (returns a `chat`). Tool-less text calls dispatch to the combo's provider
    adapter and return {"text", "model_label", "chat": None}; when Gemini combos
    are exhausted they fall through to Claude. Advances st.session_state.model_idx
    and rolls back ui_history on each failed attempt.
    """
    arsenal = LLM_ARSENAL if arsenal is None else arsenal
    g_text = gemini_text_fn or gemini_generate_text
    c_text = claude_text_fn or claude_generate_text

    if not arsenal:
        return {
            "text": ("⚠️ No API keys configured. "
                     "Please add GEMINI_KEY_1 to your .env file."),
            "model_label": None,
            "chat": None,
        }

    ui_snapshot = len(st.session_state.ui_history)

    for _ in range(len(arsenal)):
        idx = st.session_state.model_idx % len(arsenal)
        combo = arsenal[idx]

        # Tool-using calls are Gemini-only (automatic function calling).
        if not is_eligible(combo, tools is not None):
            st.session_state.model_idx += 1
            continue

        if tools is not None:
            # Gemini tool path — unchanged behavior.
            try:
                genai.configure(api_key=combo['key'])
                model = genai.GenerativeModel(
                    model_name=combo['model'],
                    tools=tools,
                    system_instruction=system_instruction,
                )
                chat = model.start_chat(
                    history=history or [],
                    enable_automatic_function_calling=automatic_function_calling,
                )
                response = chat.send_message(prompt)
                st.session_state['active_model'] = combo['label']
                return {"text": response.text, "model_label": combo['label'],
                        "chat": chat}
            except google_exceptions.InvalidArgument as e:
                err = str(e)
                if "ToolType" in err or "function" in err.lower():
                    st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
                    st.session_state.model_idx += 1
                    continue
                return {"text": f"⚠️ Invalid request: {err}",
                        "model_label": None, "chat": None}
            except (google_exceptions.ResourceExhausted,
                    google_exceptions.NotFound,
                    google_exceptions.PermissionDenied):
                st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
                st.session_state.model_idx += 1
                continue
            except Exception as e:
                return {"text": f"⚠️ Unexpected error: {str(e)}",
                        "model_label": None, "chat": None}
        else:
            # Tool-less text path — provider adapter; rotate on any failure.
            try:
                text = provider_text(
                    combo, prompt, system_instruction=system_instruction,
                    gemini_fn=g_text, claude_fn=c_text,
                )
                st.session_state['active_model'] = combo['label']
                return {"text": text, "model_label": combo['label'], "chat": None}
            except Exception:
                st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
                st.session_state.model_idx += 1
                continue

    return {
        "text": (
            f"⚠️ All {len(arsenal)} API combinations are quota-exhausted "
            f"right now. The analysis tabs still work fully. Gemini quotas reset "
            f"at midnight Pacific time. For more capacity, add API keys "
            f"(GEMINI_KEY_3, GEMINI_KEY_4, …) or an ANTHROPIC_API_KEY to your "
            f".env file."
        ),
        "model_label": None,
        "chat": None,
    }
```

- [ ] **Step 3: Verify `caller.py` parses and imports cleanly** (UTF-8; use the venv python):

Run: `..\venv\Scripts\python.exe -c "import ast; ast.parse(open('src/agent/caller.py',encoding='utf-8').read()); print('caller.py parses')"`
Expected: `caller.py parses`.

- [ ] **Step 4: Run the no-network suites that exercise the agent layer** (they inject `generate_fn`, so they must stay green):

```
..\venv\Scripts\python.exe tests/test_proactive.py
..\venv\Scripts\python.exe tests/test_memory.py
..\venv\Scripts\python.exe tests/test_router.py
..\venv\Scripts\python.exe tests/test_orchestrator.py
..\venv\Scripts\python.exe tests/test_reflexive.py
```
Expected: all PASS.

- [ ] **Step 5: Commit:**

```bash
git add src/agent/caller.py
git commit -m "Phase 5: generate() rotates LLM_ARSENAL with Gemini->Claude failover"
```

---

## Task 4: Fix the combo counters in the UI

The sidebar/chat "combos remaining" indicators must count `LLM_ARSENAL` now that `model_idx` rotates over it.

**Files:**
- Modify: `src/ui/sidebar.py`
- Modify: `src/ui/tabs/chat.py`

- [ ] **Step 1: Update `src/ui/sidebar.py`.** Change its config import:

```python
from src.config import API_KEYS, MODEL_ARSENAL
```
to:
```python
from src.config import API_KEYS, LLM_ARSENAL
```
Then, in `render_sidebar`, replace every `MODEL_ARSENAL` reference in the API-status block with `LLM_ARSENAL` (there are four: `st.session_state.model_idx % len(MODEL_ARSENAL)`, `MODEL_ARSENAL[current_idx]`, `len(MODEL_ARSENAL) - used`, and `min(st.session_state.model_idx, len(MODEL_ARSENAL))`, plus the progress text `{len(MODEL_ARSENAL)}`). Use find/replace of `MODEL_ARSENAL` → `LLM_ARSENAL` within that function.

- [ ] **Step 2: Update `src/ui/tabs/chat.py`.** Change its config import:

```python
from src.config import API_KEYS, MODEL_ARSENAL
```
to:
```python
from src.config import API_KEYS, LLM_ARSENAL
```
Then replace the three `MODEL_ARSENAL` references in `render_chat`'s status block (`st.session_state.model_idx % len(MODEL_ARSENAL)`, `MODEL_ARSENAL[idx]`, and the two `len(MODEL_ARSENAL)` in the "Combos Remaining" metric) with `LLM_ARSENAL`.

- [ ] **Step 3: Verify both parse and no stray `MODEL_ARSENAL` remains in them** (UTF-8):

Run: `..\venv\Scripts\python.exe -c "import ast; [ast.parse(open(p,encoding='utf-8').read()) for p in ('src/ui/sidebar.py','src/ui/tabs/chat.py')]; print('both parse')"`
Expected: `both parse`.

Run: `..\venv\Scripts\python.exe -c "print('sidebar', 'MODEL_ARSENAL' in open('src/ui/sidebar.py',encoding='utf-8').read()); print('chat', 'MODEL_ARSENAL' in open('src/ui/tabs/chat.py',encoding='utf-8').read())"`
Expected: `sidebar False`, `chat False`.

- [ ] **Step 4: Commit:**

```bash
git add src/ui/sidebar.py src/ui/tabs/chat.py
git commit -m "Phase 5: UI combo counters reflect the full LLM_ARSENAL"
```

---

## Task 5: Journal entry + full verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the Project Journal entry.** At the TOP of the `## 📓 Project Journal` section in `CLAUDE.md` (above the Agentic Chat entry), add:

```markdown
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
```

- [ ] **Step 2: Update the technical-guidance sections of `CLAUDE.md`** (so the "how the app is wired" half isn't stale). Make these three exact replacements:

(a) In the `## Environment` section, replace:

```
API keys live in **`.env` in this directory** as `GEMINI_KEY_1` … `GEMINI_KEY_N`
(up to 10). `src/config.py` reads each via `_get_secret()` — which checks
`st.secrets` first (Streamlit Cloud) then `os.getenv` (local `.env`) — and builds
`MODEL_ARSENAL`, every key × model combination, for automatic failover.

Core dependencies (see `requirements.txt`): `streamlit`, `pandas`, `numpy`,
`altair`, `google-generativeai`, `python-dotenv`, `pyarrow`.
```

with:

```
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
```

(b) In the `### AI agent (\`src/agent/\`)` section, replace:

```
- **`caller.py`** — `call_agent(prompt)` iterates `MODEL_ARSENAL` via
  `model_idx % len(MODEL_ARSENAL)`, advances `model_idx` on quota/permission/not-found
  errors, and snapshots/rolls back `ui_history` on failure.
```

with:

```
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
```

(c) In the `## Conventions` section, replace:

```
- `MODEL_ARSENAL` entries are `{"key", "model", "label"}`; `model_idx` wraps with
  `% len(MODEL_ARSENAL)`.
```

with:

```
- `LLM_ARSENAL` entries are `{"provider", "key", "model", "label"}` (`MODEL_ARSENAL`
  is the Gemini-only subset); `model_idx` wraps with `% len(LLM_ARSENAL)`. Claude
  combos are eligible only for tool-less text calls.
```

- [ ] **Step 3: Run the full no-network test suite.** Each must print its passing summary:

```
..\venv\Scripts\python.exe tests/test_providers.py
..\venv\Scripts\python.exe tests/test_router.py
..\venv\Scripts\python.exe tests/test_scoring.py
..\venv\Scripts\python.exe tests/test_simulation.py
..\venv\Scripts\python.exe tests/test_memory.py
..\venv\Scripts\python.exe tests/test_proactive.py
..\venv\Scripts\python.exe tests/test_insights.py
..\venv\Scripts\python.exe tests/test_orchestrator.py
..\venv\Scripts\python.exe tests/test_reflexive.py
..\venv\Scripts\python.exe tests/test_deliverables.py
..\venv\Scripts\python.exe tests/test_persistence.py
```
Expected: all PASS.

- [ ] **Step 4: Boot the app headless and confirm HTTP 200** (PowerShell):

```powershell
$p = Start-Process -PassThru -NoNewWindow ..\venv\Scripts\python.exe `
  -ArgumentList "-m","streamlit","run","app.py","--server.headless","true","--server.port","8599"
Start-Sleep -Seconds 14
try { (Invoke-WebRequest http://localhost:8599 -UseBasicParsing).StatusCode } finally { Stop-Process -Id $p.Id -Force }
```
Expected: `200`. (If port 8599 is busy, pick another free port.)

- [ ] **Step 5: Commit:**

```bash
git add CLAUDE.md
git commit -m "Phase 5: journal + technical-guidance docs for provider abstraction"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- `ANTHROPIC_API_KEY`, `CLAUDE_MODELS`, `build_llm_arsenal`, `LLM_ARSENAL` (Gemini-first, Claude appended; Gemini-only when no key) → Task 1. ✓
- `gemini_generate_text` / `claude_generate_text` adapters (Claude prompt caching, lazy import) → Task 2. ✓
- `is_eligible` (tool calls Gemini-only) + `provider_text` dispatch → Task 2. ✓
- `generate()` rotates `LLM_ARSENAL`, tool-less adapter dispatch + failover, tool path unchanged & Gemini-only → Task 3. ✓
- `anthropic` dependency → Task 2. ✓
- UI combo counters use `LLM_ARSENAL` → Task 4. ✓
- Tests (arsenal build, eligibility, dispatch, simulated cross-provider failover) → Tasks 1–2. ✓
- Journal + full suite + HTTP 200 → Task 5. ✓

**Placeholder scan:** none — every code/test step is complete. ✓

**Type consistency:** combo dict `{"provider","key","model","label"}` consistent across `build_llm_arsenal`, `is_eligible`, `provider_text`, and `generate()`. Adapter signature `(prompt, *, system_instruction, key, model) -> str` identical in `providers.py`, the test stubs, and `provider_text`'s `gemini_fn`/`claude_fn` calls. `generate()` still returns `{"text","model_label","chat"}`. ✓

**Note (behavior delta):** the Gemini *tool-less text* path now uses `generate_content` (via the adapter) instead of `start_chat().send_message()`. Output is equivalent for a single tool-less prompt (callers read only `result["text"]`), and the tool-using path is byte-for-byte unchanged. The generic-exception behavior also differs by path on purpose: the tool path returns an error message (as today); the tool-less path rotates to enable Claude failover.
