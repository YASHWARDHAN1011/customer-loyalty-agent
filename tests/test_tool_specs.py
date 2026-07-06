# tests/test_tool_specs.py — standalone script
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import tool_specs as ts
from src.agent.tools import ALL_TOOLS

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

# spec_from_function derives a JSON-schema spec from a typed signature
def sample(top_percentile: int = 10, note: str = None) -> dict:
    """Do a thing. Second line ignored."""
    return {"ok": True}

spec = ts.spec_from_function(sample)
ok(spec["name"] == "sample", "spec name = function name")
ok(spec["description"].startswith("Do a thing"), "description = first docstring line")
props = spec["input_schema"]["properties"]
ok(props["top_percentile"]["type"] == "integer", "int -> integer")
ok(props["note"]["type"] == "string", "str -> string")
ok(spec["input_schema"]["required"] == [], "params with defaults are optional")
ok(spec["fn"] is sample, "spec carries the callable")

# TOOL_SPECS covers every tool in ALL_TOOLS, keyed by name
names = {s["name"] for s in ts.TOOL_SPECS}
ok(names == {f.__name__ for f in ALL_TOOLS}, "TOOL_SPECS matches ALL_TOOLS")

# execute_tool runs a tool and returns a text summary
def fake_ok(x: int = 1) -> dict:
    """Fake."""
    return {"scored": 5, "power": 2}
specs = [ts.spec_from_function(fake_ok)]
out = ts.execute_tool("fake_ok", {"x": 3}, specs)
ok(isinstance(out, str) and "scored" in out, "execute_tool returns a text summary")

# execute_tool catches a raising tool -> relayable text, never raises
def boom() -> dict:
    """Boom."""
    raise KeyError("total_orders")
specs2 = [ts.spec_from_function(boom)]
out2 = ts.execute_tool("boom", {}, specs2)
ok("failed" in out2.lower() and "total_orders" in out2, "raising tool -> error text")

# unknown tool -> error text, not a crash
ok("unknown" in ts.execute_tool("nope", {}, specs2).lower(), "unknown tool -> error text")

print(f"test_tool_specs: {checks} checks passed")
