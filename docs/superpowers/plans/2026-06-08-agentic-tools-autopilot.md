# Agentic Tools + Autopilot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add three downloadable-deliverable tools (target-list CSV, campaign-email drafts, action-plan checklist) and a plan→execute→synthesize Autopilot tab that drives all the agent's tools toward a user-stated goal.

**Architecture:** A pure `deliverables.py` builds file content; thin wrappers in `tools.py` store artifacts in `st.session_state.artifacts` and append `type="artifact"` chat entries. A new `orchestrator.py` exposes `plan_goal` (one Gemini call → JSON plan, with a parse fallback ladder), `execute_plan` (calls tool functions directly from a shared `TOOL_REGISTRY`), and `synthesize_goal` (final Gemini summary). A reusable `generate()` extracted from `caller.py` gives both chat and orchestrator the same key×model failover. A new `tabs/autopilot.py` surfaces the flow with a visible plan + `st.status` step log + a deliverables panel.

**Tech Stack:** Python, Streamlit 1.57, pandas, `google-generativeai` (Gemini function calling). Tests are standalone scripts (not pytest) that print PASS/FAIL and `sys.exit(1)` on failure — matching the existing `tests/` convention.

---

## File Structure

**New files:**
- `src/agent/deliverables.py` — pure (no Streamlit): builds target-list DataFrame/CSV, campaign-email markdown, action-plan markdown. Independently testable.
- `src/agent/orchestrator.py` — `TOOL_REGISTRY`, `plan_goal`, `execute_plan`, `synthesize_goal`, plan parsing/validation. Depends on `tools.py` + `caller.generate`.
- `src/ui/tabs/autopilot.py` — the 7th tab UI.
- `tests/test_deliverables.py` — pure-function tests (TDD, written first).
- `tests/test_orchestrator.py` — plan-parser + executor tests with stubs (no network).

**Modified files:**
- `src/agent/caller.py` — extract `generate(...)`; `call_agent` becomes a thin wrapper.
- `src/agent/tools.py` — add `_add_artifact`, three tool wrappers, extend `ALL_TOOLS`.
- `src/ui/renderer.py` — add `download_key()` helper + `type=="artifact"` branch in `render_message`.
- `app.py` — init `artifacts`/`_dl_counter` session state; register the 7th tab.
- `CLAUDE.md` — journal entry (final task).

---

## Task 1: Artifact session state + renderer download branch

**Files:**
- Modify: `src/ui/renderer.py` (add helper + artifact branch in `render_message`, ~line 184)
- Modify: `app.py:60-68` (add `artifacts` default)

- [ ] **Step 1: Add `download_key()` helper to renderer**

In `src/ui/renderer.py`, immediately above `def render_message(msg: dict):` (line 184), add:

```python
def download_key() -> str:
    """Monotonic unique key for st.download_button.

    st.tabs renders every tab body on each run, so the same artifact can be
    drawn in more than one place in a single pass. A monotonic counter
    guarantees a unique key per button within any single render.
    """
    st.session_state['_dl_counter'] = st.session_state.get('_dl_counter', 0) + 1
    return f"dl_{st.session_state['_dl_counter']}"
```

- [ ] **Step 2: Add the artifact branch to `render_message`**

In `src/ui/renderer.py`, inside `render_message`, after the `elif msg["type"] == "chart":` block ends (after line 236, still inside the `with st.chat_message(...)` block), add:

```python
        elif msg["type"] == "artifact":
            st.download_button(
                label=msg.get("label", "⬇️ Download"),
                data=msg["content"],
                file_name=msg["filename"],
                mime=msg["mime"],
                key=download_key(),
            )
```

- [ ] **Step 3: Initialize `artifacts` in app.py defaults**

In `app.py`, in the `defaults` dict (lines 60-66), add `'artifacts': [],` — e.g. change the `'active_model': ...` line to be preceded by:

```python
    'artifacts': [],
    'active_model': MODEL_ARSENAL[0]['label'] if MODEL_ARSENAL else 'None'
```

- [ ] **Step 4: Smoke-check the app still imports**

Run: `..\venv\Scripts\python.exe -c "import ast; ast.parse(open('src/ui/renderer.py',encoding='utf-8').read()); ast.parse(open('app.py',encoding='utf-8').read()); print('OK')"`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add src/ui/renderer.py app.py
git commit -m "feat: artifact download rendering + session state"
```

---

## Task 2: Pure deliverables module (TDD — tests first)

**Files:**
- Test: `tests/test_deliverables.py`
- Create: `src/agent/deliverables.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_deliverables.py`:

```python
"""Standalone tests for src/agent/deliverables.py (pure functions)."""
import sys
import pandas as pd

