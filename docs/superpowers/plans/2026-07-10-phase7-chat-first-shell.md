# Phase 7 — Chat-First Shell + Dispatch Ladder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make chat the app's landing page: every message flows through one ordered dispatch ladder, the 5 analytical tabs collapse into a single dataset-agnostic "Full numbers" panel, and the chrome is decluttered.

**Architecture:** A new Streamlit-free `dispatch()` ladder reuses the existing `route`/`call_agent`/`run_reflexive` for its two live rungs, with empty hooks for the Phase 8/9 rungs. A new `full_numbers.py` panel replaces the retired tab modules. `app.py` drops `st.tabs` and renders the chat as the whole page.

**Tech Stack:** Python, Streamlit, pandas, Altair. Tests are standalone scripts (no pytest, no network); `streamlit.testing.v1.AppTest` for wiring.

**Spec:** `docs/superpowers/specs/2026-07-10-phase7-chat-first-shell-design.md`

---

## File structure

- **Create `src/agent/dispatch.py`** — `DispatchResult` + `dispatch(...)`: the ordered ladder. Streamlit-free; injected `route_fn`/`agent_fn`/`reflexive_fn`/`recipe_fn`/`grounded_fn`.
- **Create `src/ui/full_numbers.py`** — `render_full_numbers()`: best-effort dataset-agnostic figures panel.
- **Rewrite `src/ui/tabs/chat.py`** — `render_chat` becomes the chat-first page body (dispatch, starter chips, briefing, Full-numbers expander, deliverables); drops the 3-metric row + button wall + examples.
- **Modify `app.py`** — drop `st.tabs` + the 5 tab render calls/imports; render chat as the page.
- **Modify `src/ui/sidebar.py`** — add a "🔌 Model status" section (moved from chat).
- **Modify `src/ui/tabs/__init__.py`** — drop the 5 tab imports, keep `chat`.
- **Delete** `src/ui/tabs/{overview,scoring,segments,happy_path,interventions}.py`.
- **Create** `tests/test_dispatch.py`, `tests/test_full_numbers.py`, `tests/test_chat_shell.py`.

**Reused as-is (do NOT modify):** `src/agent/router.route` (returns `{"mode","goal"}`), `src/agent/caller.call_agent`, `src/agent/orchestrator.run_reflexive`/`synthesize_goal`, `src/agent/proactive.get_briefing`, `src/analysis/metrics.calculate_churn_risk` (returns `(at_risk, at_risk_power)`), `src/analysis/segmentation.{compute_segment_gaps,build_comparison_data}`, `src/export/generator.generate_csv_export`, `src/agent/tool_loop.{user_text,assistant_text}`.

---

## Task 1: Dispatch ladder

**Files:**
- Create: `src/agent/dispatch.py`
- Test: `tests/test_dispatch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_dispatch.py`:

```python
"""Unit tests for the dispatch ladder (no Streamlit, no network)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.agent.dispatch import dispatch, DispatchResult

def _route_answer(msg, **k): return {"mode": "answer", "goal": ""}
def _route_goal(msg, **k): return {"mode": "goal", "goal": "do X"}

def test_answer_rung_fires_agent():
    res = dispatch("hi", route_fn=_route_answer, agent_fn=lambda p: "ANS",
                   reflexive_fn=lambda *a, **k: [])
    assert res.kind == "answer" and res.text == "ANS"

def test_goal_rung_runs_reflexive_and_reports_steps():
    seen = []
    def fake_reflexive(goal, status_callback=None):
        if status_callback: status_callback("reasoning", "action")
        return ["step1"]
    res = dispatch("hi", on_step=lambda r, l: seen.append((r, l)),
                   route_fn=_route_goal, agent_fn=lambda p: "NO",
                   reflexive_fn=fake_reflexive)
    assert res.kind == "goal" and res.goal == "do X" and res.history == ["step1"]
    assert seen == [("reasoning", "action")]

def test_recipe_rung_short_circuits_before_route():
    sentinel = DispatchResult(kind="answer", text="RECIPE")
    res = dispatch("hi", route_fn=_route_answer, agent_fn=lambda p: "ANS",
                   reflexive_fn=lambda *a, **k: [], recipe_fn=lambda p: sentinel)
    assert res is sentinel

def test_grounded_rung_reached_when_agent_returns_empty():
    sentinel = DispatchResult(kind="answer", text="GROUNDED")
    res = dispatch("hi", route_fn=_route_answer, agent_fn=lambda p: "",
                   reflexive_fn=lambda *a, **k: [], grounded_fn=lambda p: sentinel)
    assert res is sentinel

def test_empty_hooks_fall_through():
    # recipe/grounded default to None -> normal answer path
    res = dispatch("hi", route_fn=_route_answer, agent_fn=lambda p: "ANS",
                   reflexive_fn=lambda *a, **k: [])
    assert res.kind == "answer" and res.text == "ANS"

def test_rung_exception_is_caught():
    def boom(p): raise RuntimeError("kaboom")
    res = dispatch("hi", route_fn=_route_answer, agent_fn=boom,
                   reflexive_fn=lambda *a, **k: [])
    assert res.kind == "answer" and "⚠️" in res.text

if __name__ == "__main__":
    test_answer_rung_fires_agent()
    test_goal_rung_runs_reflexive_and_reports_steps()
    test_recipe_rung_short_circuits_before_route()
    test_grounded_rung_reached_when_agent_returns_empty()
    test_empty_hooks_fall_through()
    test_rung_exception_is_caught()
    print("test_dispatch: OK")
```

