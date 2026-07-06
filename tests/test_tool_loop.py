# tests/test_tool_loop.py — standalone script
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent.tool_loop import run_tool_conversation, user_text, assistant_text

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

# a scripted provider: first turn asks for a tool, second turn answers
class ScriptedProvider:
    def __init__(self, turns): self.turns = list(turns); self.calls = 0
    def __call__(self, messages, specs):
        t = self.turns[self.calls]; self.calls += 1
        return t

def fake_executor(name, args, specs):
    return f"result:{name}:{args.get('x')}"

turns = [
    {"tool_calls": [{"id": "a1", "name": "do_it", "args": {"x": 7}}]},
    {"text": "final answer using result 7"},
]
prov = ScriptedProvider(turns)
messages = [user_text("run it")]
text, msgs = run_tool_conversation(messages, [], fake_executor, prov, max_steps=6)
ok(text == "final answer using result 7", "returns provider's final text")
ok(prov.calls == 2, "looped once for the tool, once for the answer")
# messages now contain the tool_call and its tool_result
kinds = [b["type"] for m in msgs for b in m["content"]]
ok("tool_call" in kinds and "tool_result" in kinds, "tool_call + tool_result recorded")
tr = [b for m in msgs for b in m["content"] if b["type"] == "tool_result"][0]
ok(tr["id"] == "a1" and "result:do_it:7" in tr["text"], "tool_result carries id + text")

# max_steps guard: a provider that only ever asks for tools
loop_prov = ScriptedProvider([{"tool_calls": [{"id": "x", "name": "t", "args": {}}]}] * 10)
text2, _ = run_tool_conversation([user_text("go")], [], fake_executor, loop_prov, max_steps=3)
ok("limit" in text2.lower(), "hitting max_steps returns a limit message")
ok(loop_prov.calls == 3, "stopped at max_steps")

print(f"test_tool_loop: {checks} checks passed")
