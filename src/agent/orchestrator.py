"""
Autopilot Orchestrator

Primary (reflexive) path for goal-driven runs:
  run_reflexive(goal)  -> closed loop: run a step, read its real numbers, decide
                          the next move (or stop). Reasoning surfaced per step.
  decide_next_step(..) -> one grounded Gemini call → a single JSON decision.
  synthesize_goal(...) -> Gemini writes the closing executive summary.

Legacy (open-loop) path, retained as the deterministic fallback + still tested:
  plan_goal(goal)      -> Gemini picks an ordered list of tool steps (JSON).
  execute_plan(steps)  -> calls the tool functions directly, in order.

TOOL_REGISTRY is the single source of truth for which tools exist, their
descriptions (for the planning prompt), and their allowed argument names
(for validation). It is reused by the catalog, the executor, and the loop.
"""

import json
import re

from src.agent.caller import generate
from src.agent import tools as T
from src.config import REFLEXIVE_SYSTEM


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
    "simulate_campaign": {
        "func": T.simulate_campaign,
        "desc": "Project a what-if campaign: lift one feature for regular users by a percent and count how many become power users (needs scoring first).",
        "args": {"feature": "str", "lift_pct": "float"},
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
        result = step.get("result")
        if not isinstance(result, dict):
            result = {}
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


MAX_STEPS = 6

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
    """Fallback: run the unrun steps of DEFAULT_PLAN in order, respecting the cap."""
    for s in DEFAULT_PLAN:
        if len(history) >= MAX_STEPS:
            break
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
            step = decision

        # args values are scalars (decide_next_step filters to the registry's
        # int/float/str args), so they are always hashable here.
        key = (step["tool"], frozenset(step["args"].items()))
        if key in seen:           # no forward progress -> stop
            break
        seen.add(key)
        _run_step(step, history, executed, status_callback)

    return history