- [ ] **Step 2: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_dispatch.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.dispatch'`.

- [ ] **Step 3: Implement `src/agent/dispatch.py`**

```python
"""The dispatch ladder — one ordered decision structure for every chat message.

Rungs, tried in order, first match wins:
  1. saved recipe      (Phase 9 slot — `recipe_fn`, None today)
  2. known tool        (route -> "answer" -> call_agent)
  3. multi-step goal   (route -> "goal"   -> run_reflexive)
  4. grounded query    (Phase 8 slot — `grounded_fn`, reached only if the tool
                        path yields nothing; None today)

Streamlit-free: the goal rung's live progress is delivered via the injected
`on_step(reason, label)` callback (the same shape `run_reflexive`'s
status_callback uses), so this module is fully unit-testable with fakes. Any
exception in a rung is caught and returned as a relayable error answer — the
chat never crashes on a dispatch.
"""

from dataclasses import dataclass, field

from src.agent.router import route as _route
from src.agent.caller import call_agent as _call_agent
from src.agent.orchestrator import run_reflexive as _run_reflexive


@dataclass
class DispatchResult:
    kind: str                 # "answer" | "goal"
    text: str = ""            # answer text (kind == "answer")
    goal: str = ""            # resolved goal (kind == "goal")
    history: list = field(default_factory=list)  # reflexive history (kind == "goal")


def dispatch(prompt, *, on_step=None, route_fn=_route, agent_fn=_call_agent,
             reflexive_fn=_run_reflexive, recipe_fn=None, grounded_fn=None):
    """Route `prompt` down the ladder and return a DispatchResult."""
    try:
        # Rung 1 — saved recipe (Phase 9).
        if recipe_fn is not None:
            res = recipe_fn(prompt)
            if res is not None:
                return res

        # Rungs 2 & 3 — known tool (answer) vs multi-step goal.
        decision = route_fn(prompt)
        if decision.get("mode") == "goal":
            goal = decision.get("goal") or prompt
            history = reflexive_fn(goal, status_callback=on_step)
            return DispatchResult(kind="goal", goal=goal, history=history or [])

        # Rung 2 — known tool.
        text = agent_fn(prompt)
        if text:
            return DispatchResult(kind="answer", text=text)

        # Rung 4 — grounded query (Phase 8): only if the tool path said nothing.
        if grounded_fn is not None:
            res = grounded_fn(prompt)
            if res is not None:
                return res

        return DispatchResult(kind="answer", text=text or "")
    except Exception as e:  # never crash the chat on a dispatch failure
        return DispatchResult(kind="answer",
                              text=f"⚠️ I hit an error handling that: {e}")
```

