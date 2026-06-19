"""
Message router — decides whether a chat message is a quick question (answer) or a
multi-step objective (goal).

Pure aside from one injected LLM classification call. This is a JUDGMENT call, not
a business number, so it does not touch the grounding contract — the reactive
answer path and the reflexive goal loop both stay grounded as before. Any failure
defaults to "answer": cheaper and safer than wrongly launching an autonomous run.
"""

import json
import re

from src.config import ROUTER_SYSTEM
from src.agent.caller import generate


def _parse(text):
    """Parse the router's single JSON object, or None if unusable."""
    if not text:
        return None
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    try:
        data = json.loads(cleaned)
        if isinstance(data, dict):
            return data
    except (ValueError, TypeError):
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, dict):
                return data
        except (ValueError, TypeError):
            pass
    return None


def route(message, generate_fn=generate):
    """Classify `message`. Returns {"mode": "answer"|"goal", "goal": str}.

    `goal` is the goal text when mode is "goal" (falling back to the original
    message if the model omits it), else "". Defaults to answer-mode on any
    failure, empty, or unparseable output.
    """
    try:
        raw = generate_fn(message, system_instruction=ROUTER_SYSTEM)
        data = _parse(raw.get("text", ""))
    except Exception:
        data = None

    if data and data.get("mode") == "goal":
        return {"mode": "goal", "goal": data.get("goal") or message}
    return {"mode": "answer", "goal": ""}
