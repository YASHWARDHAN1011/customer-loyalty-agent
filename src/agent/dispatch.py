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

        # Nothing matched: the tool path returned no text and the grounded rung
        # is inert (Phase 8). Return an honest fallback rather than an empty
        # answer, which would render as a blank chat bubble that persists.
        return DispatchResult(
            kind="answer",
            text="I couldn't produce an answer for that. Try rephrasing, or ask "
                 "for a specific analysis (e.g. \"score customers\" or \"who is "
                 "at risk of churning?\").")
    except Exception as e:  # never crash the chat on a dispatch failure
        return DispatchResult(kind="answer",
                              text=f"⚠️ I hit an error handling that: {e}")
