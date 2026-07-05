"""
Chat Page

Renders Tab 6: AI Chat.
"""

import streamlit as st
from src.config import API_KEYS, LLM_ARSENAL
from src.ui.renderer import render_message, download_key
from src.agent.caller import call_agent, probe_health
from src.agent.router import route
from src.agent.orchestrator import run_reflexive, synthesize_goal
from src.agent.proactive import get_briefing
from src.utils.persistence import save_session, clear_session


@st.cache_data(ttl=120, show_spinner=False)
def _api_health():
    """Cached upfront health check (re-probes at most every 2 minutes)."""
    return probe_health()


def _render_api_banner():
    """Show an upfront banner when the chat can't reach the LLM, before the
    user wastes a message. Cached so it costs at most one ping every 2 min."""
    if not API_KEYS:
        return  # the no-keys error is already shown in render_chat below
    try:
        status = _api_health()
    except Exception:
        return  # never let the health check break the tab
    if status == "exhausted":
        st.error(
            "⚠️ **All Gemini API keys are out of quota right now**, so the chat "
            "can't answer. The analysis tabs, briefing and Watches still work. "
            "Free-tier quota resets at midnight US Pacific — or add a fresh key "
            "(`GEMINI_KEY_5=…` in `.env`, then restart). "
            "Get one at https://aistudio.google.com/apikey"
        )


def render_chat(features, orders):
    st.header("🤖 AI Analyst Chat")
    st.caption(
        "Gemini AI with function calling — it can run "
        "analysis tools, interpret results, and answer "
        "questions about your customers."
    )

    _render_api_banner()

    if not API_KEYS:
        st.error(
            "⚠️ No API keys configured. "
            "Add GEMINI_KEY_1=your_key to your .env file, "
            "then restart the app."
        )
    else:
        idx = st.session_state.model_idx % len(LLM_ARSENAL)
        active = LLM_ARSENAL[idx]

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
                st.session_state.model_idx, len(LLM_ARSENAL)
            )
            remaining = len(LLM_ARSENAL) - used
            st.metric(
                "Combos Remaining",
                f"{remaining}/{len(LLM_ARSENAL)}"
            )

    st.divider()

    render_briefing()

    _deliverables_panel()

    # New conversation — clears the saved session and resets the chat.
    _, nc_col = st.columns([3, 1])
    with nc_col:
        if st.button("🗑️ New conversation", use_container_width=True):
            clear_session()
            st.session_state['ui_history'] = []
            st.session_state['chat_history'] = []
            st.rerun()

    if not st.session_state.ui_history:
        total_users = features['user_id'].nunique()
        total_orders_count = len(orders)
        # Dataset-agnostic third stat: prefer the canonical category signal,
        # fall back to the legacy Instacart department count, else omit.
        extra_line = ""
        if 'category_diversity' in features.columns:
            extra_line = (f"- **{features['category_diversity'].max():.0f}** "
                          f"product categories for your most varied customer\n")
        elif 'dept_diversity' in features.columns:
            extra_line = (f"- **{features['dept_diversity'].max():.0f}** "
                          f"unique departments\n")
        welcome = (
            f"👋 Hello! I'm your Customer Loyalty Intelligence Agent.\n\n"
            f"I'm connected to your customer dataset:\n"
            f"- **{total_users:,}** customers\n"
            f"- **{total_orders_count:,}** orders\n"
            f"{extra_line}\n"
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
        "Ask anything, or give a goal... "
        "(e.g. 'Who are our power users?' or 'Build a retention plan')"
    ):
        st.session_state.ui_history.append({
            "role": "user",
            "type": "text",
            "content": prompt
        })

        with st.chat_message("user"):
            st.markdown(prompt)

        decision = route(prompt)
        if decision["mode"] == "goal":
            _run_goal_in_chat(decision["goal"] or prompt)
        else:
            with st.spinner("🧠 Agent thinking..."):
                response = call_agent(prompt)
            st.session_state.ui_history.append({
                "role": "assistant",
                "type": "text",
                "content": response
            })

        save_session()
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


def render_briefing():
    """Proactive Briefing panel: deterministic signal cards + grounded narration.

    Appears only once analysis has run. Best-effort — any failure silently
    skips the panel rather than crashing the chat tab.
    """
    try:
        briefing = get_briefing()
    except Exception:
        return

    if not briefing["ready"] or not briefing["signals"]:
        return

    with st.expander("💡 Today's Briefing", expanded=True):
        if briefing["narrative"]:
            st.markdown(briefing["narrative"])
            st.divider()

        signals = briefing["signals"]
        cols = st.columns(len(signals))
        for col, sig in zip(cols, signals):
            with col:
                st.markdown(f"#### {sig['icon']} {sig['headline']}")
                st.caption(sig["detail"])
                if st.button(
                    sig["action_label"],
                    key=f"briefing_{sig['id']}",
                    use_container_width=True,
                ):
                    _handle_quick_action(sig["action_prompt"])


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
    save_session()
    st.rerun()


def _run_goal_in_chat(goal: str):
    """Run the reflexive loop for a goal, live in the chat, then summarize.

    Mirrors the old Autopilot tab: shows 🧠 reason / ▶️ action per step, renders
    the tools' inline output, posts an executive summary into the conversation,
    and injects a synthetic turn into chat_history so follow-ups have context.
    """
    start = len(st.session_state.ui_history)

    with st.status("Thinking…", expanded=True) as status:
        def _on_step(reason, label):
            if reason:
                st.markdown(f"🧠 _{reason}_")
            if label:
                st.write(f"▶️ **{label}**")

        history = run_reflexive(goal, status_callback=_on_step)
        status.update(label="Goal complete", state="complete", expanded=False)

    # Inline analysis output produced by the tools (charts/tables/text only;
    # artifacts live in the deliverables panel).
    for msg in st.session_state.ui_history[start:]:
        if msg.get("type") != "artifact":
            render_message(msg)

    summary = synthesize_goal(goal, history)
    if summary:
        st.session_state.ui_history.append({
            "role": "assistant", "type": "text", "content": summary,
        })
        # Continuity: let later reactive follow-ups see what the agent did.
        st.session_state.chat_history.append({"role": "user", "parts": [goal]})
        st.session_state.chat_history.append({"role": "model", "parts": [summary]})


def _deliverables_panel():
    """List every artifact produced this session (moved from the Autopilot tab)."""
    arts = st.session_state.get('artifacts', [])
    if not arts:
        return
    with st.expander("📦 Deliverables", expanded=False):
        st.caption("Every file the agent has produced this session.")
        for a in arts:
            st.download_button(
                label=a['label'],
                data=a['content'],
                file_name=a['filename'],
                mime=a['mime'],
                key=download_key(),
            )