- [ ] **Step 4: Run to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_dispatch.py`
Expected: `test_dispatch: OK`

- [ ] **Step 5: Commit**

```bash
git add src/agent/dispatch.py tests/test_dispatch.py
git commit -m "feat(phase7): dispatch ladder with two live rungs + Phase 8/9 slots"
```

---

## Task 2: Full numbers panel

**Files:**
- Create: `src/ui/full_numbers.py`
- Test: `tests/test_full_numbers.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_full_numbers.py`:

```python
"""Full-numbers panel tests via AppTest (no network)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from streamlit.testing.v1 import AppTest

_SCRIPT = (
    "import streamlit as st\n"
    "from src.ui.full_numbers import render_full_numbers\n"
    "render_full_numbers()\n"
)

def _scored():
    return pd.DataFrame({
        "user_id": [1, 2, 3, 4],
        "frequency": [10, 3, 8, 1],
        "monetary": [100.0, 20.0, 80.0, 5.0],
        "recency_days": [5, 60, 10, 90],
        "loyalty_score": [90.0, 30.0, 75.0, 10.0],
    })

def test_hint_shown_before_analysis():
    at = AppTest.from_string(_SCRIPT, default_timeout=30).run()
    assert not at.exception
    # No metrics rendered when there's no scored_df.
    assert len(at.metric) == 0

def test_panel_renders_after_analysis():
    scored = _scored()
    power = scored[scored["loyalty_score"] >= 70].copy()
    regular = scored[scored["loyalty_score"] < 70].copy()
    at = AppTest.from_string(_SCRIPT, default_timeout=30)
    at.session_state["scored_df"] = scored
    at.session_state["features"] = scored
    at.session_state["power"] = power
    at.session_state["regular"] = regular
    at.session_state["cutoff"] = 70.0
    at.session_state["power_user_ids"] = set(power["user_id"])
    at.run()
    assert not at.exception
    assert len(at.metric) >= 4  # customers / power / at-risk / avg score

if __name__ == "__main__":
    test_hint_shown_before_analysis()
    test_panel_renders_after_analysis()
    print("test_full_numbers: OK")
```

- [ ] **Step 2: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_full_numbers.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.ui.full_numbers'`.

- [ ] **Step 3: Implement `src/ui/full_numbers.py`**

```python
"""Full numbers panel — a lean, dataset-agnostic figures view.

