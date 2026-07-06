# tests/test_call_agent_boot.py — standalone script
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 1) App boots with 0 exceptions on canonical data (covers the chat wiring).
from streamlit.testing.v1 import AppTest

at = AppTest.from_file("app.py", default_timeout=120)
at.run()
assert len(at.exception) == 0, f"boot exceptions: {[e.value for e in at.exception]}"

# 2) Loop wiring: a scripted provider drives a real tool end-to-end, no network.
from src.agent.tool_loop import run_tool_conversation, user_text
from src.agent.tool_specs import TOOL_SPECS, execute_tool

turns = [
    {"tool_calls": [{"id": "s1", "name": "get_current_stats", "args": {}}]},
    {"text": "Here is your status."},
]
i = {"n": 0}
def scripted(messages, specs):
    t = turns[i["n"]]; i["n"] += 1; return t

text, msgs = run_tool_conversation([user_text("status?")], TOOL_SPECS,
                                   execute_tool, scripted)
assert text == "Here is your status.", "scripted agent returns final text"
assert any(b["type"] == "tool_result" for m in msgs for b in m["content"]), \
    "a real tool executed and fed a result back"

print("test_call_agent_boot: checks passed")