from src.agent.deliverables import (
    select_target_users, to_csv_bytes,
    campaign_emails_markdown, action_plan_markdown,
)
from src.analysis.interventions import INTERVENTION_TEMPLATES

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def _fixtures():
    features = pd.DataFrame({
        'user_id':               [1, 2, 3, 4],
        'total_orders':          [30, 5, 20, 2],
        'avg_days_between_orders':[10, 45, 12, 60],
        'reorder_rate':          [0.8, 0.2, 0.7, 0.1],
        'dept_diversity':        [15, 4, 12, 3],
        'avg_basket_size':       [12.0, 4.0, 10.0, 3.0],
        'total_items':           [360, 20, 200, 6],
    })
    scored = pd.DataFrame({'user_id': [1, 2, 3, 4],
                           'loyalty_score': [90.0, 30.0, 75.0, 15.0]})
    power   = features[features['user_id'].isin([1, 3])]
    regular = features[features['user_id'].isin([2, 4])]
    power_ids = {1, 3}
    return features, scored, power, regular, power_ids


def main():
    features, scored, power, regular, power_ids = _fixtures()

    # select_target_users: power segment returns only power users
    tgt = select_target_users(features, scored, power_ids, segment='power')
    check("target power-only", set(tgt['user_id']) == {1, 3})
    check("target has loyalty_score col", 'loyalty_score' in tgt.columns)
    check("target has segment col", 'segment' in tgt.columns)

    # min_orders filter
    tgt2 = select_target_users(features, scored, power_ids, min_orders=20)
    check("target min_orders filter", set(tgt2['user_id']) == {1, 3})

    # churn_days filter (avg_days_between_orders >= churn_days)
    tgt3 = select_target_users(features, scored, power_ids, churn_days=40)
    check("target churn filter", set(tgt3['user_id']) == {2, 4})

    # limit
    tgt4 = select_target_users(features, scored, power_ids, limit=1)
    check("target limit", len(tgt4) == 1)

    # CSV bytes round-trip
    raw = to_csv_bytes(tgt)
    check("csv is bytes", isinstance(raw, (bytes, bytearray)))
    check("csv has header", b'user_id' in raw)

    # campaign emails contain real numbers + subject markers
    from src.analysis.interventions import compute_intervention_gaps
    gaps = compute_intervention_gaps(power, regular)
    emails = campaign_emails_markdown(gaps, INTERVENTION_TEMPLATES)
    check("emails non-empty", len(emails) > 50)
    check("emails have Subject", "Subject:" in emails)

    # action plan dated + has checklist items
    plan = action_plan_markdown(gaps, INTERVENTION_TEMPLATES,
                                at_risk_count=2, at_risk_power=1,
                                date_str="2026-06-08")
    check("plan has date", "2026-06-08" in plan)
    check("plan has checkbox", "- [ ]" in plan)

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_deliverables.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.deliverables'`

- [ ] **Step 3: Write the implementation**

Create `src/agent/deliverables.py`:

```python
"""
Deliverables — pure builders for downloadable campaign artifacts.

No Streamlit imports: every function takes plain DataFrames / dicts so it can
be unit-tested in isolation. The tool wrappers in tools.py read session_state
and call these.
"""

import pandas as pd

_TARGET_COLS = [
    'user_id', 'total_orders', 'reorder_rate',
    'dept_diversity', 'avg_basket_size', 'segment',
]


def select_target_users(features, scored_df, power_user_ids,
                        segment=None, min_orders=None,
                        churn_days=None, limit=500):
    """Filter the feature matrix into a target list DataFrame.

    Mirrors the filter logic used by search_users / churn analysis so the
    exported list matches what the user sees in the app.
    """
    df = features.copy()
    if scored_df is not None:
        df = df.merge(
            scored_df[['user_id', 'loyalty_score']], on='user_id', how='left'
        )
    if min_orders is not None:
        df = df[df['total_orders'] >= min_orders]
    if churn_days is not None and 'avg_days_between_orders' in df.columns:
        df = df[df['avg_days_between_orders'] >= churn_days]
    if segment is not None:
        s = str(segment).lower()
        if 'power' in s:
            df = df[df['user_id'].isin(power_user_ids)]
        elif 'regular' in s:
            df = df[~df['user_id'].isin(power_user_ids)]

    df = df.copy()
    df['segment'] = df['user_id'].apply(
        lambda u: 'Power User' if u in power_user_ids else 'Regular User'
    )
    cols = list(_TARGET_COLS)
    if 'loyalty_score' in df.columns:
        cols.insert(-1, 'loyalty_score')
    return df[cols].head(int(limit)).round(3).reset_index(drop=True)


def to_csv_bytes(df) -> bytes:
    """Serialize a DataFrame to UTF-8 CSV bytes for st.download_button."""
    return df.to_csv(index=False).encode('utf-8')


def campaign_emails_markdown(gaps, templates, max_campaigns=4) -> str:
    """Build a markdown file of ready-to-send email drafts.

    gaps: list of (gap_pct, col, ru_avg, pu_avg) from compute_intervention_gaps.
    Deterministic: numbers are interpolated from the data, no LLM call.
    """
    out = "# Campaign Email Drafts\n\n"
    shown = 0
    for gap_pct, col, ru_avg, pu_avg in gaps:
        if shown >= max_campaigns or col not in templates:
            continue
        t = templates[col]
        out += f"## {t['title']}  ({gap_pct:.0f}% gap)\n\n"
        out += f"**Subject:** {t['title']} — a little something for you\n\n"
        out += (
            "Hi there,\n\n"
            f"We noticed an opportunity to help you get more from every order. "
            f"Our most loyal shoppers average {pu_avg:.2f} here, versus "
            f"{ru_avg:.2f} for most customers. "
            f"Here's an idea: {t['action']}.\n\n"
            f"_{t['message']}_\n\n"
            "Warmly,\nThe Team\n\n---\n\n"
        )
        shown += 1
    if shown == 0:
        out += "_No campaigns available — run scoring + segmentation first._\n"
    return out


def action_plan_markdown(gaps, templates, at_risk_count,
                         at_risk_power, date_str, max_items=5) -> str:
    """Build a dated, prioritized retention action checklist (markdown)."""
    out = f"# Retention Action Plan — {date_str}\n\n"
    out += (
        f"**Churn snapshot:** {at_risk_count:,} customers at risk "
        f"({at_risk_power:,} of them power users).\n\n"
        "## Prioritized actions\n\n"
    )
    shown = 0
    for gap_pct, col, ru_avg, pu_avg in gaps:
        if shown >= max_items or col not in templates:
            continue
        t = templates[col]
        out += (
            f"- [ ] **{t['title']}** — close the {gap_pct:.0f}% gap. "
            f"{t['action']} "
            f"(regulars avg {ru_avg:.2f} vs power {pu_avg:.2f}).\n"
        )
        shown += 1
    if shown == 0:
        out += "- [ ] Run scoring + segmentation to populate recommendations.\n"
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_deliverables.py`
Expected: all `PASS`, ends with `11 checks passed.`