Replaces the 5 retired analytical tabs with one panel that works identically on
the demo and on client uploads, because it reads the canonical feature matrix and
the lever-agnostic analysis helpers the agent tools already use. Best-effort: any
failure collapses to a one-line hint rather than crashing the chat-first page.
"""

import streamlit as st
import altair as alt

from src.analysis.metrics import calculate_churn_risk
from src.analysis.segmentation import compute_segment_gaps, build_comparison_data
from src.export.generator import generate_csv_export

_HINT = ("No analysis yet — ask the agent to \"score customers\", or use "
         "**Run Full Analysis** in the sidebar.")


def render_full_numbers():
    """Render the panel; never raise (collapses to a hint on any error)."""
    try:
        _render()
    except Exception:
        st.caption(_HINT)


def _render():
    scored = st.session_state.get("scored_df")
    if scored is None or len(scored) == 0:
        st.caption(_HINT)
        return

    features = st.session_state.get("features")
    power = st.session_state.get("power")
    regular = st.session_state.get("regular")
    cutoff = st.session_state.get("cutoff")
    power_ids = st.session_state.get("power_user_ids") or set()

    # --- key metrics ---
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Customers", f"{len(scored):,}")
    c2.metric("Power users",
              f"{len(power):,}" if power is not None else "—",
              help=(f"Score cutoff {cutoff:.1f}" if cutoff else None))
    at_risk_n = 0
    if features is not None:
        at_risk, _ = calculate_churn_risk(features, power_ids, 30)
        at_risk_n = len(at_risk)
    c3.metric("At-risk (30d)", f"{at_risk_n:,}")
    c4.metric("Avg loyalty score", f"{scored['loyalty_score'].mean():.1f}")

    # --- scored customers table + download ---
    st.divider()
    st.subheader("Scored customers")
    st.caption("Top 500 shown; download for the full list.")
    st.dataframe(
        scored.sort_values("loyalty_score", ascending=False).head(500),
        use_container_width=True, hide_index=True,
    )
    csv = generate_csv_export()
    if csv:
        st.download_button("⬇️ Download full scored CSV", data=csv,
                           file_name="scored_customers.csv", mime="text/csv")

    # --- power vs regular by active lever ---
    if power is not None and regular is not None:
        gaps = compute_segment_gaps(power, regular)
        if gaps:
            st.divider()
            st.subheader("Power vs regular — by lever")
            chart = (
                alt.Chart(build_comparison_data(gaps))
                .mark_bar(stroke="#00141F", strokeWidth=1.5)
                .encode(
                    x=alt.X("Feature:N", axis=alt.Axis(
                        labelAngle=-20, title="", labelColor="#FEF0D5",
                        domainColor="#FEF0D5")),
                    y=alt.Y("Value:Q", axis=alt.Axis(
                        labelColor="#FEF0D5", domainColor="#FEF0D5")),
                    xOffset="Segment:N",
                    color=alt.Color("Segment:N",
                        scale=alt.Scale(range=["#C1121F", "#FEF0D5"]),
                        legend=alt.Legend(labelColor="#FEF0D5",
                                          titleColor="#FEF0D5")),
                    tooltip=["Feature", "Segment", "Value"],
                )
                .properties(height=300)
                .configure_view(strokeWidth=0, fill="#0A3D5C")
            )
            st.altair_chart(chart, use_container_width=True)
```

- [ ] **Step 4: Run to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_full_numbers.py`
Expected: `test_full_numbers: OK`

- [ ] **Step 5: Commit**

```bash
git add src/ui/full_numbers.py tests/test_full_numbers.py
git commit -m "feat(phase7): dataset-agnostic Full numbers panel"
```

---

## Task 3: Sidebar "Model status" section

Move the API-status metrics out of the chat into the sidebar.

**Files:**
- Modify: `src/ui/sidebar.py`

- [ ] **Step 1: Read the current sidebar**

Open `src/ui/sidebar.py`. It already imports `API_KEYS, LLM_ARSENAL` and has an "🔑 API Status" section showing key count. You will ADD a compact metrics block there (active model / keys loaded / combos remaining) — the same three metrics the chat currently shows.

- [ ] **Step 2: Add the metrics block**

Inside `render_sidebar`, find the existing API status section (the `st.markdown("### 🔑 API Status")` block). Immediately AFTER the existing `st.success(f"✅ {len(API_KEYS)} key(s) loaded")` / caption lines within the `else:` branch, add:

```python
            idx = st.session_state.get("model_idx", 0) % len(LLM_ARSENAL)
            active = LLM_ARSENAL[idx]
            m1, m2 = st.columns(2)
            m1.metric("Model", active["model"].replace("gemini-", ""))
            used = min(st.session_state.get("model_idx", 0), len(LLM_ARSENAL))
            m2.metric("Combos left", f"{len(LLM_ARSENAL) - used}/{len(LLM_ARSENAL)}")
```

(Keys-loaded is already shown by the existing `st.success` line, so we show Model + Combos-left here rather than duplicating the key count.)

- [ ] **Step 3: Verify the app still boots**

Run: `..\venv\Scripts\python.exe -c "import ast; ast.parse(open('src/ui/sidebar.py',encoding='utf-8').read()); print('parse OK')"`
Expected: `parse OK`

Run: `..\venv\Scripts\python.exe tests/test_upload_flow.py`
Expected: `test_upload_flow: OK` (app boots through the sidebar with 0 exceptions).

- [ ] **Step 4: Commit**

```bash
git add src/ui/sidebar.py
git commit -m "feat(phase7): move model-status metrics into the sidebar"
```

---

## Task 4: Rewrite `chat.py` as the chat-first page body

Restructure `render_chat` to route through `dispatch`, show starter chips on an empty conversation, embed the Full-numbers expander, and drop the 3-metric row + button wall + examples. `chat.py` is still rendered as `tabs[5]` by `app.py` at this point (that's fine — Task 5 removes the tabs); this keeps the change independently bootable/testable.

**Files:**
- Rewrite: `src/ui/tabs/chat.py`
- Test: `tests/test_upload_flow.py` (reuse its AppTest boot; no new test here — the shell test is Task 5)

- [ ] **Step 1: Replace the entire contents of `src/ui/tabs/chat.py`**

```python
"""Chat page — the chat-first landing surface (Phase 7).

