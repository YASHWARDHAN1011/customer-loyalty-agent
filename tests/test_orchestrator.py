"""Standalone tests for the orchestrator's plan parsing + execution.

No network: generate is replaced with stubs; tool funcs are replaced in the
registry with no-op stubs that record calls.
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
