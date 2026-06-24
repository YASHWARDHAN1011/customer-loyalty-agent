"""
Agent Caller

`generate()` owns the key×model failover (shared by chat and the autopilot
orchestrator). `call_agent()` is the chat-specific wrapper that keeps the
Gemini conversation history and automatic function calling.
"""

import streamlit as st
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from google.api_core import retry as garetry

from src.config import LLM_ARSENAL, API_KEYS, SYSTEM_PROMPT
from src.agent.tools import ALL_TOOLS
from src.agent.providers import (
    gemini_generate_text, claude_generate_text, is_eligible, provider_text,
)

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


def call_agent(prompt: str) -> str:
    """Chat wrapper: full history + automatic function calling over ALL_TOOLS."""
    result = generate(
        prompt,
        system_instruction=SYSTEM_PROMPT,
        tools=ALL_TOOLS,
        history=st.session_state.chat_history,
        automatic_function_calling=True,
    )
    chat = result.get("chat")
    if chat is not None:
        st.session_state.chat_history = chat.history
    return result["text"]
