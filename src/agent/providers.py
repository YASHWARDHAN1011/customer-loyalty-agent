"""
LLM provider adapters + dispatch helpers.

Two thin, non-streaming text adapters with one shared signature
(prompt, *, system_instruction, key, model) -> str, plus pure helpers used by
caller.generate() to route a combo to the right provider and to keep tool-using
calls on Gemini. The adapters raise on SDK error so the caller's rotation can
fail over. Grounding is unaffected — providers only narrate.
"""

import google.generativeai as genai


def gemini_generate_text(prompt, *, system_instruction, key, model):
    """One non-streaming Gemini text completion."""
    genai.configure(api_key=key)
    m = genai.GenerativeModel(model_name=model,
                              system_instruction=system_instruction)
    response = m.generate_content(prompt)
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
