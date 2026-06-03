import streamlit as st
st.set_page_config(page_title="Customer Loyalty", layout="wide", page_icon="🛒")

from src.ui.renderer import apply_theme
from src.data.loader import get_app_data
from src.ui.sidebar import render_sidebar
from src.analysis.scoring import score_users, get_power_users, get_thresholds
from src.config import MODEL_ARSENAL
from src.ui.tabs.overview import render_overview
from src.ui.tabs.scoring import render_scoring
from src.ui.tabs.segments import render_segments
from src.ui.tabs.happy_path import render_happy_path
from src.ui.tabs.interventions import render_interventions
from src.ui.tabs.chat import render_chat
from src.ui.onboarding import maybe_show_onboarding
from src.utils.persistence import load_session

apply_theme()

st.markdown("""
<div style="
    display:flex; align-items:center; gap:16px;
    padding: 1.2rem 0 1rem;
    margin-bottom: 0.5rem;
    border-bottom: 1px solid rgba(255,255,255,0.07);
">
    <div style="
        width:46px; height:46px; flex-shrink:0;
        background: linear-gradient(135deg, rgba(79,106,255,0.22), rgba(34,212,255,0.12));
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(79,106,255,0.30);
        border-radius:14px;
        display:flex; align-items:center; justify-content:center;
        font-size:1.4rem;
        box-shadow:
            0 4px 16px rgba(0,0,0,0.25),
            inset 0 1px 0 rgba(255,255,255,0.14),
            0 0 22px rgba(79,106,255,0.22);
    ">🛒</div>
    <div>
        <div style="
            font-size:1.38rem; font-weight:800;
            letter-spacing:-0.035em; line-height:1.1;
            color: rgba(255,255,255,0.92);
        ">Customer Loyalty Intelligence</div>
        <div style="color:rgba(255,255,255,0.28); font-size:0.78rem; font-weight:500; margin-top:3px; letter-spacing:0.02em;">
            Instacart dataset &nbsp;&middot;&nbsp; 206,209 customers &nbsp;&middot;&nbsp; 3.4M orders
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

orders, full_data, features = get_app_data()

defaults = {
    'features': features, 'full_data': full_data, 'chat_history': [], 'ui_history': [],
    'model_idx': 0, 'scored_df': None, 'power': None, 'regular': None, 'cutoff': None,
    'thresholds_df': None, 'power_user_ids': set(), 'top_pct': 10,
    'weights': {'total_orders': 0.30, 'reorder_rate': 0.25, 'dept_diversity': 0.20, 'avg_basket_size': 0.15, 'total_items': 0.10},
    'active_model': MODEL_ARSENAL[0]['label'] if MODEL_ARSENAL else 'None'
}
for k, v in defaults.items():
    if k not in st.session_state: st.session_state[k] = v

# Restore the saved chat once per browser session (Feature 4).
if 'session_loaded' not in st.session_state:
    saved_ui, saved_chat = load_session()
    if saved_ui is not None:
        st.session_state['ui_history'] = saved_ui
        st.session_state['chat_history'] = saved_chat
    st.session_state['session_loaded'] = True

def run_analysis(top_pct):
    with st.status("Running analysis…", expanded=True) as status:
        st.write(f"⚖️ Scoring all {len(features):,} users…")
        scored = score_users(features, st.session_state['weights'])

        st.write(f"🏆 Selecting top {top_pct}%…")
        power, regular, cutoff = get_power_users(scored, top_pct)

        st.write("📊 Computing segment thresholds…")
        thresholds = get_thresholds(power, regular)

        st.session_state.update({
            'scored_df': scored, 'power': power, 'regular': regular, 'cutoff': cutoff,
            'thresholds_df': thresholds, 'power_user_ids': set(power['user_id']),
            'top_pct': top_pct
        })
        status.update(
            label=f"Analysis complete — {len(power):,} power users found",
            state="complete", expanded=False,
        )
    st.success(f"✅ Analysis complete — Found **{len(power):,}** power users")

render_sidebar(features, orders, run_analysis)

maybe_show_onboarding(run_analysis)

tabs = st.tabs(["📊 Overview", "⚖️ Scoring", "👥 Segments", "🗺️ Happy Path", "🎯 Interventions", "🤖 AI Chat"])
with tabs[0]: render_overview(features, orders)
with tabs[1]: render_scoring()
with tabs[2]: render_segments()
with tabs[3]: render_happy_path(full_data)
with tabs[4]: render_interventions()
with tabs[5]: render_chat(features, orders)