Every message flows through the dispatch ladder (`src/agent/dispatch.py`). The 5
analytical tabs are retired; their figures live in the collapsible "Full numbers"
expander below the conversation.
"""

import streamlit as st

from src.config import API_KEYS
from src.ui.renderer import render_message, download_key
from src.agent.caller import probe_health
from src.agent.tool_loop import user_text, assistant_text
from src.agent.dispatch import dispatch
from src.agent.orchestrator import synthesize_goal
from src.agent.proactive import get_briefing
from src.ui.full_numbers import render_full_numbers
from src.utils.persistence import save_session, clear_session

_STARTERS = [
    "Score all customers and identify power users",
    "Who is at risk of churning? Use a 30-day threshold.",
    "Compare power users vs regular users",
    "Find the happy path to power user status",
]


@st.cache_data(ttl=120, show_spinner=False)
def _api_health():
    return probe_health()


def _render_api_banner():
    """Upfront banner when the LLM is unreachable, before a message is wasted."""
    if not API_KEYS:
        return
    try:
        status = _api_health()
    except Exception:
        return
    if status == "exhausted":
        st.error(
            "⚠️ **All Gemini API keys are out of quota right now**, so the chat "
            "can't answer. Free-tier quota resets at midnight US Pacific — or add "
            "a fresh key (`GEMINI_KEY_5=…` in `.env`, then restart). "
            "Get one at https://aistudio.google.com/apikey"
        )


def render_chat(features, orders):
    _render_api_banner()
    if not API_KEYS:
        st.error("⚠️ No API keys configured. Add GEMINI_KEY_1=your_key to your "
                 ".env file, then restart the app.")

    render_briefing()

    if not st.session_state.ui_history:
        _seed_welcome(features, orders)

    for msg in st.session_state.ui_history:
        render_message(msg)

    # Starter chips only while the user hasn't spoken yet.
    no_user_msgs = not any(m.get("role") == "user" for m in st.session_state.ui_history)
    if no_user_msgs:
        st.caption("Try one of these:")
        cols = st.columns(len(_STARTERS))
        for i, (col, starter) in enumerate(zip(cols, _STARTERS)):
            if col.button(starter, key=f"starter_{i}", use_container_width=True):
                _submit(starter)

    if prompt := st.chat_input("Ask anything, or give a goal…"):
        _submit(prompt)

    with st.expander("📊 Full numbers", expanded=False):
        render_full_numbers()

    _deliverables_panel()

    _, nc_col = st.columns([3, 1])
    with nc_col:
        if st.button("🗑️ New conversation", use_container_width=True):
            clear_session()
            st.session_state["ui_history"] = []
            st.session_state["chat_history"] = []
            st.rerun()


def _submit(prompt: str):
    """Route one message through the dispatch ladder and render the result."""
    st.session_state.ui_history.append(
        {"role": "user", "type": "text", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    start = len(st.session_state.ui_history)
    with st.status("🧠 Working…", expanded=True) as status:
        def on_step(reason, label):
            if reason:
                st.markdown(f"🧠 _{reason}_")
            if label:
                st.write(f"▶️ **{label}**")
        result = dispatch(prompt, on_step=on_step)
        status.update(label="Done", state="complete", expanded=False)

    if result.kind == "goal":
        # Inline the tools' output produced during the loop (charts/tables/text).
        for msg in st.session_state.ui_history[start:]:
            if msg.get("type") != "artifact":
                render_message(msg)
        summary = synthesize_goal(result.goal, result.history)
        if summary:
            st.session_state.ui_history.append(
                {"role": "assistant", "type": "text", "content": summary})
            # Continuity: neutral-shape turns so follow-ups have context.
            st.session_state.chat_history.append(user_text(result.goal))
            st.session_state.chat_history.append(assistant_text(summary))
    else:
        st.session_state.ui_history.append(
            {"role": "assistant", "type": "text", "content": result.text})

    save_session()
    st.rerun()


def _seed_welcome(features, orders):
    total_users = features["user_id"].nunique()
    total_orders_count = len(orders)
    extra_line = ""
    if "category_diversity" in features.columns:
        extra_line = (f"- **{features['category_diversity'].max():.0f}** product "
                      f"categories for your most varied customer\n")
    elif "dept_diversity" in features.columns:
        extra_line = (f"- **{features['dept_diversity'].max():.0f}** unique "
                      f"departments\n")
    welcome = (
        f"👋 Hello! I'm your Customer Loyalty Intelligence Agent.\n\n"
        f"I'm connected to your customer dataset:\n"
        f"- **{total_users:,}** customers\n"
        f"- **{total_orders_count:,}** orders\n"
        f"{extra_line}\n"
        f"Ask me anything, or pick a starter below. I can score customers, "
        f"compare segments, find the happy path to loyalty, flag churn risk, "
        f"and draft campaigns — every number computed from your real data."
    )
    st.session_state.ui_history.append(
        {"role": "assistant", "type": "text", "content": welcome})


def render_briefing():
    """Proactive briefing panel: deterministic signal cards + grounded narration.
    Best-effort — any failure silently skips the panel."""
    try:
        briefing = get_briefing()
    except Exception:
        return
    if not briefing["ready"] or not briefing["signals"]:
        return
    with st.expander("💡 Today's Briefing", expanded=True):
        if briefing["narrative"]:
            st.markdown(briefing["narrative"])
            st.divider()
        signals = briefing["signals"]
        cols = st.columns(len(signals))
        for col, sig in zip(cols, signals):
            with col:
                st.markdown(f"#### {sig['icon']} {sig['headline']}")
                st.caption(sig["detail"])
                if st.button(sig["action_label"], key=f"briefing_{sig['id']}",
                             use_container_width=True):
                    _submit(sig["action_prompt"])


def _deliverables_panel():
    arts = st.session_state.get("artifacts", [])
    if not arts:
        return
    with st.expander("📦 Deliverables", expanded=False):
        st.caption("Every file the agent has produced this session.")
        for a in arts:
            st.download_button(label=a["label"], data=a["content"],
                               file_name=a["filename"], mime=a["mime"],
                               key=download_key())
```

- [ ] **Step 2: Parse + boot check**

Run: `..\venv\Scripts\python.exe -c "import ast; ast.parse(open('src/ui/tabs/chat.py',encoding='utf-8').read()); print('parse OK')"`
Expected: `parse OK`

Run: `..\venv\Scripts\python.exe tests/test_upload_flow.py`
Expected: `test_upload_flow: OK` (app still boots — chat tab now shows the new body with 0 exceptions).

- [ ] **Step 3: Commit**

```bash
git add src/ui/tabs/chat.py
git commit -m "feat(phase7): chat.py routes through dispatch; starter chips; Full numbers expander"
```

---

## Task 5: Retire the tabs — `app.py` single-page chat-first layout

Drop `st.tabs` and the 5 analytical tab modules; render the chat as the whole page.

**Files:**
- Modify: `app.py`
- Modify: `src/ui/tabs/__init__.py`
- Delete: `src/ui/tabs/overview.py`, `scoring.py`, `segments.py`, `happy_path.py`, `interventions.py`
- Test: `tests/test_chat_shell.py`

- [ ] **Step 1: Write the failing shell test**

Create `tests/test_chat_shell.py`:

```python
"""Chat-first shell boots with 0 exceptions and has no 6-tab dashboard."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from streamlit.testing.v1 import AppTest

