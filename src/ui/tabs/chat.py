"""
Chat Page

Renders Tab 6: AI Chat.
"""

import streamlit as st
from src.config import API_KEYS, MODEL_ARSENAL
from src.ui.renderer import render_message
from src.agent.caller import call_agent


def render_chat(features, orders):
    st.header("🤖 AI Analyst Chat")
    st.caption(
        "Gemini AI with function calling — it can run "
        "analysis tools, interpret results, and answer "
        "questions about your customers."
    )

    if not API_KEYS:
        st.error(
            "⚠️ No API keys configured. "
            "Add GEMINI_KEY_1=your_key to your .env file, "
            "then restart the app."
        )
    else:
        idx = st.session_state.model_idx % len(MODEL_ARSENAL)
        active = MODEL_ARSENAL[idx]

        status_col1, status_col2, status_col3 = st.columns(3)
        with status_col1:
            st.metric(
                "Active Model",
                active['model'].replace('gemini-', '')
            )
        with status_col2:
            st.metric(
                "API Keys Loaded",
                len(API_KEYS)
            )
        with status_col3:
            used = min(
                st.session_state.model_idx, len(MODEL_ARSENAL)
            )
            remaining = len(MODEL_ARSENAL) - used
            st.metric(
                "Combos Remaining",
                f"{remaining}/{len(MODEL_ARSENAL)}"
            )

    st.divider()

    if not st.session_state.ui_history:
        total_users = features['user_id'].nunique()
        total_orders_count = len(orders)
        welcome = (
            f"👋 Hello! I'm your Customer Loyalty Intelligence Agent.\n\n"
            f"I'm connected to the Instacart dataset:\n"
            f"- **{total_users:,}** customers\n"
            f"- **{total_orders_count:,}** orders\n"
            f"- **{features['dept_diversity'].max():.0f}** "
            f"unique departments\n\n"
            f"**What I can do:**\n"
            f"- 📊 Score all customers by loyalty (0-100)\n"
            f"- 👥 Compare power users vs regular users\n"
            f"- 🗺️ Find the happy path to loyalty\n"
            f"- 🎯 Generate intervention recommendations\n\n"
            f"**Try asking:**\n"
            f"- *\"Who are our power users?\"*\n"
            f"- *\"Run the full analysis\"*\n"
            f"- *\"What makes our best customers different?\"*\n"
            f"- *\"Find the happy path to loyalty\"*"
        )
        st.session_state.ui_history.append({
            "role": "assistant",
            "type": "text",
            "content": welcome
        })

    for msg in st.session_state.ui_history:
        render_message(msg)

    if prompt := st.chat_input(
        "Ask about your customers... "
        "(e.g. 'Who are our power users?')"
    ):
        st.session_state.ui_history.append({
            "role": "user",
            "type": "text",
            "content": prompt
        })

        with st.chat_message("user"):
            st.markdown(prompt)

        with st.spinner("🧠 Agent thinking..."):
            response = call_agent(prompt)

        st.session_state.ui_history.append({
            "role": "assistant",
            "type": "text",
            "content": response
        })

        st.rerun()

    st.divider()
    st.caption("Quick actions:")
    q1, q2, q3, q4 = st.columns(4)

    if q1.button("📊 Score customers", use_container_width=True):
        _handle_quick_action("Score all customers and identify power users")

    if q2.button("👥 Compare segments", use_container_width=True):
        _handle_quick_action("Compare power users vs regular users")

    if q3.button("🗺️ Happy path", use_container_width=True):
        _handle_quick_action("Find the happy path to power user status")

    if q4.button("🎯 Interventions", use_container_width=True):
        _handle_quick_action("What campaigns should we run to convert regular users?")

    q5, q6, q7, q8 = st.columns(4)

    if q5.button("⚠️ Churn risk", use_container_width=True):
        _handle_quick_action("Who is at risk of churning? Use a 30-day threshold.")

    if q6.button("👤 User lookup", use_container_width=True):
        _handle_quick_action("Show me the profile of user 1")

    if q7.button("🔍 Filter users", use_container_width=True):
        _handle_quick_action("Find users with more than 15 orders and a reorder rate above 0.6")

    if q8.button("📋 Current stats", use_container_width=True):
        _handle_quick_action("Give me a summary of what has been analyzed so far")

    with st.expander("💡 Example questions you can ask"):
        st.markdown("""
**Scoring & Power Users**
- *"Score customers and identify the top 5% as power users"*
- *"Who are our top 20 most loyal customers?"*
- *"What's the loyalty score distribution look like?"*

**Churn & Retention**
- *"Who hasn't ordered in 45 days?"*
- *"How many power users are at churn risk?"*
- *"Show me at-risk customers who order infrequently"*

**Individual Lookup & Filtering**
- *"Tell me about user 12345"*
- *"Show me 10 users with reorder rate above 0.8"*
- *"Find regular users who have placed more than 10 orders"*

**Strategy & Campaigns**
- *"What campaign should I run first to improve retention?"*
- *"What makes our best customers different from average ones?"*
- *"Find the customer journey that converts best to loyalty"*

**Concepts & Interpretation**
- *"What does reorder rate mean for our business?"*
- *"Why does dept diversity predict loyalty?"*
- *"How is the loyalty score calculated?"*
""")


def _handle_quick_action(prompt: str):
    st.session_state.ui_history.append({
        "role": "user",
        "type": "text",
        "content": prompt
    })
    with st.spinner("Running..."):
        resp = call_agent(prompt)
    st.session_state.ui_history.append({
        "role": "assistant",
        "type": "text",
        "content": resp
    })
    st.rerun()