- [ ] **Step 5: Commit**

```bash
git add src/agent/deliverables.py tests/test_deliverables.py
git commit -m "feat: pure deliverables builders + tests"
```

---

## Task 3: Deliverable tool wrappers in tools.py

**Files:**
- Modify: `src/agent/tools.py` (imports near line 26-31; new functions before `ALL_TOOLS`; extend `ALL_TOOLS` at line 580)

- [ ] **Step 1: Add imports**

In `src/agent/tools.py`, below the existing analysis imports (after line 30, `from src.analysis.interventions import ...`), add:

```python
import uuid
from datetime import date
from src.agent.deliverables import (
    select_target_users, to_csv_bytes,
    campaign_emails_markdown, action_plan_markdown,
)
```

(`compute_intervention_gaps` and `INTERVENTION_TEMPLATES` are already imported at line 29; `calculate_churn_risk` at line 30.)

- [ ] **Step 2: Add the artifact helper + three tools**

In `src/agent/tools.py`, immediately before the `# All tools Gemini can call` comment (line 579), add:

```python
def _add_artifact(filename: str, mime: str, content, label: str) -> str:
    """Store a downloadable artifact in session_state and append a chat entry."""
    art_id = uuid.uuid4().hex[:8]
    art = {
        "id": art_id, "filename": filename,
        "mime": mime, "content": content, "label": label,
    }
    st.session_state.setdefault('artifacts', []).append(art)
    st.session_state.ui_history.append({
        "role": "assistant", "type": "artifact",
        "filename": filename, "mime": mime,
        "content": content, "label": label, "artifact_id": art_id,
    })
    return art_id


def export_target_list(
    segment: str = None,
    min_orders: int = None,
    churn_days: int = None,
    limit: int = 500,
) -> dict:
    """
    Exports a downloadable CSV of the exact customers to target for a campaign.

    Use this when the user wants a list/export/file of users to contact, a
    target list for a campaign, or to "pull the users" matching a segment or
    churn threshold.

    Args:
        segment: 'power' or 'regular' to restrict the list.
        min_orders: only include users with at least this many orders.
        churn_days: only include users whose avg days between orders >= this.
        limit: max rows in the CSV (default 500).
    """
    features = st.session_state.get('features')
    if features is None:
        return {"error": "Data not loaded yet."}

    scored = st.session_state.get('scored_df')
    power_ids = st.session_state.get('power_user_ids', set())

    target = select_target_users(
        features, scored, power_ids,
        segment=segment, min_orders=min_orders,
        churn_days=churn_days, limit=limit,
    )
    if target.empty:
        return {
            "status": "no_results",
            "instruction": "Tell the user no customers matched their criteria.",
        }

    _add_artifact(
        "target_list.csv", "text/csv", to_csv_bytes(target),
        f"🎯 Target list — {len(target):,} users",
    )
    return {
        "status": "success",
        "target_count": int(len(target)),
        "filename": "target_list.csv",
        "instruction": (
            "Tell the user their target-list CSV is ready to download and "
            "how many customers it contains."
        ),
    }


def draft_campaign_emails(segment: str = None) -> dict:
    """
    Writes downloadable campaign email drafts, personalized to the biggest
    behavioral gaps between power users and regular users.

    Use this when the user asks to draft/write emails, create campaign copy,
    or generate outreach messages.

    Args:
        segment: optional label noted in the brief (e.g. 'regular', 'power').
    """
    power = st.session_state.get('power')
    regular = st.session_state.get('regular')
    if power is None:
        return {
            "error": "Run scoring analysis first.",
            "instruction": "Tell the user to run scoring before drafting emails.",
        }

    gaps = compute_intervention_gaps(power, regular)
    md = campaign_emails_markdown(gaps, INTERVENTION_TEMPLATES)
    _add_artifact("campaign_emails.md", "text/markdown", md,
                  "✉️ Campaign email drafts")
    return {
        "status": "success",
        "filename": "campaign_emails.md",
        "instruction": (
            "Tell the user the email drafts are ready to download and name "
            "the top campaign they cover."
        ),
    }


def build_action_plan(churn_days: int = 30) -> dict:
    """
    Compiles a downloadable, prioritized retention action checklist combining
    the biggest behavioral gaps with the current churn-risk snapshot.

    Use this when the user wants a plan, a checklist, a to-do list, next steps,
    or "what should we do" as a deliverable.

    Args:
        churn_days: days-without-order threshold for the churn snapshot.
    """
    power = st.session_state.get('power')
    regular = st.session_state.get('regular')
    features = st.session_state.get('features')
    if power is None or features is None:
        return {
            "error": "Run scoring analysis first.",
            "instruction": "Tell the user to run scoring before the action plan.",
        }

    gaps = compute_intervention_gaps(power, regular)
    power_ids = st.session_state.get('power_user_ids', set())
    at_risk, at_risk_power = calculate_churn_risk(features, power_ids, churn_days)

    md = action_plan_markdown(
        gaps, INTERVENTION_TEMPLATES,
        at_risk_count=len(at_risk), at_risk_power=len(at_risk_power),
        date_str=date.today().isoformat(),
    )
    _add_artifact("action_plan.md", "text/markdown", md,
                  "✅ Retention action plan")
    return {
        "status": "success",
        "filename": "action_plan.md",
        "at_risk": int(len(at_risk)),
        "instruction": (
            "Tell the user the action plan is ready to download and summarize "
            "its single highest-priority item."
        ),
    }
```

