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

    # parsed dict whose mode isn't exactly "goal" -> answer (case-sensitive)
    check("non-goal mode -> answer",
          route("m", generate_fn=_gen('{"mode":"GOAL"}'))["mode"] == "answer")
    check("unknown mode -> answer",
          route("m", generate_fn=_gen('{"mode":"plan"}'))["mode"] == "answer")

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
