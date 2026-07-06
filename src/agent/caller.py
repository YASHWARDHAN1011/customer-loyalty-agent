"""
Agent Caller

`generate()` owns the key×model failover (shared by chat and the autopilot
orchestrator). `call_agent()` is the chat-specific wrapper that keeps the
Gemini conversation history and automatic function calling.
"""

from functools import partial

import streamlit as st
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from google.api_core import retry as garetry

from src.config import LLM_ARSENAL, API_KEYS, SYSTEM_PROMPT
from src.agent.tools import ALL_TOOLS
from src.agent.providers import (
    gemini_generate_text, claude_generate_text, is_eligible, provider_text,
    gemini_tool_turn, claude_tool_turn,
)
from src.agent.tool_specs import TOOL_SPECS, execute_tool
from src.agent.tool_loop import run_tool_conversation, user_text

# Fail fast: never sit in the SDK's exponential-backoff retry loop on a 429 /
# quota error. Without this, an exhausted key blocks for many seconds before
# raising, so rotating all combos can hang the chat for minutes. We'd rather
# fall through to the next combo (or the "all exhausted" message) immediately.
FAST_FAIL = {"retry": garetry.Retry(predicate=lambda exc: False, deadline=20),
             "timeout": 20}


def generate(
    prompt: str,
    *,
    system_instruction: str,
    tools=None,
    history=None,
    automatic_function_calling: bool = False,
    arsenal=None,
    gemini_text_fn=None,
    claude_text_fn=None,
) -> dict:
    """Send one message to an LLM, rotating through LLM_ARSENAL on failure.

    Tool-using calls (tools is not None) are Gemini-only and use the inline chat
    path (returns a `chat`). Tool-less text calls dispatch to the combo's provider
    adapter and return {"text", "model_label", "chat": None}; when Gemini combos
    are exhausted they fall through to Claude. Advances st.session_state.model_idx
    and rolls back ui_history on each failed attempt.
    """
    arsenal = LLM_ARSENAL if arsenal is None else arsenal
    g_text = gemini_text_fn or gemini_generate_text
    c_text = claude_text_fn or claude_generate_text

    if not arsenal:
        return {
            "text": ("⚠️ No API keys configured. "
                     "Please add GEMINI_KEY_1 to your .env file."),
            "model_label": None,
            "chat": None,
        }

    ui_snapshot = len(st.session_state.ui_history)

    for _ in range(len(arsenal)):
        idx = st.session_state.model_idx % len(arsenal)
        combo = arsenal[idx]

        # Tool-using calls are Gemini-only (automatic function calling).
        if not is_eligible(combo, tools is not None):
            st.session_state.model_idx += 1
            continue

        if tools is not None:
            # Gemini tool path — unchanged behavior.
            try:
                genai.configure(api_key=combo['key'])
                model = genai.GenerativeModel(
                    model_name=combo['model'],
                    tools=tools,
                    system_instruction=system_instruction,
                )
                chat = model.start_chat(
                    history=history or [],
                    enable_automatic_function_calling=automatic_function_calling,
                )
                response = chat.send_message(prompt, request_options=FAST_FAIL)
                st.session_state['active_model'] = combo['label']
                return {"text": response.text, "model_label": combo['label'],
                        "chat": chat}
            except google_exceptions.InvalidArgument as e:
                err = str(e)
                if "ToolType" in err or "function" in err.lower():
                    st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
                    st.session_state.model_idx += 1
                    continue
                return {"text": f"⚠️ Invalid request: {err}",
                        "model_label": None, "chat": None}
            except (google_exceptions.ResourceExhausted,
                    google_exceptions.NotFound,
                    google_exceptions.PermissionDenied):
                st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
                st.session_state.model_idx += 1
                continue
            except Exception as e:
                return {"text": f"⚠️ Unexpected error: {str(e)}",
                        "model_label": None, "chat": None}
        else:
            # Tool-less text path — provider adapter; rotate on any failure.
            try:
                text = provider_text(
                    combo, prompt, system_instruction=system_instruction,
                    gemini_fn=g_text, claude_fn=c_text,
                )
                st.session_state['active_model'] = combo['label']
                return {"text": text, "model_label": combo['label'], "chat": None}
            except Exception:
                st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
                st.session_state.model_idx += 1
                continue

    return {
        "text": (
            f"⚠️ All {len(arsenal)} API combinations are quota-exhausted "
            f"right now. The analysis tabs still work fully. Gemini quotas reset "
            f"at midnight Pacific time. For more capacity, add API keys "
            f"(GEMINI_KEY_3, GEMINI_KEY_4, …) or an ANTHROPIC_API_KEY to your "
            f".env file."
        ),
        "model_label": None,
        "chat": None,
    }


