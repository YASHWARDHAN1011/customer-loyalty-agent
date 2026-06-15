"""
Autopilot Page

Renders Tab 7. The user states a goal; the reflexive controller runs one step,
reads the numbers, and decides the next move — showing its reasoning live — then
synthesizes a summary. All deliverables produced (this run or in chat) are listed
with download buttons.
"""

import streamlit as st

from src.ui.renderer import render_message, download_key
from src.agent.orchestrator import run_reflexive, synthesize_goal


_EXAMPLES = [
    "Build a full retention strategy for at-risk power users",
    "Find and target my churning customers",
    "Score customers and draft win-back campaigns",
]


def render_autopilot(features, orders):
    st.header("🤖 Autopilot")
    st.caption(
        "Give the agent a goal. It runs one analysis step, reads the numbers, "
        "and decides the next move live — adapting as it learns — then hands you "
        "downloadable deliverables."
    )

    cols = st.columns(len(_EXAMPLES))
    for i, ex in enumerate(_EXAMPLES):
        if cols[i].button(ex, key=f"ap_ex_{i}", use_container_width=True):
            st.session_state['autopilot_goal'] = ex

    goal = st.text_input(
        "Goal",
        value=st.session_state.get('autopilot_goal', ''),
        placeholder="e.g. Build a retention plan for churning power users",
    )

    if st.button("🚀 Run goal", type="primary"):
        if not goal.strip():
            st.warning("Enter a goal first.")
        else:
            _run_goal(goal.strip())

    _deliverables_panel()


def _run_goal(goal: str):
    start = len(st.session_state.ui_history)

    # Closed loop — show the agent think (reason) then act (label) per step.
    with st.status("Thinking…", expanded=True) as status:
        def _on_step(reason, label):
            if reason:
                st.markdown(f"🧠 _{reason}_")
            if label:
                st.write(f"▶️ **{label}**")

        history = run_reflexive(goal, status_callback=_on_step)
        status.update(label="Goal complete", state="complete", expanded=False)

    # Inline analysis output produced by the tools (charts/tables/text only;
    # artifacts are shown in the deliverables panel below).
    for msg in st.session_state.ui_history[start:]:
        if msg.get("type") != "artifact":
            render_message(msg)

    # Executive summary over what actually ran.
    summary = synthesize_goal(goal, history)
    if summary:
        st.markdown("### 📋 Executive summary")
        st.markdown(summary)


def _deliverables_panel():
    arts = st.session_state.get('artifacts', [])
    if not arts:
        return
    st.divider()
    st.subheader("📦 Deliverables")
    st.caption("Every file the agent has produced this session.")
    for a in arts:
        st.download_button(
            label=a['label'],
            data=a['content'],
            file_name=a['filename'],
            mime=a['mime'],
            key=download_key(),
        )
