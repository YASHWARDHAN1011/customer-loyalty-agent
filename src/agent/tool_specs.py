"""Neutral tool registry: the single source of truth both LLM providers read.

Each spec is {name, description, input_schema (JSON Schema), fn}. Specs are
auto-derived from each tool's typed signature (DRY — no hand-maintained schemas).
`execute_tool` is the ONLY place a tool function is invoked; it summarizes the
tool's return for the model and catches any exception so a broken/Instacart-bound
tool degrades into relayable text instead of crashing the chat.
"""

import inspect
import json

from src.agent.tools import ALL_TOOLS

_PY_TO_JSON = {int: "integer", float: "number", str: "string", bool: "boolean"}


def spec_from_function(fn):
    """Build a neutral tool spec from a function's signature + docstring."""
    sig = inspect.signature(fn)
    props, required = {}, []
    for pname, p in sig.parameters.items():
        if pname.startswith("_"):
            continue
        jtype = _PY_TO_JSON.get(p.annotation, "string")
        props[pname] = {"type": jtype, "description": pname.replace("_", " ")}
        if p.default is inspect.Parameter.empty:
            required.append(pname)
    doc = (inspect.getdoc(fn) or "").strip().splitlines()
    description = doc[0] if doc else fn.__name__
    return {
        "name": fn.__name__,
        "description": description,
        "input_schema": {"type": "object", "properties": props, "required": required},
        "fn": fn,
    }


TOOL_SPECS = [spec_from_function(fn) for fn in ALL_TOOLS]


def _summarize(name, result):
    """Concise text the model can narrate, from a tool's return value."""
    if result is None:
        return f"{name} completed."
    if isinstance(result, (dict, list)):
        try:
            return json.dumps(result, default=str)[:1500]
        except Exception:
            return str(result)[:1500]
    return str(result)[:1500]


def execute_tool(name, args, specs=None):
    """Run the named tool with args; return a text result. Never raises."""
    specs = TOOL_SPECS if specs is None else specs
    spec = next((s for s in specs if s["name"] == name), None)
    if spec is None:
        return f"Unknown tool: {name}"
    try:
        return _summarize(name, spec["fn"](**(args or {})))
    except Exception as e:
        return f"Tool {name} failed: {type(e).__name__}: {e}"
