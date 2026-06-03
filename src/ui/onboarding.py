"""
Onboarding wizard.

A 3-step welcome dialog shown the first time someone opens the app. The
final step kicks off an initial analysis so newcomers land on a populated
dashboard instead of an empty one.

"Seen" state is persisted to .app_state/onboarding.json so the tour does not
reappear on every visit; a sidebar "Replay tour" button can re-trigger it.
"""

import json
import os

import streamlit as st

STATE_DIR = '.app_state'
ONBOARDING_FILE = os.path.join(STATE_DIR, 'onboarding.json')
TOTAL_STEPS = 3
DEFAULT_TOP_PCT = 10


# ── First-run flag persistence ────────────────────────────────────────────────

def _has_seen_tour() -> bool:
    try:
        with open(ONBOARDING_FILE, 'r', encoding='utf-8') as f:
            return bool(json.load(f).get('seen'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False


def _mark_tour_seen() -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(ONBOARDING_FILE, 'w', encoding='utf-8') as f:
        json.dump({'seen': True}, f)


def start_tour() -> None:
    """Force the tour open (used by the sidebar 'Replay tour' button)."""
    st.session_state['show_onboarding'] = True
    st.session_state['onboarding_step'] = 0


# ── The dialog ────────────────────────────────────────────────────────────────

def _finish() -> None:
    """Close the tour and request the deferred initial analysis."""
    _mark_tour_seen()
    st.session_state['show_onboarding'] = False
    st.session_state['onboarding_run'] = True
    st.rerun()


@st.dialog("👋 Welcome to Customer Loyalty Intelligence")
def _tour() -> None:
    step = st.session_state.get('onboarding_step', 0)
    st.progress((step + 1) / TOTAL_STEPS, text=f"Step {step + 1} of {TOTAL_STEPS}")

    if step == 0:
        st.markdown(
            "#### What this is\n"
            "An analytics workspace that scores **206,209 Instacart customers** "
            "on loyalty, segments your **power users**, and surfaces the campaigns "
            "most likely to grow them.\n\n"
            "You can also just **ask the AI chat** questions in plain English."
        )
    elif step == 1:
        st.markdown(
            "#### How scoring works\n"
            "Each customer gets a **0–100 loyalty score** from a weighted blend of "
            "six behaviors — total orders, reorder rate, department diversity, "
            "basket size, total items, and order frequency.\n\n"
            "The top *N%* by score are your **power users**; everyone else is "
            "**regular**. You control the weights and the cutoff in the sidebar."
        )
    else:
        st.markdown(
            "#### Let's run your first analysis\n"
            f"We'll score everyone and pick the **top {DEFAULT_TOP_PCT}%** to get "
            "you started. You can re-run with different settings any time from the "
            "sidebar.\n\n"
            "Click **Finish & analyze** below."
        )

    st.write("")
    back_col, next_col = st.columns(2)

    with back_col:
        if step > 0 and st.button("← Back", use_container_width=True, key="onb_back"):
            st.session_state['onboarding_step'] = step - 1
            st.rerun()

    with next_col:
        if step < TOTAL_STEPS - 1:
            if st.button("Next →", use_container_width=True, type="primary", key="onb_next"):
                st.session_state['onboarding_step'] = step + 1
                st.rerun()
        else:
            if st.button("✅ Finish & analyze", use_container_width=True, type="primary", key="onb_finish"):
                _finish()

    if st.button("Skip tour", use_container_width=True, key="onb_skip"):
        _mark_tour_seen()
        st.session_state['show_onboarding'] = False
        st.rerun()


# ── Entry point called from app.py ────────────────────────────────────────────

def maybe_show_onboarding(run_analysis) -> None:
    """Open the tour on first visit; run the deferred initial analysis after it.

    `run_analysis(top_pct)` is the app's analysis callback. The initial run is
    deferred to the main script body (not inside the dialog) so its status log
    renders on the dashboard rather than inside the closing modal.
    """
    if 'show_onboarding' not in st.session_state:
        st.session_state['show_onboarding'] = not _has_seen_tour()
        st.session_state['onboarding_step'] = 0

    if st.session_state.get('show_onboarding'):
        _tour()

    if st.session_state.pop('onboarding_run', False):
        run_analysis(DEFAULT_TOP_PCT)