- [ ] **Step 3: Extend `ALL_TOOLS`**

In `src/agent/tools.py`, replace the `ALL_TOOLS` list (lines 580-589) with:

```python
ALL_TOOLS = [
    run_scoring_analysis,
    run_segmentation,
    run_happy_path,
    run_interventions,
    analyze_churn_risk,
    get_user_profile,
    search_users,
    get_current_stats,
    export_target_list,
    draft_campaign_emails,
    build_action_plan,
]
```

- [ ] **Step 4: Verify import + tool count**

Run: `..\venv\Scripts\python.exe -c "from src.agent.tools import ALL_TOOLS; print(len(ALL_TOOLS), [f.__name__ for f in ALL_TOOLS])"`
Expected: `11` and the list includes `export_target_list`, `draft_campaign_emails`, `build_action_plan`.

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools.py
git commit -m "feat: deliverable tools (target list, emails, action plan)"
```

---

## Task 4: Extract reusable `generate()` in caller.py

**Files:**
- Modify: `src/agent/caller.py` (rewrite the whole file)

- [ ] **Step 1: Rewrite caller.py with `generate()` + thin `call_agent()`**

Replace the entire contents of `src/agent/caller.py` with:

```python
"""
Agent Caller

`generate()` owns the key×model failover (shared by chat and the autopilot
orchestrator). `call_agent()` is the chat-specific wrapper that keeps the
Gemini conversation history and automatic function calling.
"""

import streamlit as st
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from src.config import MODEL_ARSENAL, API_KEYS, MODELS, SYSTEM_PROMPT
from src.agent.tools import ALL_TOOLS


def generate(
    prompt: str,
    *,
    system_instruction: str,
    tools=None,
    history=None,
    automatic_function_calling: bool = False,
) -> dict:
    """Send one message to Gemini, rotating through MODEL_ARSENAL on failure.

    Returns {"text", "model_label", "chat"} on success (chat may be None for
    the all-exhausted / no-keys messages). Advances st.session_state.model_idx
    and rolls back ui_history on each failed attempt, exactly as the old
    call_agent did.
    """
    if not MODEL_ARSENAL:
        return {
            "text": (
                "⚠️ No API keys configured. "
                "Please add GEMINI_KEY_1 to your .env file."
            ),
            "model_label": None,
            "chat": None,
        }

    ui_snapshot = len(st.session_state.ui_history)

    for _ in range(len(MODEL_ARSENAL)):
        idx = st.session_state.model_idx % len(MODEL_ARSENAL)
        config = MODEL_ARSENAL[idx]
        try:
            genai.configure(api_key=config['key'])
            model = genai.GenerativeModel(
                model_name=config['model'],
                tools=tools,
                system_instruction=system_instruction,
            )
            chat = model.start_chat(
                history=history or [],
                enable_automatic_function_calling=automatic_function_calling,
            )
            response = chat.send_message(prompt)
            st.session_state['active_model'] = config['label']
            return {
                "text": response.text,
                "model_label": config['label'],
                "chat": chat,
            }

        except google_exceptions.ResourceExhausted:
            st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
            st.session_state.model_idx += 1
            continue
        except google_exceptions.NotFound:
            st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
            st.session_state.model_idx += 1
            continue
        except google_exceptions.InvalidArgument as e:
            err = str(e)
            if "ToolType" in err or "function" in err.lower():
                st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
                st.session_state.model_idx += 1
                continue
            return {"text": f"⚠️ Invalid request: {err}", "model_label": None, "chat": None}
        except google_exceptions.PermissionDenied:
            st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
            st.session_state.model_idx += 1
            continue
        except Exception as e:
            return {"text": f"⚠️ Unexpected error: {str(e)}", "model_label": None, "chat": None}

    total_keys = len(API_KEYS)
    return {
        "text": (
            f"⚠️ All {len(MODEL_ARSENAL)} API combinations "
            f"({total_keys} keys × {len(MODELS)} models) "
            f"are quota-exhausted for today. "
            f"The analysis tabs still work fully. "
            f"Quotas reset at midnight Pacific time. "
            f"To get more capacity: add more API keys to "
            f"your .env file as GEMINI_KEY_3, GEMINI_KEY_4, etc."
        ),
        "model_label": None,
        "chat": None,
    }