def test_chat_first_shell_boots():
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception, f"app raised: {at.exception}"
    # Chat input is present (the landing surface).
    assert len(at.chat_input) >= 1
    # The old analytical dashboard is gone: at most 0 top-level tab groups
    # containing the retired tab labels.
    labels = [t.label for t in at.tabs]
    for gone in ("Overview", "Scoring", "Segments", "Happy Path", "Interventions"):
        assert gone not in labels, f"retired tab still present: {gone}"

if __name__ == "__main__":
    test_chat_first_shell_boots()
    print("test_chat_shell: OK")
```

- [ ] **Step 2: Run to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_chat_shell.py`
Expected: FAIL — the retired tab labels are still present (app still renders `st.tabs`).

- [ ] **Step 3: Trim `src/ui/tabs/__init__.py`**

Replace its entire contents with:

```python
from src.ui.tabs.chat import render_chat
```

- [ ] **Step 4: Edit `app.py`**

(a) Remove these 5 import lines:

```python
from src.ui.tabs.overview import render_overview
from src.ui.tabs.scoring import render_scoring
from src.ui.tabs.segments import render_segments
from src.ui.tabs.happy_path import render_happy_path
from src.ui.tabs.interventions import render_interventions
```

(Keep `from src.ui.tabs.chat import render_chat`.)

(b) Replace the tabs block inside the `if not render_confirm_gate(run_analysis):` branch — currently:

```python
    tabs = st.tabs(["📊 Overview", "⚖️ Scoring", "👥 Segments", "🗺️ Happy Path", "🎯 Interventions", "🤖 AI Chat"])
    with tabs[0]: render_overview(features, orders)
    with tabs[1]: render_scoring()
    with tabs[2]: render_segments()
    with tabs[3]: render_happy_path(full_data)
    with tabs[4]: render_interventions()
    with tabs[5]: render_chat(features, orders)
```

