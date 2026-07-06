"""The provider-agnostic tool loop.

Pure orchestration: no Streamlit, no SDK imports. `provider_turn` (one SDK
round-trip, neutral-in/neutral-out) and `executor` are injected, so the loop is
unit-testable with a scripted fake provider. Neutral message shape:

    {"role": "user"|"assistant", "content": [block, ...]}
    block: {"type":"text","text":str}
           {"type":"tool_call","id":str,"name":str,"args":dict}   (assistant)
           {"type":"tool_result","id":str,"text":str}             (user turn)
"""

DEFAULT_MAX_STEPS = 6


def user_text(text):
    return {"role": "user", "content": [{"type": "text", "text": text}]}


def assistant_text(text):
    return {"role": "assistant", "content": [{"type": "text", "text": text}]}


def run_tool_conversation(messages, specs, executor, provider_turn,
                          max_steps=DEFAULT_MAX_STEPS):
    """Drive one user turn to a final text answer, executing tool calls.

    Mutates and returns `messages` (the neutral history) plus the final text.
    """
    for _ in range(max_steps):
        turn = provider_turn(messages, specs)
        calls = turn.get("tool_calls")
        if calls:
            messages.append({
                "role": "assistant",
                "content": [{"type": "tool_call", "id": c["id"],
                             "name": c["name"], "args": c.get("args") or {}}
                            for c in calls],
            })
            results = []
            for c in calls:
                text = executor(c["name"], c.get("args") or {}, specs)
                results.append({"type": "tool_result", "id": c["id"], "text": text})
            messages.append({"role": "user", "content": results})
            continue
        text = turn.get("text", "")
        messages.append(assistant_text(text))
        return text, messages
    limit_msg = ("I reached my step limit while working on that. "
                 "Here's what I have so far — try narrowing the request.")
    messages.append(assistant_text(limit_msg))
    return limit_msg, messages
