"""
Agent Caller

Handles sending messages to Gemini with automatic failover.
Tries every key/model combination until one works.
Rolls back UI state if a call fails midway.
"""

import streamlit as st
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions

from src.config import MODEL_ARSENAL, API_KEYS, MODELS, SYSTEM_PROMPT
from src.agent.tools import ALL_TOOLS


def call_agent(prompt: str) -> str:
    """
    Send a message to Gemini with automatic failover.

    Tries every key/model combination until one works.
    Rolls back UI if a call fails midway through.
    """
    if not MODEL_ARSENAL:
        return (
            "⚠️ No API keys configured. "
            "Please add GEMINI_KEY_1 to your .env file."
        )

    # Take UI snapshot for rollback
    ui_snapshot = len(st.session_state.ui_history)

    # Try every combination
    for attempt in range(len(MODEL_ARSENAL)):

        # Get current combo using modulo for wraparound
        idx = st.session_state.model_idx % len(MODEL_ARSENAL)
        config = MODEL_ARSENAL[idx]

        try:
            # Set API key for this attempt
            genai.configure(api_key=config['key'])

            # Create model with tools and system prompt
            model = genai.GenerativeModel(
                model_name=config['model'],
                tools=ALL_TOOLS,
                system_instruction=SYSTEM_PROMPT
            )

            # Restore full conversation history
            chat = model.start_chat(
                history=st.session_state.chat_history,
                enable_automatic_function_calling=True
            )

            # ACTUAL API CALL
            response = chat.send_message(prompt)

            # Save updated conversation history
            st.session_state.chat_history = chat.history

            # Update sidebar to show active model
            st.session_state['active_model'] = (
                config['label']
            )

            return response.text

        except google_exceptions.ResourceExhausted:
            # Quota hit — rollback and try next
            st.session_state.ui_history = (
                st.session_state.ui_history[:ui_snapshot]
            )
            st.session_state.model_idx += 1
            continue

        except google_exceptions.NotFound:
            # Model not available in this region/tier
            st.session_state.ui_history = (
                st.session_state.ui_history[:ui_snapshot]
            )
            st.session_state.model_idx += 1
            continue

        except google_exceptions.InvalidArgument as e:
            # Invalid request — usually tool schema issue
            err = str(e)
            if "ToolType" in err or "function" in err.lower():
                st.session_state.ui_history = (
                    st.session_state.ui_history[:ui_snapshot]
                )
                st.session_state.model_idx += 1
                continue
            return f"⚠️ Invalid request: {err}"

        except google_exceptions.PermissionDenied:
            # Invalid API key
            st.session_state.ui_history = (
                st.session_state.ui_history[:ui_snapshot]
            )
            st.session_state.model_idx += 1
            continue

        except Exception as e:
            # Unexpected error — don't retry, report it
            return f"⚠️ Unexpected error: {str(e)}"

    # All combos exhausted
    total_keys = len(API_KEYS)
    return (
        f"⚠️ All {len(MODEL_ARSENAL)} API combinations "
        f"({total_keys} keys × {len(MODELS)} models) "
        f"are quota-exhausted for today. "
        f"The analysis tabs still work fully. "
        f"Quotas reset at midnight Pacific time. "
        f"To get more capacity: add more API keys to "
        f"your .env file as GEMINI_KEY_3, GEMINI_KEY_4, etc."
    )
