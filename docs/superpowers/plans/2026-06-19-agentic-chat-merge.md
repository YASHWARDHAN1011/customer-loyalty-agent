# Agentic Chat (Chat ⊃ Autopilot) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the AI Chat a real agent — it auto-detects whether a message is a quick question or a multi-step goal, and for goals it runs the reflexive loop inline with live reasoning, while the separate Autopilot tab is removed.

**Architecture:** A new pure `router.route()` classifies each chat message (answer vs goal) via one small LLM call. The chat dispatches `answer` to the existing reactive `call_agent`, and `goal` to the existing `orchestrator.run_reflexive` loop rendered live, then `synthesize_goal`. The Autopilot tab is deleted; its engine is reused and its deliverables panel moves into chat.

**Tech Stack:** Python, Streamlit (UI layer), Gemini, standalone test scripts (not pytest). No new dependencies.

---

## Conventions (read once)

- **Tests are standalone scripts**, not pytest. Each defines `check(name, cond)` that prints `PASS`/`FAIL` and `sys.exit(1)` on failure (copy the harness shown in Task 1).
- **Run tests** from the inner project dir (`customer-loyalty-agent/customer-loyalty-agent/`): `..\venv\Scripts\python.exe tests/test_router.py`
- **Keep `src/agent/router.py` Streamlit-free** (pure logic + one injected LLM call). `chat.py`/`app.py` use Streamlit and need the runtime, so they are syntax-checked + the app booted (HTTP 200) rather than unit-tested — same approach the repo uses for `tools.py`.
- **NO "Co-Authored-By: Claude" trailer** on any commit (repo convention).
- **The `generate` stub signature** used everywhere (router, tests): `generate(prompt, *, system_instruction, tools=None, history=None, automatic_function_calling=False)` returning a dict `{"text", "model_label", "chat"}`.
- **Tolerant JSON parse** pattern (from `orchestrator._parse_decision`): strip ``` / ```json fences, try `json.loads`, then fall back to a `{...}` regex.

---

## File Structure

- **Create** `src/agent/router.py` — `route(message, generate_fn=generate)`; pure, testable.
- **Modify** `src/config.py` — add `ROUTER_SYSTEM`.
- **Create** `tests/test_router.py` — router behavior + default-to-answer safety.
- **Modify** `src/ui/tabs/chat.py` — route each free-form message; goal path runs the loop inline + continuity + deliverables panel.
- **Modify** `app.py` — remove the Autopilot tab (import, tab label, render call).
- **Delete** `src/ui/tabs/autopilot.py` — behavior now lives in chat.
- **Modify** `CLAUDE.md` — dated Project Journal entry.

---

## Task 1: The router + ROUTER_SYSTEM

A pure classifier that decides answer-vs-goal, defaulting to `answer` on any failure.

**Files:**
- Create: `src/agent/router.py`
- Modify: `src/config.py`
- Test: `tests/test_router.py`

- [ ] **Step 1: Write the failing test** — create `tests/test_router.py`:

```python
"""Standalone tests for src/agent/router.py. No network, no Streamlit."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent.router import route

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def _gen(text):
    """generate-compatible stub returning a fixed text."""
    def g(prompt, *, system_instruction, tools=None, history=None,
          automatic_function_calling=False):
        return {"text": text, "model_label": "stub", "chat": None}
    return g


def _boom(prompt, *, system_instruction, tools=None, history=None,
          automatic_function_calling=False):
    raise RuntimeError("model down")


def main():
    # ROUTER_SYSTEM exists and is a non-trivial prompt
    from src.config import ROUTER_SYSTEM
    check("ROUTER_SYSTEM is non-empty str",
          isinstance(ROUTER_SYSTEM, str) and len(ROUTER_SYSTEM) > 50)

    # goal classification -> mode goal + goal text
    g = route("build a retention strategy",
              generate_fn=_gen('{"mode":"goal","goal":"build a retention strategy"}'))
    check("goal -> mode goal", g["mode"] == "goal")
    check("goal -> goal text", g["goal"] == "build a retention strategy")

    # goal wrapped in ``` fences still parses
    gf = route("x", generate_fn=_gen('```json\n{"mode":"goal","goal":"do it"}\n```'))
    check("fenced goal parses", gf["mode"] == "goal" and gf["goal"] == "do it")

    # answer classification -> mode answer, empty goal
    a = route("what does reorder rate mean?",
              generate_fn=_gen('{"mode":"answer","goal":""}'))
    check("answer -> mode answer", a["mode"] == "answer")
    check("answer -> empty goal", a["goal"] == "")

    # goal text falls back to the original message when omitted
    gm = route("the original message", generate_fn=_gen('{"mode":"goal"}'))
    check("goal falls back to message", gm["goal"] == "the original message")

    # default to answer on exception / empty / garbage
    check("exception -> answer", route("m", generate_fn=_boom)["mode"] == "answer")
    check("empty text -> answer", route("m", generate_fn=_gen(""))["mode"] == "answer")
    check("garbage -> answer",
          route("m", generate_fn=_gen("not json at all"))["mode"] == "answer")

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run, confirm it FAILS** (no module yet):