— with a single call:

```python
    render_chat(features, orders)
```

Leave the rest of that branch (`render_watch_alerts()`, `render_upload_notices()`, `maybe_show_onboarding(run_analysis)`) unchanged and ABOVE the `render_chat` call.

- [ ] **Step 5: Delete the 5 retired tab modules**

```bash
git rm src/ui/tabs/overview.py src/ui/tabs/scoring.py src/ui/tabs/segments.py src/ui/tabs/happy_path.py src/ui/tabs/interventions.py
```

- [ ] **Step 6: Confirm nothing else imports the deleted modules**

Run: `..\venv\Scripts\python.exe -c "import ast; ast.parse(open('app.py',encoding='utf-8').read()); print('parse OK')"`
Expected: `parse OK`

Search for stragglers — use the Grep tool (or ripgrep) for the pattern
`render_overview|render_scoring|render_segments|render_happy_path|render_interventions`
across `*.py` in the repo. Expect matches ONLY inside `docs/` (historical plan/spec
text). If any live `.py` still imports or calls them, fix that importer before
continuing.

- [ ] **Step 7: Run the shell test + boot**

Run: `..\venv\Scripts\python.exe tests/test_chat_shell.py`
Expected: `test_chat_shell: OK`

Run: `..\venv\Scripts\python.exe tests/test_upload_flow.py`
Expected: `test_upload_flow: OK`

- [ ] **Step 8: Commit**

```bash
git add app.py src/ui/tabs/__init__.py
git commit -m "feat(phase7): chat-first single-page shell; retire the 5 analytical tabs"
```

---

## Task 6: Regression sweep + journal

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Run the full no-network suite**

Run each and confirm each prints its OK line and exits 0:

```
..\venv\Scripts\python.exe tests/test_dispatch.py
..\venv\Scripts\python.exe tests/test_full_numbers.py
..\venv\Scripts\python.exe tests/test_chat_shell.py
..\venv\Scripts\python.exe tests/test_upload_flow.py
..\venv\Scripts\python.exe tests/test_dataset_swap.py
..\venv\Scripts\python.exe tests/test_tools_canonical.py
..\venv\Scripts\python.exe tests/test_canonical.py
..\venv\Scripts\python.exe tests/test_levers.py
..\venv\Scripts\python.exe tests/test_app_data.py
```

If any fails, STOP and report — do not paper over a regression.

- [ ] **Step 2: Manual smoke (recommended)**

```
..\venv\Scripts\python.exe -m streamlit run app.py
```
Confirm: chat is the landing page (no tab bar); a starter chip runs; "📊 Full numbers" expander shows metrics after an analysis; sidebar shows Model status.

- [ ] **Step 3: Add the journal entry**

Prepend a dated `### 2026-07-10 — Intelligence Layer / Chat-First, Phase 7: Chat-first shell + dispatch ladder` entry to the Project Journal in `CLAUDE.md`, matching the surrounding style: the new `dispatch()` ladder (2 live rungs + Phase 8/9 slots), `full_numbers.py` replacing the 5 retired tabs, `app.py` single-page chat-first layout, chrome declutter (model status → sidebar, starter chips), and the tests. Do NOT add a Co-Authored-By line.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs(phase7): journal entry for chat-first shell + dispatch ladder"
```

---

## Self-review notes

- **Spec coverage:** dispatch ladder (§3.1)→T1; Full numbers panel (§3.3)→T2; sidebar API status (§3.4)→T3; chat-first page + route→dispatch + chips + declutter (§3.2, Q4)→T4; single-page layout + retire 5 tabs (§3.2, Q2/Q3)→T5; testing (§6)→T1/T2/T5/T6; retirement + journal→T5/T6.
- **Type consistency:** `dispatch(...)` signature + `DispatchResult(kind/text/goal/history)` defined in T1 and used verbatim in T4. `route` returns `{"mode","goal"}` (matches real code). `calculate_churn_risk` returns `(at_risk, at_risk_power)` — T2 uses `at_risk, _ = ...`. `compute_segment_gaps(power, regular)` + `build_comparison_data(gaps)` used per real signatures.
- **Ordering:** T4 rewrites chat.py while it's still `tabs[5]` (bootable); T5 flips app.py to single-page and deletes tabs. Both independently green.
- **No placeholders:** every code step is complete.
