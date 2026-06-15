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