Run: `..\venv\Scripts\python.exe tests/test_router.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.router'`.

- [ ] **Step 3: Add `ROUTER_SYSTEM` to `src/config.py`.** Immediately after the `MEMORY_SYSTEM = """ ... """` block, add:

```python
ROUTER_SYSTEM = """
You are a router for a customer-loyalty analytics agent. Classify the user's
message into exactly one mode:

- "answer": a question, a request to explain a concept, a single lookup, or a
  single analysis/action. Examples: "who are our power users?", "what does
  reorder rate mean?", "show me user 1", "score the customers",
  "how many are at churn risk?".
- "goal": a multi-step objective that needs several analyses and/or deliverables
  chained together. Examples: "build a retention strategy for at-risk power
  users", "find and target my churners and draft win-back emails", "score
  customers and prepare a full campaign plan".

Respond with ONLY a JSON object and nothing else:
{"mode": "answer" | "goal", "goal": "<the goal text if mode is goal, else empty>"}

When unsure, prefer "answer".
"""
```

- [ ] **Step 4: Create `src/agent/router.py`:**

```python
"""
Message router — decides whether a chat message is a quick question (answer) or a
multi-step objective (goal).

Pure aside from one injected LLM classification call. This is a JUDGMENT call, not
a business number, so it does not touch the grounding contract — the reactive
answer path and the reflexive goal loop both stay grounded as before. Any failure
defaults to "answer": cheaper and safer than wrongly launching an autonomous run.
"""

import json
import re

from src.config import ROUTER_SYSTEM
from src.agent.caller import generate


def _parse(text):
    """Parse the router's single JSON object, or None if unusable."""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except (ValueError, TypeError):
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError):
            pass
    return None


def route(message, generate_fn=generate):
    """Classify `message`. Returns {"mode": "answer"|"goal", "goal": str}.

    `goal` is the goal text when mode is "goal" (falling back to the original
    message if the model omits it), else "". Defaults to answer-mode on any
    failure, empty, or unparseable output.
    """
    try:
        raw = generate_fn(message, system_instruction=ROUTER_SYSTEM)
        data = _parse(raw.get("text", ""))
    except Exception:
        data = None

    if data and data.get("mode") == "goal":
        return {"mode": "goal", "goal": data.get("goal") or message}
    return {"mode": "answer", "goal": ""}
```

- [ ] **Step 5: Run, confirm ALL checks PASS:**

Run: `..\venv\Scripts\python.exe tests/test_router.py`
Expected: PASS — "10 checks passed."

- [ ] **Step 6: Commit:**

```bash
git add src/agent/router.py src/config.py tests/test_router.py
git commit -m "Agentic chat: add answer/goal message router + ROUTER_SYSTEM"
```

---

## Task 2: Wire routing + inline goal-runs into the chat

The chat dispatches free-form messages: `answer` → `call_agent`; `goal` → the reflexive loop rendered live, then a summary that stays in context. Adds the deliverables panel moved from the Autopilot tab.

**Files:**
- Modify: `src/ui/tabs/chat.py`

- [ ] **Step 1: Update the imports** at the top of `src/ui/tabs/chat.py`. Replace this block:

```python
import streamlit as st
from src.config import API_KEYS, MODEL_ARSENAL
from src.ui.renderer import render_message
from src.agent.caller import call_agent
from src.agent.proactive import get_briefing
from src.utils.persistence import save_session, clear_session
```

with:

```python
import streamlit as st
from src.config import API_KEYS, MODEL_ARSENAL
from src.ui.renderer import render_message, download_key
from src.agent.caller import call_agent
from src.agent.router import route
from src.agent.orchestrator import run_reflexive, synthesize_goal
from src.agent.proactive import get_briefing
from src.utils.persistence import save_session, clear_session
```

- [ ] **Step 2: Replace the `st.chat_input` handler** in `render_chat`. Replace this block:

```python
    if prompt := st.chat_input(
        "Ask about your customers... "
        "(e.g. 'Who are our power users?')"
    ):
        st.session_state.ui_history.append({
            "role": "user",
            "type": "text",
            "content": prompt
        })

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.spinner("🧠 Agent thinking..."):
            response = call_agent(prompt)

        st.session_state.ui_history.append({
            "role": "assistant",
            "type": "text",
            "content": response
        })

        save_session()
        st.rerun()
```

with:

