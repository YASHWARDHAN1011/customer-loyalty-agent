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