def call_agent(prompt: str) -> str:
    """Chat wrapper: full history + automatic function calling over ALL_TOOLS."""
    result = generate(
        prompt,
        system_instruction=SYSTEM_PROMPT,
        tools=ALL_TOOLS,
        history=st.session_state.chat_history,
        automatic_function_calling=True,
    )
    chat = result.get("chat")
    if chat is not None:
        st.session_state.chat_history = chat.history
    return result["text"]
```

- [ ] **Step 2: Verify import**

Run: `..\venv\Scripts\python.exe -c "from src.agent.caller import generate, call_agent; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Run the existing Gemini smoke test (if a key is present)**

Run: `..\venv\Scripts\python.exe tests/test_gemini.py`
Expected: PASS, or a clear "no key"/quota message — NOT an import/attribute error. (If it fails only due to missing/quota'd keys, that's acceptable; a traceback referencing `generate`/`call_agent` is not.)

- [ ] **Step 4: Commit**

```bash
git add src/agent/caller.py
git commit -m "refactor: extract reusable generate() failover from call_agent"
```

---

## Task 5: Orchestrator (TDD — parser/executor tests first)

**Files:**
- Test: `tests/test_orchestrator.py`
- Create: `src/agent/orchestrator.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_orchestrator.py`:

```python
"""Standalone tests for the orchestrator's plan parsing + execution.

No network: generate is replaced with stubs; tool funcs are replaced in the
registry with no-op stubs that record calls.
"""
import sys

import src.agent.orchestrator as orch

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def _stub_generate(text):
    """Return a generate-compatible callable that always yields `text`."""
    def _g(prompt, *, system_instruction, tools=None, history=None,
           automatic_function_calling=False):
        return {"text": text, "model_label": "stub", "chat": None}
    return _g


def main():
    # --- _parse_plan: clean JSON array ---
    clean = '[{"tool": "run_scoring_analysis", "args": {}, "label": "Score"}]'
    check("parse clean json", orch._parse_plan(clean) is not None)

    # --- _parse_plan: fenced ```json block ---
    fenced = "Here is the plan:\n```json\n" + clean + "\n```\nDone."
    check("parse fenced json", orch._parse_plan(fenced) is not None)

    # --- _parse_plan: garbage -> None ---
    check("parse garbage -> None", orch._parse_plan("sorry, I cannot") is None)

    # --- plan_goal falls back to DEFAULT_PLAN on garbage ---
    steps = orch.plan_goal("do something", generate_fn=_stub_generate("garbage"))
    check("fallback to default plan",
          [s["tool"] for s in steps] == [s["tool"] for s in orch.DEFAULT_PLAN])

    # --- plan_goal validates/keeps a good plan, drops unknown tools/args ---
    good = ('[{"tool":"run_scoring_analysis","args":{"top_percentile":5,'
            '"bogus":1},"label":"Score"},'
            '{"tool":"not_a_tool","args":{},"label":"X"}]')
    steps = orch.plan_goal("score", generate_fn=_stub_generate(good))
    check("keeps valid step", steps[0]["tool"] == "run_scoring_analysis")
    check("strips unknown arg", "bogus" not in steps[0]["args"])
    check("drops unknown tool", all(s["tool"] != "not_a_tool" for s in steps))

    # --- execute_plan runs steps in order, resilient to errors ---
    calls = []
    def ok_tool(**kw): calls.append(("ok", kw)); return {"status": "success"}
    def boom_tool(**kw): calls.append(("boom", kw)); raise ValueError("nope")
    orch.TOOL_REGISTRY["__ok"] = {"func": ok_tool, "desc": "ok", "args": {}}
    orch.TOOL_REGISTRY["__boom"] = {"func": boom_tool, "desc": "boom", "args": {}}

    labels = []
    results = orch.execute_plan(
        [{"tool": "__ok", "args": {}, "label": "A"},
         {"tool": "__boom", "args": {}, "label": "B"},
         {"tool": "__ok", "args": {}, "label": "C"}],
        status_callback=labels.append,
    )
    check("executed all three", len(results) == 3)
    check("status callback fired", labels == ["A", "B", "C"])
    check("error captured, run continued",
          "error" in results[1]["result"] and results[2]["result"]["status"] == "success")

    # --- synthesize_goal returns the stubbed model text ---
    summary = orch.synthesize_goal("goal", results,
                                   generate_fn=_stub_generate("Summary text"))
    check("synthesize returns text", summary == "Summary text")

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_orchestrator.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.orchestrator'`

