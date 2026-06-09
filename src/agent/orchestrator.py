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
