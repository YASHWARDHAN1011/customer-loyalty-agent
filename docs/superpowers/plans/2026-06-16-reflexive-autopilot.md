# Reflexive Autopilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the open-loop Autopilot with a closed-loop "Grounded ReAct" controller that runs one analysis step, reads the real numbers it produced, decides the next step (or stops), and shows its reasoning live.

**Architecture:** Evolve `src/agent/orchestrator.py` — add a pure history-digest helper, a single-decision LLM call (`decide_next_step`) constrained by the existing `TOOL_REGISTRY`, and a closed loop (`run_reflexive`) with deterministic guardrails (scoring-first, max 6 steps, no-repeat, parse-fallback to `DEFAULT_PLAN`). The Autopilot tab is rewired to drive the loop and render the live reasoning. The existing `plan_goal`/`execute_plan` functions and their tests stay in place (used as the fallback's source of truth via `DEFAULT_PLAN`); they're just no longer the primary path.

**Tech Stack:** Python, Streamlit, Google Generative AI (Gemini). Tests are standalone scripts (not pytest) that `sys.path.insert` the repo root and `sys.exit(1)` on failure, run with the outer venv: `..\venv\Scripts\python.exe tests/<file>.py`.

---

## File Structure

- **Modify** `src/config.py` — add `REFLEXIVE_SYSTEM` prompt constant.
- **Modify** `src/agent/orchestrator.py` — add `_digest_history`, `_parse_decision`, `decide_next_step`, `_execute_one`, `_run_fallback_remainder`, `run_reflexive`, and the module constants `MAX_STEPS` / `SCORING_DEPENDENT`. Leave existing functions untouched.
- **Modify** `src/ui/tabs/autopilot.py` — replace `_run_goal` internals to call `run_reflexive` with a two-line (reasoning + action) live status log; drop the `plan_goal`/`execute_plan` import.
- **Create** `tests/test_reflexive.py` — standalone test script for the new pure helpers and the loop (no network).

The existing `tests/test_orchestrator.py` stays and must keep passing.

---

## Task 1: REFLEXIVE_SYSTEM prompt

**Files:**
- Modify: `src/config.py` (append a new constant near `PROACTIVE_SYSTEM`)

- [ ] **Step 1: Locate the anchor**

Open `src/config.py` and find the `PROACTIVE_SYSTEM = (` constant (added in Phase 1). The new constant goes immediately after it.

- [ ] **Step 2: Add the constant**

Insert this after the `PROACTIVE_SYSTEM` definition:

```python
REFLEXIVE_SYSTEM = (
    "You are the controller for a customer-loyalty analytics agent. You work "
    "one step at a time: given the business goal, the catalog of tools, and the "
    "numeric results of the steps already run, you choose the SINGLE next tool "
    "to run — or you declare the goal complete.\n\n"
    "Respond with ONLY a JSON object, no prose, in one of two forms:\n"
    '  {"tool": <tool name>, "args": {<args>}, "label": <short human phrase>, '
    '"reason": <one sentence>}\n'
    '  {"done": true, "reason": <one sentence>}\n\n'
    "Rules:\n"
    "- Choose tools ONLY from the provided catalog.\n"
    "- Your `reason` MUST cite the actual numbers shown under 'Results so far'. "
    "NEVER state a number that is not shown there.\n"
    "- Do not repeat a step that already ran with the same arguments.\n"
    "- Stop (done) as soon as the goal is satisfied; prefer 2-5 steps total.\n"
    "- Adapt: if a result shows an issue is minor, do not pursue it — pursue "
    "whatever the numbers say matters most for the goal."
)
```

- [ ] **Step 3: Verify it imports**

Run: `..\venv\Scripts\python.exe -c "from src.config import REFLEXIVE_SYSTEM; print(len(REFLEXIVE_SYSTEM))"`
Expected: prints an integer > 0 (no ImportError). (A `google.generativeai` FutureWarning is pre-existing and harmless.)

- [ ] **Step 4: Commit**

```bash
git add src/config.py
git commit -m "Add REFLEXIVE_SYSTEM controller prompt"
```

---

## Task 2: Pure helpers + the decision call

This task adds `_digest_history`, `_parse_decision`, and `decide_next_step` to `orchestrator.py`, plus the test file covering them. We write the tests first.

**Files:**
- Create: `tests/test_reflexive.py`
- Modify: `src/agent/orchestrator.py`

- [ ] **Step 1: Write the failing test file**

Create `tests/test_reflexive.py` with exactly this content (it covers Task 2 and Task 3; the Task 3 checks will fail to import until Task 3 is done, so for now run only the functions that exist — Step 2 explains how):

```python
"""Standalone tests for the Reflexive Autopilot loop.

No network: `generate` is replaced with scripted stubs; the tool functions in
TOOL_REGISTRY are replaced with no-op stubs that just echo their kwargs.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import src.agent.orchestrator as orch

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def _scripted_generate(texts):
    """generate-compatible callable that returns each text in order, then a
    'done' object once the script is exhausted."""
    seq = list(texts)
    def _g(prompt, *, system_instruction, tools=None, history=None,
           automatic_function_calling=False):
        t = seq.pop(0) if seq else '{"done": true, "reason": "exhausted"}'
        return {"text": t, "model_label": "stub", "chat": None}
    return _g


def _always_new_generate():
    """Never says done; returns a distinct valid step every call (varying args)
    so the no-repeat guard never trips and only the step cap can stop the loop."""
    n = {"i": 0}
    def _g(prompt, **kw):
        n["i"] += 1
        txt = ('{"tool":"analyze_churn_risk","args":{"churn_days":%d},'
               '"label":"churn","reason":"r"}' % (30 + n["i"]))
        return {"text": txt, "model_label": "stub", "chat": None}
    return _g


def _install_stub_tools():
    """Replace every TOOL_REGISTRY func with a no-op echo stub."""
    def _stub(**kw):
        return {"status": "success", "echo": kw}
    for name in list(orch.TOOL_REGISTRY):
        orch.TOOL_REGISTRY[name] = {**orch.TOOL_REGISTRY[name], "func": _stub}


def main():
    # ---------- _digest_history ----------
    check("digest empty", orch._digest_history([]) == "(no steps run yet)")

    sample = [{
        "label": "Score all customers", "tool": "run_scoring_analysis",
        "args": {}, "reason": "first",
        "result": {"status": "success", "total_users": 206209,
                   "power_user_count": 20626, "power_user_percentage": 10.0,
                   "instruction": "ignore me",
                   "top_differentiators": [{"Feature": "x"}]},
    }]
    dig = orch._digest_history(sample)
    check("digest includes a real number", "power_user_count=20626" in dig)
    check("digest skips instruction", "ignore me" not in dig)
    check("digest skips non-scalar", "top_differentiators" not in dig)

    # ---------- _parse_decision ----------
    obj = '{"tool":"analyze_churn_risk","args":{"churn_days":30},"label":"c","reason":"r"}'
    check("parse clean object", orch._parse_decision(obj) is not None)
    fenced = "```json\n" + obj + "\n```"
    check("parse fenced object", orch._parse_decision(fenced) is not None)
    check("parse garbage -> None", orch._parse_decision("sorry, no") is None)

    # ---------- decide_next_step ----------
    good = ('{"tool":"analyze_churn_risk","args":{"churn_days":60,"bogus":1},'
            '"label":"Churn","reason":"because"}')
    d = orch.decide_next_step("goal", [], generate_fn=_scripted_generate([good]))
    check("decide returns tool", d["tool"] == "analyze_churn_risk")
    check("decide strips unknown arg", "bogus" not in d["args"])
    check("decide keeps valid arg", d["args"]["churn_days"] == 60)

    done = orch.decide_next_step(
        "goal", [], generate_fn=_scripted_generate(['{"done": true, "reason": "ok"}']))
    check("decide recognizes done", done.get("done") is True)

    unknown = orch.decide_next_step(
        "goal", [], generate_fn=_scripted_generate(['{"tool":"nope","args":{}}']))
    check("decide rejects unknown tool", unknown is None)

    garbage = orch.decide_next_step(
        "goal", [], generate_fn=_scripted_generate(["totally not json"]))
    check("decide on garbage -> None", garbage is None)

    # ---------- run_reflexive ----------
    _install_stub_tools()

    # scoring is always forced first, then the scripted step, then done
    hist = orch.run_reflexive(
        "goal",
        generate_fn=_scripted_generate(
            ['{"tool":"analyze_churn_risk","args":{"churn_days":30},'
             '"label":"churn","reason":"r"}',
             '{"done": true, "reason": "enough"}']),
    )
    tools = [h["tool"] for h in hist]
    check("scoring forced first", tools[0] == "run_scoring_analysis")
    check("ran the chosen step", tools == ["run_scoring_analysis", "analyze_churn_risk"])
    check("each step carries a reason", all("reason" in h for h in hist))
    check("each step carries a result", all("result" in h for h in hist))

    # step cap (MAX_STEPS) stops an otherwise-endless loop
    capped = orch.run_reflexive("goal", generate_fn=_always_new_generate())
    check("respects step cap", len(capped) == orch.MAX_STEPS)

    # no-repeat: identical (tool,args) twice -> loop stops after the first
    rep = '{"tool":"analyze_churn_risk","args":{"churn_days":30},"label":"c","reason":"r"}'
    norepeat = orch.run_reflexive("goal", generate_fn=_scripted_generate([rep, rep]))
    check("no-repeat stops progress",
          [h["tool"] for h in norepeat] == ["run_scoring_analysis", "analyze_churn_risk"])

    # parse-fallback: two bad decisions in a row -> run DEFAULT_PLAN remainder
    fb = orch.run_reflexive("goal", generate_fn=_scripted_generate(["junk", "junk"]))
    fb_tools = [h["tool"] for h in fb]
    check("fallback runs default-plan remainder", "build_action_plan" in fb_tools)

    # status_callback receives (reason, label)
    seen = []
    orch.run_reflexive(
        "goal",
        status_callback=lambda reason, label: seen.append((reason, label)),
        generate_fn=_scripted_generate(['{"done": true, "reason": "x"}']),
    )
    check("status_callback got reason+label",
          len(seen) == 1 and seen[0][1] == "Score all customers")

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_reflexive.py`
Expected: FAIL — `AttributeError: module 'src.agent.orchestrator' has no attribute '_digest_history'` (the first `check` line that calls a missing function).

- [ ] **Step 3: Implement the pure helpers + decision call**

In `src/agent/orchestrator.py`, add the import for the new prompt at the top alongside the existing imports:

```python
from src.config import REFLEXIVE_SYSTEM
```

Then add these functions (place them after `synthesize_goal`, at the end of the existing code):

```python
# ── Reflexive (closed-loop) controller ──────────────────────────────────────

_DIGEST_SKIP_KEYS = {"instruction", "status"}


def _digest_history(history):
    """Flatten executed steps into grounded text for the controller.

    Pure: echoes only the scalar fields already present in each tool's result
    dict (skipping prompt-control keys and any nested/non-scalar values). No
    computation, no LLM — this is the ONLY place the controller may read numbers.
    """
    if not history:
        return "(no steps run yet)"
    lines = []
    for i, step in enumerate(history, 1):
        result = step.get("result") or {}
        parts = []
        for k, v in result.items():
            if k in _DIGEST_SKIP_KEYS or not isinstance(v, (str, int, float, bool)):
                continue
            parts.append(f"{k}={v}")
        detail = ", ".join(parts) if parts else "(no scalar output)"
        label = step.get("label") or step.get("tool")
        lines.append(f"Step {i} — {label}: {detail}")
    return "\n".join(lines)


def _parse_decision(text):
    """Parse the controller's single JSON object, or None if unusable."""
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


def decide_next_step(goal, history, generate_fn=generate):
    """One controller call: choose the next tool (grounded) or signal done.

    Returns {"done": True, "reason": ...}, or
    {"tool", "args", "label", "reason"}, or None if the output was unusable
    (unparseable, unknown tool).
    """
    prompt = (
        f"Goal: {goal}\n\n"
        f"Available tools:\n{_tool_catalog()}\n\n"
        f"Results so far:\n{_digest_history(history)}\n\n"
        "Decide the next step now."
    )
    raw = generate_fn(prompt, system_instruction=REFLEXIVE_SYSTEM)
    data = _parse_decision(raw.get("text", ""))
    if data is None:
        return None
    if data.get("done") is True:
        return {"done": True, "reason": data.get("reason", "")}
    name = data.get("tool")
    if name not in TOOL_REGISTRY:
        return None
    raw_args = data.get("args") or {}
    if not isinstance(raw_args, dict):
        raw_args = {}
    allowed = TOOL_REGISTRY[name]["args"].keys()
    args = {k: v for k, v in raw_args.items() if k in allowed}
    return {
        "tool": name,
        "args": args,
        "label": data.get("label", name),
        "reason": data.get("reason", ""),
    }
```

- [ ] **Step 4: Run the test again**

Run: `..\venv\Scripts\python.exe tests/test_reflexive.py`
Expected: still FAIL, but now further along — `AttributeError: ... has no attribute 'run_reflexive'` (or `MAX_STEPS`). The `_digest_history`, `_parse_decision`, and `decide_next_step` checks above should all print `PASS` before it fails. This confirms Task 2's code is correct.

- [ ] **Step 5: Commit**

```bash
git add src/agent/orchestrator.py tests/test_reflexive.py
git commit -m "Add grounded decision helpers for reflexive autopilot"
```

---

## Task 3: The closed loop

Adds `run_reflexive` and its helpers, completing `tests/test_reflexive.py`.

**Files:**
- Modify: `src/agent/orchestrator.py`

- [ ] **Step 1: The test already exists**

The `run_reflexive` checks are already in `tests/test_reflexive.py` (written in Task 2). Running now still fails on the missing `run_reflexive`/`MAX_STEPS` — that is the failing test for this task.

- [ ] **Step 2: Confirm it fails on the loop**

Run: `..\venv\Scripts\python.exe tests/test_reflexive.py`
Expected: PASS lines through the `decide_*` checks, then FAIL with `AttributeError: ... 'run_reflexive'` (or `MAX_STEPS`).

- [ ] **Step 3: Implement the loop**

Append to `src/agent/orchestrator.py` (after `decide_next_step`):

```python
MAX_STEPS = 6

# Tools that require run_scoring_analysis to have run first.
SCORING_DEPENDENT = {
    "run_segmentation", "run_happy_path", "run_interventions",
    "draft_campaign_emails", "build_action_plan",
}

_SCORING_STEP = {
    "tool": "run_scoring_analysis",
    "args": {},
    "label": "Score all customers",
    "reason": "Scoring underpins every other analysis, so run it first.",
}


def _execute_one(step):
    """Run a single validated step's tool; never raise (record errors)."""
    meta = TOOL_REGISTRY.get(step["tool"])
    if meta is None:
        return {"error": "unknown tool"}
    try:
        return meta["func"](**step["args"])
    except Exception as e:  # best-effort: record and continue
        return {"error": f"step failed: {e}"}


def _run_step(step, history, executed, status_callback):
    """Execute one step, report it, and record it in history/executed."""
    if status_callback:
        status_callback(step.get("reason", ""), step["label"])
    result = _execute_one(step)
    executed.add(step["tool"])
    history.append({**step, "result": result})


def _run_fallback_remainder(history, executed, status_callback):
    """A flaky controller: run the unrun steps of DEFAULT_PLAN and finish."""
    for s in DEFAULT_PLAN:
        if s["tool"] in executed:
            continue
        step = {
            "tool": s["tool"], "args": dict(s["args"]), "label": s["label"],
            "reason": "Falling back to the standard plan.",
        }
        _run_step(step, history, executed, status_callback)


def run_reflexive(goal, status_callback=None, generate_fn=generate):
    """Closed-loop driver. Runs one step at a time, deciding the next from the
    real results so far, with deterministic guardrails. Returns the list of
    executed step dicts: [{label, tool, args, reason, result}, ...].

    `status_callback(reason, label)` (optional) is called just before each step
    executes, so the UI can show the agent thinking then acting.
    """
    history = []
    executed = set()       # tool names that have run
    seen = set()           # (tool, frozenset(args)) — blocks exact repeats
    fails = 0              # consecutive unusable decisions

    while len(history) < MAX_STEPS:
        # Scoring-first: force scoring before anything else.
        if "run_scoring_analysis" not in executed:
            step = dict(_SCORING_STEP)
        else:
            decision = decide_next_step(goal, history, generate_fn=generate_fn)
            if decision is None:
                fails += 1
                if fails >= 2:
                    _run_fallback_remainder(history, executed, status_callback)
                    break
                continue
            fails = 0
            if decision.get("done"):
                break
            # Defensive scoring-first guard (scoring has already run here).
            if (decision["tool"] in SCORING_DEPENDENT
                    and "run_scoring_analysis" not in executed):
                decision = dict(_SCORING_STEP)
            step = decision

        key = (step["tool"], frozenset(step["args"].items()))
        if key in seen:           # no forward progress -> stop
            break
        seen.add(key)
        _run_step(step, history, executed, status_callback)

    return history
```

- [ ] **Step 4: Run the full reflexive test**

Run: `..\venv\Scripts\python.exe tests/test_reflexive.py`
Expected: all checks PASS, ending with a line like `21 checks passed.`

- [ ] **Step 5: Confirm the existing orchestrator test still passes**

Run: `..\venv\Scripts\python.exe tests/test_orchestrator.py`
Expected: all checks PASS (we added code but changed nothing existing).

- [ ] **Step 6: Commit**

```bash
git add src/agent/orchestrator.py
git commit -m "Add reflexive closed loop with guardrails"
```

---

## Task 4: Wire the Autopilot tab to the loop

**Files:**
- Modify: `src/ui/tabs/autopilot.py`

- [ ] **Step 1: Update the import**

In `src/ui/tabs/autopilot.py`, replace this line:

```python
from src.agent.orchestrator import plan_goal, execute_plan, synthesize_goal
```

with:

```python
from src.agent.orchestrator import run_reflexive, synthesize_goal
```

- [ ] **Step 2: Update the caption**

Replace the `st.caption(...)` call inside `render_autopilot` with:

```python
    st.caption(
        "Give the agent a goal. It runs one analysis step, reads the numbers, "
        "and decides the next move live — adapting as it learns — then hands you "
        "downloadable deliverables."
    )
```

- [ ] **Step 3: Replace `_run_goal`**

Replace the entire `_run_goal` function with this closed-loop version that shows reasoning then action per step:

```python
def _run_goal(goal: str):
    start = len(st.session_state.ui_history)

    # Closed loop — show the agent think (reason) then act (label) per step.
    with st.status("Thinking…", expanded=True) as status:
        def _on_step(reason, label):
            if reason:
                st.markdown(f"🧠 _{reason}_")
            st.write(f"▶️ **{label}**")

        history = run_reflexive(goal, status_callback=_on_step)
        status.update(label="Goal complete", state="complete", expanded=False)

    # Inline analysis output produced by the tools (charts/tables/text only;
    # artifacts are shown in the deliverables panel below).
    for msg in st.session_state.ui_history[start:]:
        if msg.get("type") != "artifact":
            render_message(msg)

    # Executive summary over what actually ran.
    summary = synthesize_goal(goal, history)
    if summary:
        st.markdown("### 📋 Executive summary")
        st.markdown(summary)
```

- [ ] **Step 4: Verify the module imports cleanly**

Run: `..\venv\Scripts\python.exe -c "import src.ui.tabs.autopilot as a; print(hasattr(a, 'render_autopilot'))"`
Expected: prints `True` (a `google.generativeai` FutureWarning is harmless/pre-existing).

- [ ] **Step 5: Commit**

```bash
git add src/ui/tabs/autopilot.py
git commit -m "Wire Autopilot tab to the reflexive loop"
```

---

## Task 5: Full verification + journal

**Files:**
- Modify: `CLAUDE.md` (add a dated journal entry at the top of the Project Journal)

- [ ] **Step 1: Run every no-network test suite**

Run each and confirm all pass (each exits non-zero on failure):

```
..\venv\Scripts\python.exe tests/test_reflexive.py
..\venv\Scripts\python.exe tests/test_orchestrator.py
..\venv\Scripts\python.exe tests/test_deliverables.py
..\venv\Scripts\python.exe tests/test_insights.py
..\venv\Scripts\python.exe tests/test_proactive.py
..\venv\Scripts\python.exe tests/test_persistence.py
..\venv\Scripts\python.exe tests/test_artifacts.py
```
Expected: each prints its `N checks passed.` (or `ALL PASSED`) line and exits 0.

- [ ] **Step 2: Boot the app headless**

Run (background, then poll):

```powershell
..\venv\Scripts\python.exe -m streamlit run app.py --server.port=8501 --server.headless=true
```
Poll `http://localhost:8501` until it returns HTTP 200 (use a retry loop; do not rely on a fixed sleep — the bind races). Then stop the process.
Expected: HTTP 200.

- [ ] **Step 3: Add the journal entry**

At the top of the `## 📓 Project Journal` section in `CLAUDE.md`, add:

```markdown
### 2026-06-16 — Proactive Analyst, Phase 2: Reflexive Autopilot
Turned the Autopilot from open-loop (plan everything upfront, execute blindly)
into a closed "Grounded ReAct" loop. It now runs one step, reads the real numbers
that step produced, and decides the next move — adapting, digging deeper, or
stopping early — with its reasoning shown live.
- **`src/agent/orchestrator.py`**: added `run_reflexive(goal, status_callback,
  generate_fn)` — the loop — plus `decide_next_step` (one grounded Gemini call
  returning a single JSON decision or `done`), `_digest_history` (pure: flattens
  prior steps' scalar result fields — the ONLY numbers the controller may cite),
  `_parse_decision`, and guardrails: scoring forced first, `MAX_STEPS=6`,
  no-repeat of an identical (tool,args), and a parse-fallback to the unrun
  remainder of `DEFAULT_PLAN` after two unusable decisions. The old
  `plan_goal`/`execute_plan` stay (still tested) but are no longer the primary
  path.
- **`src/config.py`**: added `REFLEXIVE_SYSTEM` — choose only catalog tools,
  cite only digest numbers, never invent, stop when the goal is met.
- **`src/ui/tabs/autopilot.py`**: the run now shows 🧠 reasoning then ▶️ action
  per step in the live `st.status` log; summary and deliverables unchanged.
- Tests: `tests/test_reflexive.py` (no network) covers the digest, the decision
  parser, `decide_next_step`, and the loop (scoring-first, step cap, no-repeat,
  parse-fallback, status callback). All existing suites still pass; app boots
  headless HTTP 200.
- Provider stays Gemini-only; provider abstraction is still Phase 5.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "Phase 2: Reflexive Autopilot — journal entry"
```

- [ ] **Step 5: Browser check (human)**

The live reasoning UI wants a human glance: open the Autopilot tab, run a goal (e.g. "Build a full retention strategy for at-risk power users"), and confirm each step shows a 🧠 reason then ▶️ action, the inline charts/tables render, the executive summary appears, and deliverables are downloadable.

---

## Notes for the implementer

- **Run all commands from the inner repo dir** `customer-loyalty-agent/customer-loyalty-agent`; the venv is in the **outer** dir (`..\venv`).
- Tests are **standalone scripts**, not pytest. Follow the `check()` + `sys.exit(1)` pattern already in `tests/test_orchestrator.py`.
- `generate()` returns a **dict** `{"text","model_label","chat"}` — always read `result["text"]`.
- **Do not** add a `Co-Authored-By: Claude` trailer to commits (project rule).
- The `google.generativeai` FutureWarning on import is pre-existing and harmless.
