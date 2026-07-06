"""Standalone tests for provider abstraction. No network, no Streamlit."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def main():
    from src.config import build_llm_arsenal

    # With an Anthropic key: Gemini combos first, then Claude combos.
    a = build_llm_arsenal(["k1", "k2"], ["m1", "m2"], "anthro", ["c1"])
    check("count = gemini*models + claude", len(a) == 2 * 2 + 1)
    check("gemini combos first", all(c["provider"] == "gemini" for c in a[:4]))
    check("claude combo last", a[-1]["provider"] == "claude")
    check("gemini combo shape",
          set(a[0].keys()) == {"provider", "key", "model", "label"})
    check("claude combo uses anthropic key + model",
          a[-1]["key"] == "anthro" and a[-1]["model"] == "c1")
    check("gemini labels keyed", a[0]["label"] == "Key1+m1")

    # No Anthropic key -> Gemini-only (identical to today).
    b = build_llm_arsenal(["k1"], ["m1"], None, ["c1"])
    check("no key -> no claude", all(c["provider"] == "gemini" for c in b))
    check("no key -> len 1", len(b) == 1)

    # Empty-string key is falsy -> no claude.
    e = build_llm_arsenal(["k1"], ["m1"], "", ["c1"])
    check("empty key -> no claude", all(c["provider"] == "gemini" for c in e))

    # --- dispatch helpers (pure) ---
    from src.agent.providers import is_eligible, provider_text

    g = {"provider": "gemini", "key": "k", "model": "m", "label": "Key1+m"}
    c = {"provider": "claude", "key": "a", "model": "c1", "label": "Claude+c1"}

    # eligibility: tool-using calls are Gemini-only
    check("gemini eligible with tools", is_eligible(g, True) is True)
    check("claude NOT eligible with tools", is_eligible(c, True) is False)
    check("claude eligible without tools", is_eligible(c, False) is True)

    # provider_text dispatches to the right adapter
    def gfn(prompt, *, system_instruction, key, model):
        return f"G:{prompt}:{model}"

    def cfn(prompt, *, system_instruction, key, model):
        return f"C:{prompt}:{model}"

    check("dispatch gemini",
          provider_text(g, "hi", system_instruction="s", gemini_fn=gfn,
                        claude_fn=cfn) == "G:hi:m")
    check("dispatch claude",
          provider_text(c, "hi", system_instruction="s", gemini_fn=gfn,
                        claude_fn=cfn) == "C:hi:c1")

    # simulated cross-provider failover: gemini adapter fails, claude succeeds
    def boom_g(prompt, *, system_instruction, key, model):
        raise RuntimeError("quota")

    def ok_c(prompt, *, system_instruction, key, model):
        return "ANSWER"

    arsenal = [g, dict(g, label="Key2+m"), c]
    result, landed = None, None
    idx = 0
    for _ in range(len(arsenal)):
        combo = arsenal[idx % len(arsenal)]
        if not is_eligible(combo, False):
            idx += 1; continue
        try:
            result = provider_text(combo, "p", system_instruction="s",
                                   gemini_fn=boom_g, claude_fn=ok_c)
            landed = combo["provider"]
            break
        except Exception:
            idx += 1; continue
    check("failover reaches claude", result == "ANSWER" and landed == "claude")

    # --- Phase 4.5: turn adapters translate neutral <-> SDK (mocked, no net) ---
    from src.agent.providers import claude_tool_turn
    from src.agent.tool_loop import user_text
    from src.agent import tool_specs as _ts

    def _sample(x: int = 1) -> dict:
        """Sample."""
        return {}
    _specs = [_ts.spec_from_function(_sample)]

    class _Block:
        def __init__(self, **kw): self.__dict__.update(kw)

    class _Resp:
        def __init__(self, content, stop_reason):
            self.content = content; self.stop_reason = stop_reason

    class _FakeMessages:
        def __init__(self, resp): self._resp = resp
        def create(self, **kw): self.kw = kw; return self._resp

    class _FakeClient:
        def __init__(self, resp): self.messages = _FakeMessages(resp)

    # Claude tool_use block -> neutral tool_calls
    tool_resp = _Resp(
        [_Block(type="tool_use", id="tu1", name="_sample", input={"x": 5})],
        "tool_use")
    turn = claude_tool_turn(
        [user_text("hi")], _specs, key="k", model="m",
        base_url="http://enterprise",
        _client_factory=lambda **kw: _FakeClient(tool_resp))
    check("claude tool_use -> neutral tool_call",
          turn["tool_calls"][0]["name"] == "_sample")
    check("claude input -> args", turn["tool_calls"][0]["args"] == {"x": 5})

    # Claude text block -> neutral text; base_url threaded to the client
    text_resp = _Resp([_Block(type="text", text="done")], "end_turn")
    fc = {"client": None}
    def _factory(**kw):
        fc["client"] = kw; return _FakeClient(text_resp)
    turn2 = claude_tool_turn([user_text("hi")], _specs, key="k", model="m",
                             base_url="http://enterprise", _client_factory=_factory)
    check("claude text -> neutral text", turn2["text"] == "done")
    check("base_url threaded to client",
          fc["client"]["base_url"] == "http://enterprise")

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