- [ ] **Step 3: Write the implementation**

Create `src/agent/orchestrator.py`:

```python
"""
Autopilot Orchestrator

Three phases for goal-driven runs:
  plan_goal(goal)      -> Gemini picks an ordered list of tool steps (JSON).
  execute_plan(steps)  -> calls the tool functions directly, in order.
  synthesize_goal(...) -> Gemini writes the closing executive summary.

TOOL_REGISTRY is the single source of truth for which tools exist, their
descriptions (for the planning prompt), and their allowed argument names
(for validation). It is reused by both the catalog and the executor.
"""

import json
import re

from src.agent.caller import generate
from src.agent import tools as T


TOOL_REGISTRY = {
    "run_scoring_analysis": {
        "func": T.run_scoring_analysis,
        "desc": "Score all customers 0-100 and identify power users. Run this first.",
        "args": {"top_percentile": "int"},
    },
    "run_segmentation": {
        "func": T.run_segmentation,
        "desc": "Compare power vs regular users (needs scoring first).",
        "args": {},
    },
    "run_happy_path": {
        "func": T.run_happy_path,
        "desc": "Find the sequences that lead to loyalty (needs scoring first).",
        "args": {"lookback_orders": "int"},
    },
    "run_interventions": {
        "func": T.run_interventions,
        "desc": "Generate campaign recommendations (needs scoring first).",
        "args": {},
    },
    "analyze_churn_risk": {
        "func": T.analyze_churn_risk,
        "desc": "Identify customers at risk of churning by days since last order.",
        "args": {"churn_days": "int"},
    },
    "get_user_profile": {
        "func": T.get_user_profile,
        "desc": "Show the full profile of one customer by user_id.",
        "args": {"user_id": "int"},
    },
    "search_users": {
        "func": T.search_users,
        "desc": "Find customers matching order/reorder/segment filters.",
        "args": {
            "min_orders": "int", "max_orders": "int",
            "min_reorder_rate": "float", "max_reorder_rate": "float",
            "segment": "str", "limit": "int",
        },
    },
    "get_current_stats": {
        "func": T.get_current_stats,
        "desc": "Summarize what has been analyzed so far.",
        "args": {},
    },
    "export_target_list": {
        "func": T.export_target_list,
        "desc": "Export a downloadable CSV of the exact users to target.",
        "args": {"segment": "str", "min_orders": "int",
                 "churn_days": "int", "limit": "int"},
    },
    "draft_campaign_emails": {
        "func": T.draft_campaign_emails,
        "desc": "Write downloadable campaign email drafts (needs scoring first).",
        "args": {"segment": "str"},
    },
    "build_action_plan": {
        "func": T.build_action_plan,
        "desc": "Compile a downloadable prioritized retention checklist (needs scoring first).",
        "args": {"churn_days": "int"},
    },
}


DEFAULT_PLAN = [
    {"tool": "run_scoring_analysis", "args": {}, "label": "Score all customers"},
    {"tool": "analyze_churn_risk", "args": {}, "label": "Find churn risk"},
    {"tool": "export_target_list", "args": {}, "label": "Export target list"},
    {"tool": "build_action_plan", "args": {}, "label": "Build action plan"},
]


_PLANNER_SYSTEM = (
    "You are a planning module for a customer-loyalty analytics agent. "
    "Given a business goal, output ONLY a JSON array of steps and nothing "
    "else. Each step is an object: "
    '{"tool": <tool name>, "args": {<args>}, "label": <short human phrase>}. '
    "Choose 2 to 6 steps. run_scoring_analysis must come before "
    "run_segmentation, run_happy_path, run_interventions, draft_campaign_emails, "
    "and build_action_plan. Use only tools from the catalog."
)


def _tool_catalog() -> str:
    lines = []
    for name, meta in TOOL_REGISTRY.items():
        args = ", ".join(meta["args"].keys()) or "none"
        lines.append(f"- {name}(args: {args}) — {meta['desc']}")
    return "\n".join(lines)


def _parse_plan(text):
    """Return a list of step dicts, or None if no JSON array can be found."""
    if not text:
        return None
    cleaned = text.strip()
    # strip ``` / ```json fences
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    # (a) strict parse
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except (ValueError, TypeError):
        pass
    # (b) regex-extract the first [...] block
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except (ValueError, TypeError):
            pass
    # (c) give up
    return None


def _validate_steps(steps):
    """Keep only known tools; drop unknown arg keys; default missing labels."""
    cleaned = []
    for s in steps or []:
        if not isinstance(s, dict):
            continue
        name = s.get("tool")
        if name not in TOOL_REGISTRY:
            continue
        raw_args = s.get("args") or {}
        if not isinstance(raw_args, dict):
            raw_args = {}
        allowed = TOOL_REGISTRY[name]["args"].keys()
        args = {k: v for k, v in raw_args.items() if k in allowed}
        cleaned.append({"tool": name, "args": args, "label": s.get("label", name)})
    return cleaned


def plan_goal(goal: str, generate_fn=generate):
    """Ask the model for an ordered plan; fall back to DEFAULT_PLAN if unusable."""
    prompt = (
        f"Available tools:\n{_tool_catalog()}\n\n"
        f"Business goal: {goal}\n\n"
        "Return the JSON plan now."
    )
    result = generate_fn(prompt, system_instruction=_PLANNER_SYSTEM)
    steps = _validate_steps(_parse_plan(result.get("text", "")))
    return steps or list(DEFAULT_PLAN)


def execute_plan(steps, status_callback=None):
    """Run each step's tool function in order; never raise on a step failure."""
    results = []
    for s in steps:
        if status_callback:
            status_callback(s["label"])
        meta = TOOL_REGISTRY.get(s["tool"])
        if meta is None:
            results.append({"step": s["label"], "tool": s["tool"],
                            "result": {"error": "unknown tool"}})
            continue
        try:
            out = meta["func"](**s["args"])
        except Exception as e:  # best-effort: record and continue
            out = {"error": f"step failed: {e}"}
        results.append({"step": s["label"], "tool": s["tool"], "result": out})
    return results


_SYNTH_SYSTEM = (
    "You are a retention strategist. Summarize the executed plan for a "
    "marketer in 3-5 bullet points: what was found and which downloadable "
    "deliverables were produced (name them). Be concise and specific."
)


def synthesize_goal(goal: str, results, generate_fn=generate) -> str:
    """Final model call: turn raw step results into an executive summary."""
    prompt = (
        f"Goal: {goal}\n\n"
        f"Step results (JSON):\n{json.dumps(results, default=str)[:6000]}\n\n"
        "Write the summary now."
    )
    result = generate_fn(prompt, system_instruction=_SYNTH_SYSTEM)
    return result.get("text", "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_orchestrator.py`
