"""
Agent Caller

`generate()` owns the key×model failover (shared by chat and the autopilot
orchestrator). `call_agent()` is the chat-specific wrapper that keeps the
Gemini conversation history and automatic function calling.
"""

import streamlit as st
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from src.config import MODEL_ARSENAL, API_KEYS, MODELS, SYSTEM_PROMPT
from src.agent.tools import ALL_TOOLS


def generate(
    prompt: str,
    *,
    system_instruction: str,
    tools=None,
    history=None,
    automatic_function_calling: bool = False,
) -> dict:
    """Send one message to Gemini, rotating through MODEL_ARSENAL on failure.

    Returns {"text", "model_label", "chat"} on success (chat may be None for
    the all-exhausted / no-keys messages). Advances st.session_state.model_idx
    and rolls back ui_history on each failed attempt, exactly as the old
    call_agent did.
    """
    if not MODEL_ARSENAL:
        return {
            "text": (
                "⚠️ No API keys configured. "
                "Please add GEMINI_KEY_1 to your .env file."
            ),
            "model_label": None,
            "chat": None,
        }

    ui_snapshot = len(st.session_state.ui_history)

    for _ in range(len(MODEL_ARSENAL)):
        idx = st.session_state.model_idx % len(MODEL_ARSENAL)
        config = MODEL_ARSENAL[idx]
        try:
            genai.configure(api_key=config['key'])
            model = genai.GenerativeModel(
                model_name=config['model'],
                tools=tools,
                system_instruction=system_instruction,
            )
            chat = model.start_chat(
                history=history or [],
                enable_automatic_function_calling=automatic_function_calling,
            )
            response = chat.send_message(prompt)
            st.session_state['active_model'] = config['label']
            return {
                "text": response.text,
                "model_label": config['label'],
                "chat": chat,
            }

        except google_exceptions.ResourceExhausted:
            st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
            st.session_state.model_idx += 1
            continue
        except google_exceptions.NotFound:
            st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
            st.session_state.model_idx += 1
            continue
        except google_exceptions.InvalidArgument as e:
            err = str(e)
            if "ToolType" in err or "function" in err.lower():
                st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
                st.session_state.model_idx += 1
                continue
            return {"text": f"⚠️ Invalid request: {err}", "model_label": None, "chat": None}
        except google_exceptions.PermissionDenied:
            st.session_state.ui_history = st.session_state.ui_history[:ui_snapshot]
            st.session_state.model_idx += 1
            continue
        except Exception as e:
            return {"text": f"⚠️ Unexpected error: {str(e)}", "model_label": None, "chat": None}

    total_keys = len(API_KEYS)
    return {
        "text": (
            f"⚠️ All {len(MODEL_ARSENAL)} API combinations "
            f"({total_keys} keys × {len(MODELS)} models) "
            f"are quota-exhausted for today. "
            f"The analysis tabs still work fully. "
            f"Quotas reset at midnight Pacific time. "
            f"To get more capacity: add more API keys to "
            f"your .env file as GEMINI_KEY_3, GEMINI_KEY_4, etc."
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
