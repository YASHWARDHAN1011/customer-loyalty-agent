"""
Proactive Briefing — session-state glue + grounded narration.

Bridges the pure signal detector (insights.py) to the running app. Reads the
analysis results out of st.session_state, detects the top signals, diffs them
against cross-session memory, and asks the existing LLM caller to narrate them
(with a deterministic continuity line) under MEMORY_SYSTEM. The narrative is
cached so Streamlit reruns don't re-call the model, and any LLM failure falls
back to a deterministic templated briefing so the panel never blanks out.
"""

import streamlit as st

from src.config import MEMORY_SYSTEM
from src.agent.caller import generate
from src.agent.insights import detect_signals, briefing_digest
from src.agent.memory import (
    load_memory, record_snapshot, diff_signals, continuity_line,
)

CHURN_DAYS = 30


def _fallback_narrative(signals, continuity=""):
    """Deterministic briefing used when the LLM is unavailable.

    Pure — references only already-computed signal headlines/details (+ the
    deterministic continuity line), so it stays grounded like the model path.
    """
    if not signals:
        return "Analysis is ready, but nothing stands out as urgent right now."
    top = signals[0]
    lead = f"{top['headline']}. {top['detail']}."
    if len(signals) > 1:
        others = "; ".join(s["headline"] for s in signals[1:])
        lead += f" Also worth your attention: {others}."
    lead += f" Start here: {top['action_label'].lower()}."
    return f"{continuity} {lead}".strip() if continuity else lead


def _narrate(signals, generate_fn, continuity=""):
    """Narrate the signal digest (with continuity) via the LLM; fall back safely."""
    digest = briefing_digest(signals)
    prompt = f"{continuity}\n\n{digest}" if continuity else digest
    try:
        result = generate_fn(prompt, system_instruction=MEMORY_SYSTEM)
        text = (result.get("text") or "").strip()
        if not text:
            raise ValueError("empty narration")
        return text
    except Exception:
        return _fallback_narrative(signals, continuity)


def get_briefing(*, generate_fn=generate, state=None,
                 load_memory_fn=load_memory, record_snapshot_fn=record_snapshot):
    """Build the proactive, continuity-aware briefing from the current session.

    Returns {"ready": bool, "signals": list[dict], "narrative": str}.
    `state`, `generate_fn`, `load_memory_fn`, and `record_snapshot_fn` are
    injectable for testing; in the app they default to st.session_state, the real
    Gemini caller, and the real memory store.
    """
    state = st.session_state if state is None else state

    scored_df = state.get("scored_df")
    if scored_df is None or len(scored_df) == 0:
        return {"ready": False, "signals": [], "narrative": ""}

    top_pct = state.get("top_pct", 10)
    signals = detect_signals(
        state.get("features"),
        scored_df,
        state.get("power"),
        state.get("regular"),
        state.get("power_user_ids") or set(),
        state.get("full_data"),
        churn_days=CHURN_DAYS,
        top_pct=top_pct,
    )

    if not signals:
        return {
            "ready": True,
            "signals": [],
            "narrative": _fallback_narrative(signals),
        }

    # Cache the narrative so reruns don't re-call the model. Key on the inputs
    # that actually change what we'd say.
    cache_key = (top_pct, CHURN_DAYS, len(scored_df))
    cached = state.get("_briefing_cache")
    if cached and cached.get("key") == cache_key:
        narrative = cached["narrative"]
    else:
        memory = load_memory_fn()
        params = {"top_pct": top_pct, "churn_days": CHURN_DAYS, "n": len(scored_df)}
        continuity = continuity_line(diff_signals(signals, memory))
        narrative = _narrate(signals, generate_fn, continuity)
        record_snapshot_fn(signals, params)
        state["_briefing_cache"] = {"key": cache_key, "narrative": narrative}

    return {"ready": True, "signals": signals, "narrative": narrative}