def probe_health(arsenal=None) -> str:
    """Cheap upfront check of whether the chat can actually reach Gemini.

    Returns "no_keys" (nothing configured), "ok" (a Gemini combo answered), or
    "exhausted" (every Gemini combo failed — quota/invalid/permission). Chat uses
    function calling, which is Gemini-only, so only Gemini combos are probed.
    Fail-fast (no retry) keeps this to well under a second even when all dead.
    """
    arsenal = LLM_ARSENAL if arsenal is None else arsenal
    if not arsenal:
        return "no_keys"
    probed_gemini = False
    seen_keys = set()
    for combo in arsenal:
        if combo["provider"] != "gemini" or combo["key"] in seen_keys:
            continue  # quota is per-key, so one model per key is enough
        seen_keys.add(combo["key"])
        probed_gemini = True
        try:
            genai.configure(api_key=combo["key"])
            genai.GenerativeModel(combo["model"]).generate_content(
                "ping", request_options=FAST_FAIL,
            )
            return "ok"
        except Exception:
            continue
    return "exhausted" if probed_gemini else "no_keys"


def _provider_turn_for(combo, system_instruction):
    """Bind a combo to a neutral provider_turn(messages, specs) callable."""
    if combo["provider"] == "claude":
        return partial(claude_tool_turn, key=combo["key"], model=combo["model"],
                       system_instruction=system_instruction,
                       base_url=combo.get("base_url"))
    return partial(gemini_tool_turn, key=combo["key"], model=combo["model"],
                   system_instruction=system_instruction,
                   base_url=combo.get("base_url"))


def call_agent(prompt: str) -> str:
    """Provider-agnostic tool-using chat over the neutral history + LLM_ARSENAL.

    Rotates combos on quota/permission errors (Gemini first, Claude on
    exhaustion), driving run_tool_conversation with the combo's turn adapter.
    """
    arsenal = LLM_ARSENAL
    if not arsenal:
        return ("⚠️ No API keys configured. "
                "Please add GEMINI_KEY_1 to your .env file.")

    base_history = st.session_state.chat_history
    history_len = len(base_history)

    for _ in range(len(arsenal)):
        idx = st.session_state.model_idx % len(arsenal)
        combo = arsenal[idx]
        # Fresh copy per attempt so a failed partial turn leaves no residue.
        working = list(base_history) + [user_text(prompt)]
        try:
            provider_turn = _provider_turn_for(combo, SYSTEM_PROMPT)
            text, final_msgs = run_tool_conversation(
                working, TOOL_SPECS, execute_tool, provider_turn)
            st.session_state['active_model'] = combo['label']
            st.session_state.chat_history = final_msgs
            return text
        except Exception:
            # Roll back to the pre-attempt history, advance to the next combo.
            st.session_state.chat_history = base_history[:history_len]
            st.session_state.model_idx += 1
            continue

    return (
        f"⚠️ All {len(arsenal)} API combinations are quota-exhausted right now. "
        f"The analysis tabs still work fully. Gemini quotas reset at midnight "
        f"Pacific time. For more capacity, add API keys or an ANTHROPIC_API_KEY."
    )