```python
    if prompt := st.chat_input(
        "Ask anything, or give a goal... "
        "(e.g. 'Who are our power users?' or 'Build a retention plan')"
    ):
        st.session_state.ui_history.append({
            "role": "user",
            "type": "text",
            "content": prompt
        })

        with st.chat_message("user"):
            st.markdown(prompt)

        decision = route(prompt)
        if decision["mode"] == "goal":
            _run_goal_in_chat(decision["goal"] or prompt)
        else:
            with st.spinner("🧠 Agent thinking..."):
                response = call_agent(prompt)
            st.session_state.ui_history.append({
                "role": "assistant",
                "type": "text",
                "content": response
            })

        save_session()
        st.rerun()
```

- [ ] **Step 3: Add the deliverables panel call.** In `render_chat`, immediately after the `render_briefing()` line, add a call so deliverables show once any exist:

Find:
```python
    render_briefing()
```
Replace with:
```python
    render_briefing()

    _deliverables_panel()
```

- [ ] **Step 4: Add the two helper functions** at the END of `src/ui/tabs/chat.py` (after `_handle_quick_action`):

```python
def _run_goal_in_chat(goal: str):
    """Run the reflexive loop for a goal, live in the chat, then summarize.

    Mirrors the old Autopilot tab: shows 🧠 reason / ▶️ action per step, renders
    the tools' inline output, posts an executive summary into the conversation,
    and injects a synthetic turn into chat_history so follow-ups have context.
    """
    start = len(st.session_state.ui_history)

    with st.status("Thinking…", expanded=True) as status:
        def _on_step(reason, label):
            if reason:
                st.markdown(f"🧠 _{reason}_")
            if label:
                st.write(f"▶️ **{label}**")

        history = run_reflexive(goal, status_callback=_on_step)
        status.update(label="Goal complete", state="complete", expanded=False)

    # Inline analysis output produced by the tools (charts/tables/text only;
    # artifacts live in the deliverables panel).
    for msg in st.session_state.ui_history[start:]:
        if msg.get("type") != "artifact":
            render_message(msg)

    summary = synthesize_goal(goal, history)
    if summary:
        st.session_state.ui_history.append({
            "role": "assistant", "type": "text", "content": summary,
        })
        # Continuity: let later reactive follow-ups see what the agent did.
        st.session_state.chat_history.append({"role": "user", "parts": [goal]})
        st.session_state.chat_history.append({"role": "model", "parts": [summary]})


def _deliverables_panel():
    """List every artifact produced this session (moved from the Autopilot tab)."""
    arts = st.session_state.get('artifacts', [])
    if not arts:
        return
    with st.expander("📦 Deliverables", expanded=False):
        st.caption("Every file the agent has produced this session.")
        for a in arts:
            st.download_button(
                label=a['label'],
                data=a['content'],
                file_name=a['filename'],
                mime=a['mime'],
                key=download_key(),
            )
```

- [ ] **Step 5: Verify the module parses and is wired:**

Run: `..\venv\Scripts\python.exe -c "import ast; src=open('src/ui/tabs/chat.py',encoding='utf-8').read(); ast.parse(src); print('chat.py parses'); print('route', 'route(prompt)' in src); print('goalrun', 'def _run_goal_in_chat' in src); print('deliverables', 'def _deliverables_panel' in src and '_deliverables_panel()' in src)"`
Expected: `chat.py parses`, `route True`, `goalrun True`, `deliverables True`.

- [ ] **Step 6: Commit:**

```bash
git add src/ui/tabs/chat.py
git commit -m "Agentic chat: route messages, run goals inline, add deliverables panel"
```

---

## Task 3: Remove the Autopilot tab

The chat is now the single agent surface. Delete the tab UI; keep the engine.

**Files:**
- Modify: `app.py`
- Delete: `src/ui/tabs/autopilot.py`

- [ ] **Step 1: Remove the import.** In `app.py`, delete this line:

```python
from src.ui.tabs.autopilot import render_autopilot
```

- [ ] **Step 2: Remove the tab label.** In `app.py`, change:

```python
tabs = st.tabs(["📊 Overview", "⚖️ Scoring", "👥 Segments", "🗺️ Happy Path", "🎯 Interventions", "🤖 AI Chat", "🚀 Autopilot"])
```
to:
```python
tabs = st.tabs(["📊 Overview", "⚖️ Scoring", "👥 Segments", "🗺️ Happy Path", "🎯 Interventions", "🤖 AI Chat"])
```

- [ ] **Step 3: Remove the render call.** In `app.py`, delete this line:

```python
with tabs[6]: render_autopilot(features, orders)
```

- [ ] **Step 4: Delete the tab module:**

```bash
git rm src/ui/tabs/autopilot.py
```

- [ ] **Step 5: Verify nothing else references the removed tab:**

