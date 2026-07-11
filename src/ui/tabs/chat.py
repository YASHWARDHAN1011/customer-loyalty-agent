"""Chat page — the chat-first landing surface (Phase 7).

Every message flows through the dispatch ladder (`src/agent/dispatch.py`). The 5
analytical tabs are retired; their figures live in the collapsible "Full numbers"
expander below the conversation.
"""

import streamlit as st

from src.config import API_KEYS
from src.ui.renderer import render_message, download_key
from src.agent.caller import probe_health
from src.agent.tool_loop import user_text, assistant_text
from src.agent.dispatch import dispatch
from src.agent.orchestrator import synthesize_goal
from src.agent.proactive import get_briefing
from src.ui.full_numbers import render_full_numbers
from src.utils.persistence import save_session, clear_session

_STARTERS = [
    "Score all customers and identify power users",
    "Who is at risk of churning? Use a 30-day threshold.",
    "Compare power users vs regular users",
    "Find the happy path to power user status",
]


@st.cache_data(ttl=120, show_spinner=False)
def _api_health():
    return probe_health()


def _render_api_banner():
    """Upfront banner when the LLM is unreachable, before a message is wasted."""
    if not API_KEYS:
        return
    try:
        status = _api_health()
    except Exception:
        return
    if status == "exhausted":
        st.error(
            "⚠️ **All Gemini API keys are out of quota right now**, so the chat "
            "can't answer. Free-tier quota resets at midnight US Pacific — or add "
            "a fresh key (`GEMINI_KEY_5=…` in `.env`, then restart). "
            "Get one at https://aistudio.google.com/apikey"
        )


def render_chat(features, orders):
    _render_api_banner()
    if not API_KEYS:
        st.error("⚠️ No API keys configured. Add GEMINI_KEY_1=your_key to your "
                 ".env file, then restart the app.")

    render_briefing()

    if not st.session_state.ui_history:
        _seed_welcome(features, orders)

    for msg in st.session_state.ui_history:
        render_message(msg)

    # Starter chips only while the user hasn't spoken yet.
    no_user_msgs = not any(m.get("role") == "user" for m in st.session_state.ui_history)
    if no_user_msgs:
        st.caption("Try one of these:")
        cols = st.columns(len(_STARTERS))
        for i, (col, starter) in enumerate(zip(cols, _STARTERS)):
            if col.button(starter, key=f"starter_{i}", use_container_width=True):
                _submit(starter)

    if prompt := st.chat_input("Ask anything, or give a goal…"):
        _submit(prompt)

    with st.expander("📊 Full numbers", expanded=False):
        render_full_numbers()

    _deliverables_panel()

    _, nc_col = st.columns([3, 1])
    with nc_col:
        if st.button("🗑️ New conversation", use_container_width=True):
            clear_session()
            st.session_state["ui_history"] = []
            st.session_state["chat_history"] = []
            st.rerun()


def _submit(prompt: str):
    """Route one message through the dispatch ladder and render the result."""
    st.session_state.ui_history.append(
        {"role": "user", "type": "text", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    start = len(st.session_state.ui_history)
    with st.status("🧠 Working…", expanded=True) as status:
        def on_step(reason, label):
            if reason:
                st.markdown(f"🧠 _{reason}_")
            if label:
                st.write(f"▶️ **{label}**")
        result = dispatch(prompt, on_step=on_step)
        status.update(label="Done", state="complete", expanded=False)

    if result.kind == "goal":
        # Inline the tools' output produced during the loop (charts/tables/text).
        for msg in st.session_state.ui_history[start:]:
            if msg.get("type") != "artifact":
                render_message(msg)
        summary = synthesize_goal(result.goal, result.history)
        if summary:
            st.session_state.ui_history.append(
                {"role": "assistant", "type": "text", "content": summary})
            # Continuity: neutral-shape turns so follow-ups have context.
            st.session_state.chat_history.append(user_text(result.goal))
            st.session_state.chat_history.append(assistant_text(summary))
    else:
        st.session_state.ui_history.append(
            {"role": "assistant", "type": "text", "content": result.text})

    save_session()
    st.rerun()


def _seed_welcome(features, orders):
    total_users = features["user_id"].nunique()
    total_orders_count = len(orders)
    extra_line = ""
    if "category_diversity" in features.columns:
        extra_line = (f"- **{features['category_diversity'].max():.0f}** product "
                      f"categories for your most varied customer\n")
    elif "dept_diversity" in features.columns:
        extra_line = (f"- **{features['dept_diversity'].max():.0f}** unique "
                      f"departments\n")
    welcome = (
        f"👋 Hello! I'm your Customer Loyalty Intelligence Agent.\n\n"
        f"I'm connected to your customer dataset:\n"
        f"- **{total_users:,}** customers\n"
        f"- **{total_orders_count:,}** orders\n"
        f"{extra_line}\n"
        f"Ask me anything, or pick a starter below. I can score customers, "
        f"compare segments, find the happy path to loyalty, flag churn risk, "
        f"and draft campaigns — every number computed from your real data."
    )
    st.session_state.ui_history.append(
        {"role": "assistant", "type": "text", "content": welcome})


def render_briefing():
    """Proactive briefing panel: deterministic signal cards + grounded narration.
    Best-effort — any failure silently skips the panel."""
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
                if st.button(sig["action_label"], key=f"briefing_{sig['id']}",
                             use_container_width=True):
                    _submit(sig["action_prompt"])


def _deliverables_panel():
    arts = st.session_state.get("artifacts", [])
    if not arts:
        return
    with st.expander("📦 Deliverables", expanded=False):
        st.caption("Every file the agent has produced this session.")
        for a in arts:
            st.download_button(label=a["label"], data=a["content"],
                               file_name=a["filename"], mime=a["mime"],
                               key=download_key())
