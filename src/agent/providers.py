"""
LLM provider adapters + dispatch helpers.

Two thin, non-streaming text adapters with one shared signature
(prompt, *, system_instruction, key, model) -> str, plus pure helpers used by
caller.generate() to route a combo to the right provider and to keep tool-using
calls on Gemini. The adapters raise on SDK error so the caller's rotation can
fail over. Grounding is unaffected — providers only narrate.
"""

import google.generativeai as genai
from google.api_core import retry as garetry

# Fail fast on quota/429 instead of the SDK's long backoff retry (see caller.py).
_FAST_FAIL = {"retry": garetry.Retry(predicate=lambda exc: False, deadline=20),
              "timeout": 20}


def gemini_generate_text(prompt, *, system_instruction, key, model):
    """One non-streaming Gemini text completion."""
    genai.configure(api_key=key)
    m = genai.GenerativeModel(model_name=model,
                              system_instruction=system_instruction)
    response = m.generate_content(prompt, request_options=_FAST_FAIL)
    return response.text


def claude_generate_text(prompt, *, system_instruction, key, model):
    """One non-streaming Claude text completion (system prompt is cached)."""
    import anthropic  # lazy: only needed when a Claude combo is actually used
    client = anthropic.Anthropic(api_key=key)
    response = client.messages.create(
        model=model,
        max_tokens=1024,
        system=[{
            "type": "text",
            "text": system_instruction,
            "cache_control": {"type": "ephemeral"},
        }],
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(
        block.text for block in response.content
        if getattr(block, "type", None) == "text"
    )


def is_eligible(combo, has_tools):
    """Tool-using calls are Gemini-only; tool-less calls accept any provider."""
    return (not has_tools) or combo["provider"] == "gemini"


def provider_text(combo, prompt, *, system_instruction,
                  gemini_fn=gemini_generate_text,
                  claude_fn=claude_generate_text):
    """Dispatch a tool-less text call to the combo's provider adapter."""
    if combo["provider"] == "claude":
        return claude_fn(prompt, system_instruction=system_instruction,
                         key=combo["key"], model=combo["model"])
    return gemini_fn(prompt, system_instruction=system_instruction,
                     key=combo["key"], model=combo["model"])


# ── Phase 4.5: provider-agnostic tool-turn adapters ──────────────────────────
# Each takes neutral messages + tool specs, does ONE SDK round-trip, and returns
# either {"text": str} or {"tool_calls": [{"id","name","args"}]}. These are the
# translators the pure tool loop (tool_loop.run_tool_conversation) drives.


def _specs_to_claude(specs):
    return [{"name": s["name"], "description": s["description"],
             "input_schema": s["input_schema"]} for s in specs]


def _messages_to_claude(messages):
    """Neutral messages -> Anthropic messages list."""
    out = []
    for m in messages:
        content = []
        for b in m["content"]:
            if b["type"] == "text":
                content.append({"type": "text", "text": b["text"]})
            elif b["type"] == "tool_call":
                content.append({"type": "tool_use", "id": b["id"],
                                "name": b["name"], "input": b["args"]})
            elif b["type"] == "tool_result":
                content.append({"type": "tool_result", "tool_use_id": b["id"],
                                "content": b["text"]})
        out.append({"role": m["role"], "content": content})
    return out


def claude_tool_turn(messages, specs, *, key, model, system_instruction=None,
                     base_url=None, max_tokens=1024, _client_factory=None):
    """One Claude round-trip over the neutral tool protocol."""
    if _client_factory is None:
        import anthropic  # lazy: only when a Claude combo is actually used
        _client_factory = anthropic.Anthropic
    client = _client_factory(api_key=key, base_url=base_url)
    kwargs = {"model": model, "max_tokens": max_tokens,
              "tools": _specs_to_claude(specs),
              "messages": _messages_to_claude(messages)}
    if system_instruction:
        kwargs["system"] = system_instruction
    resp = client.messages.create(**kwargs)
    tool_calls = [{"id": b.id, "name": b.name, "args": dict(b.input)}
                  for b in resp.content if getattr(b, "type", None) == "tool_use"]
    if tool_calls:
        return {"tool_calls": tool_calls}
    text = "".join(getattr(b, "text", "") for b in resp.content
                   if getattr(b, "type", None) == "text")
    return {"text": text}


def _specs_to_gemini(specs):
    """Neutral specs -> Gemini function declarations (dict form)."""
    return [{"function_declarations": [
        {"name": s["name"], "description": s["description"],
         "parameters": s["input_schema"]} for s in specs]}]


def _messages_to_gemini(messages):
    """Neutral messages -> Gemini contents (role 'model' for assistant)."""
    from google.generativeai import protos
    contents = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        parts = []
        for b in m["content"]:
            if b["type"] == "text":
                parts.append(protos.Part(text=b["text"]))
            elif b["type"] == "tool_call":
                parts.append(protos.Part(function_call=protos.FunctionCall(
                    name=b["name"], args=b["args"])))
            elif b["type"] == "tool_result":
                parts.append(protos.Part(function_response=protos.FunctionResponse(
                    name=b["id"], response={"result": b["text"]})))
        contents.append(protos.Content(role=role, parts=parts))
    return contents


def gemini_tool_turn(messages, specs, *, key, model, system_instruction=None,
                     base_url=None, _model_factory=None):
    """One Gemini round-trip over the neutral protocol (manual function calling)."""
    if _model_factory is None:
        genai.configure(api_key=key)
        _model_factory = lambda: genai.GenerativeModel(
            model_name=model, tools=_specs_to_gemini(specs),
            system_instruction=system_instruction)
    gmodel = _model_factory()
    resp = gmodel.generate_content(_messages_to_gemini(messages),
                                   request_options=_FAST_FAIL)
    tool_calls = []
    for part in resp.candidates[0].content.parts:
        fc = getattr(part, "function_call", None)
        if fc and fc.name:
            tool_calls.append({"id": fc.name, "name": fc.name,
                               "args": dict(fc.args)})
    if tool_calls:
        return {"tool_calls": tool_calls}
    return {"text": resp.text}