Run: `..\venv\Scripts\python.exe -c "import ast; ast.parse(open('app.py',encoding='utf-8').read()); print('app.py parses')"`
Expected: `app.py parses`.

Run: `..\venv\Scripts\python.exe -c "import os; hits=[]; [hits.append(f) for r,_,fs in os.walk('src') for f in fs if f.endswith('.py') and ('render_autopilot' in open(os.path.join(r,f),encoding='utf-8').read() or 'tabs.autopilot' in open(os.path.join(r,f),encoding='utf-8').read())]; print('stray refs', hits); print('app refs', 'autopilot' in open('app.py',encoding='utf-8').read())"`
Expected: `stray refs []`, `app refs False`.

- [ ] **Step 6: Commit:**

```bash
git add app.py
git commit -m "Agentic chat: remove the standalone Autopilot tab (engine reused by chat)"
```

---

## Task 4: Journal entry + full verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the Project Journal entry.** At the TOP of the `## 📓 Project Journal` section in `CLAUDE.md` (above the 2026-06-19 What-If entry), add:

```markdown
### 2026-06-19 — Agentic Chat (chat absorbs Autopilot)
Made the AI Chat a real agent and retired the separate Autopilot tab.
- **`src/agent/router.py`** (NEW, pure): `route(message)` classifies each message
  as a quick `answer` or a multi-step `goal` via one small LLM call under
  `ROUTER_SYSTEM`; defaults to `answer` on any failure (safe + cheap).
- **`src/config.py`**: added `ROUTER_SYSTEM`.
- **`src/ui/tabs/chat.py`**: free-form messages are routed — `answer` → the
  existing reactive `call_agent`; `goal` → the reflexive loop
  (`run_reflexive`) run inline with live 🧠 reason / ▶️ action, then
  `synthesize_goal`; the summary lands in the conversation and a synthetic
  `{user,goal}/{model,summary}` pair is pushed into `chat_history` so follow-ups
  have context. The consolidated "📦 Deliverables" panel moved here from the
  Autopilot tab.
- **`app.py`**: dropped from 7 tabs to 6 — the Autopilot tab is removed.
- **Deleted `src/ui/tabs/autopilot.py`** — its engine (`orchestrator`) is reused
  by the chat unchanged.
- Grounding unchanged: routing is a judgment call (no business numbers); the loop
  and tools stay grounded.
- Tests: `tests/test_router.py` (classification + default-to-answer). No network.
  Full suite green; app boots headless HTTP 200. Quick-action buttons still call
  `call_agent` directly (deliberate single actions, no routing).
- Gemini-only; provider abstraction is still a later phase.
```

- [ ] **Step 2: Run the full no-network test suite.** Each must print its passing summary:

```
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

- [ ] **Step 3: Boot the app headless and confirm HTTP 200** (PowerShell):

```powershell
$p = Start-Process -PassThru -NoNewWindow ..\venv\Scripts\python.exe `
  -ArgumentList "-m","streamlit","run","app.py","--server.headless","true","--server.port","8599"
Start-Sleep -Seconds 14
try { (Invoke-WebRequest http://localhost:8599 -UseBasicParsing).StatusCode } finally { Stop-Process -Id $p.Id -Force }
```
Expected: `200`. (If port 8599 is busy, pick another free port.)

- [ ] **Step 4: Commit:**

```bash
git add CLAUDE.md
git commit -m "Agentic chat: journal entry for chat/Autopilot merge"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Auto-detect LLM router (`route`, defaults to answer) + `ROUTER_SYSTEM` → Task 1. ✓
- Chat routes answer→`call_agent`, goal→`run_reflexive` live + `synthesize_goal` → Task 2. ✓
- Live steps (🧠/▶️) then summary in conversation → Task 2 (`_run_goal_in_chat`). ✓
- Continuity via synthetic `chat_history` turns → Task 2. ✓
- Deliverables panel moved into chat → Task 2 (`_deliverables_panel`). ✓
- Remove Autopilot tab + delete `autopilot.py` (engine kept) → Task 3. ✓
- Router tests + full suite + HTTP 200 + journal → Tasks 1 & 4. ✓

**Placeholder scan:** none — every code/test step is complete. ✓

**Type consistency:** `route()` returns `{"mode", "goal"}`; chat reads `decision["mode"]`/`decision["goal"]`. `run_reflexive(goal, status_callback=...)` and `synthesize_goal(goal, history)` signatures match `orchestrator.py`. `download_key`/`render_message` imported from `src.ui.renderer` (as the old Autopilot tab did). Synthetic `chat_history` entries use the `{role, parts:[text]}` shape the persistence layer round-trips. ✓

**Note:** Quick-action and briefing buttons keep calling `call_agent` directly (they are deliberate single actions) — only free-form `st.chat_input` messages are routed, which avoids spending a router call on canned buttons.