Expected: all `PASS`, ends with `13 checks passed.`

- [ ] **Step 5: Commit**

```bash
git add src/agent/orchestrator.py tests/test_orchestrator.py
git commit -m "feat: autopilot orchestrator (plan/execute/synthesize) + tests"
```

---

## Task 6: Autopilot tab UI

**Files:**
- Create: `src/ui/tabs/autopilot.py`

- [ ] **Step 1: Write the tab module**

Create `src/ui/tabs/autopilot.py`:

```python
"""
Autopilot Page

Renders Tab 7. The user states a goal; the orchestrator plans it, runs the
steps with a live status log, then synthesizes a summary. All deliverables
produced (this run or in chat) are listed with download buttons.
"""

import streamlit as st

from src.ui.renderer import render_message, download_key
from src.agent.orchestrator import plan_goal, execute_plan, synthesize_goal


_EXAMPLES = [
    "Build a full retention strategy for at-risk power users",
    "Find and target my churning customers",
    "Score customers and draft win-back campaigns",
]


def render_autopilot(features, orders):
    st.header("🤖 Autopilot")
    st.caption(
        "Give the agent a goal. It plans the steps, runs them, and hands you "
        "downloadable deliverables — no tool-by-tool prompting needed."
    )

    cols = st.columns(len(_EXAMPLES))
    for i, ex in enumerate(_EXAMPLES):
        if cols[i].button(ex, key=f"ap_ex_{i}", use_container_width=True):
            st.session_state['autopilot_goal'] = ex

    goal = st.text_input(
        "Goal",
        value=st.session_state.get('autopilot_goal', ''),
        placeholder="e.g. Build a retention plan for churning power users",
    )

    if st.button("🚀 Run goal", type="primary"):
        if not goal.strip():
            st.warning("Enter a goal first.")
        else:
            _run_goal(goal.strip())

    _deliverables_panel()


def _run_goal(goal: str):
    start = len(st.session_state.ui_history)

    # Phase 1 — plan (visible)
    steps = plan_goal(goal)
    plan_md = "### 🧭 Plan\n" + "\n".join(
        f"{i}. {s['label']}" for i, s in enumerate(steps, 1)
    )
    st.markdown(plan_md)

    # Phase 2 — execute (live status log, reusing the staged-loading pattern)
    with st.status("Running plan…", expanded=True) as status:
        results = execute_plan(steps, status_callback=lambda lbl: st.write(f"▸ {lbl}"))
        status.update(label="Plan complete", state="complete", expanded=False)

    # Inline analysis output produced by the tools (charts/tables/text only;
    # artifacts are shown in the deliverables panel below).
    for msg in st.session_state.ui_history[start:]:
        if msg.get("type") != "artifact":
            render_message(msg)

    # Phase 3 — synthesize
    summary = synthesize_goal(goal, results)
    if summary:
        st.markdown("### 📋 Executive summary")
        st.markdown(summary)


def _deliverables_panel():
    arts = st.session_state.get('artifacts', [])
    if not arts:
        return
    st.divider()
    st.subheader("📦 Deliverables")
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

- [ ] **Step 2: Verify import**

Run: `..\venv\Scripts\python.exe -c "from src.ui.tabs.autopilot import render_autopilot; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add src/ui/tabs/autopilot.py
git commit -m "feat: Autopilot tab UI"
```

---

## Task 7: Register the 7th tab in app.py

**Files:**
- Modify: `app.py:14` (import) and `app.py:104-110` (tab list + body)

- [ ] **Step 1: Add the import**

In `app.py`, after line 14 (`from src.ui.tabs.chat import render_chat`), add:

```python
from src.ui.tabs.autopilot import render_autopilot
```

- [ ] **Step 2: Register the tab**

In `app.py`, replace lines 104-110 (the `tabs = st.tabs([...])` block and the six `with tabs[i]:` lines) with:

```python
tabs = st.tabs(["📊 Overview", "⚖️ Scoring", "👥 Segments", "🗺️ Happy Path", "🎯 Interventions", "🤖 AI Chat", "🚀 Autopilot"])
with tabs[0]: render_overview(features, orders)
with tabs[1]: render_scoring()
with tabs[2]: render_segments()
with tabs[3]: render_happy_path(full_data)
with tabs[4]: render_interventions()
with tabs[5]: render_chat(features, orders)
with tabs[6]: render_autopilot(features, orders)
```

- [ ] **Step 3: Verify the app boots headless (HTTP 200)**

Run (PowerShell, from the inner project dir):

```powershell
$p = Start-Process ..\venv\Scripts\python.exe -ArgumentList "-m","streamlit","run","app.py","--server.headless=true","--server.port=8531" -PassThru
Start-Sleep -Seconds 12
try { (Invoke-WebRequest http://localhost:8531 -UseBasicParsing).StatusCode } finally { Stop-Process -Id $p.Id -Force }
```

Expected: `200`

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: register Autopilot as the 7th tab"
```

---

## Task 8: Full verification + journal entry

**Files:**
- Modify: `CLAUDE.md` (add a dated journal entry at the top of the Project Journal)

- [ ] **Step 1: Run the full deterministic test suite**

Run each; every one must end without `sys.exit(1)`:

```powershell
..\venv\Scripts\python.exe tests/test_deliverables.py
..\venv\Scripts\python.exe tests/test_orchestrator.py
..\venv\Scripts\python.exe tests/test_artifacts.py
..\venv\Scripts\python.exe tests/test_persistence.py
```

Expected: all print their PASS lines / `checks passed`; none traceback.

- [ ] **Step 2: Add the journal entry**

In `CLAUDE.md`, directly under `## 📓 Project Journal` (above the most recent dated entry), insert:

```markdown
### 2026-06-08 — Agentic tools + Autopilot
Turned the chat agent into a goal-driven agent with downloadable deliverables.
- **Deliverable tools** (`src/agent/deliverables.py` pure builders +
  `src/agent/tools.py` wrappers): `export_target_list` (CSV of target users),
  `draft_campaign_emails` (markdown drafts), `build_action_plan` (dated
  checklist). Each stores a downloadable artifact in
  `st.session_state.artifacts` and appends a `type="artifact"` chat entry.
- **Autopilot** (`src/agent/orchestrator.py` + `src/ui/tabs/autopilot.py`,
  new 7th tab): a goal is planned by Gemini into a JSON tool plan
  (`plan_goal`, with a parse fallback ladder to `DEFAULT_PLAN`), executed
  step-by-step with a live `st.status` log (`execute_plan`), then summarized
  (`synthesize_goal`). `TOOL_REGISTRY` is the shared catalog/executor source.
- **Caller refactor:** extracted `generate()` (key×model failover) from
  `call_agent`; chat and orchestrator now share it.
- Tests: `tests/test_deliverables.py`, `tests/test_orchestrator.py` (no network).
  App boots headless HTTP 200.
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: journal entry for agentic tools + autopilot"
```

- [ ] **Step 4: Push (standing agreement: push after commits)**

```bash
git push origin <branch>
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Section 1 (deliverable tools + artifact mechanism) → Tasks 1–3. ✓
- Section 2 (orchestrator: plan/execute/synthesize, registry, fallback ladder) → Task 5. ✓
- Section 3 (caller refactor → `generate()`) → Task 4. ✓
- Section 4 (Autopilot tab: plan, status log, deliverables panel) → Tasks 6–7. ✓
- Section 5 (TDD for deterministic pieces, stubbed LLM tests) → Tasks 2 & 5 tests. ✓
- Section 6 (no new deps/secrets, ephemeral artifacts, journal) → Tasks 1, 8; verified by HTTP-200 boot. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; every test step shows assertions. ✓

**Type/name consistency:** `select_target_users`, `to_csv_bytes`, `campaign_emails_markdown`, `action_plan_markdown` are defined in Task 2 and imported verbatim in Task 3. `generate(prompt, *, system_instruction, tools, history, automatic_function_calling)` defined in Task 4 and called with that exact signature by the orchestrator (Task 5) and its test stub. `TOOL_REGISTRY`/`DEFAULT_PLAN`/`_parse_plan`/`plan_goal`/`execute_plan`/`synthesize_goal` defined in Task 5 and used by the tab (Task 6) and tests. `download_key()` defined in Task 1, used in Tasks 1 & 6. Artifact dict shape `{id, filename, mime, content, label}` consistent across Tasks 1, 3, 6. ✓

**Note for executor:** if a Gemini API key is configured, the parser/executor tests still run fully offline (they stub `generate`), but a live click-through of the Autopilot tab in a browser is the human-verification step — `@st.status` runs and download buttons can't be fully driven headlessly.
