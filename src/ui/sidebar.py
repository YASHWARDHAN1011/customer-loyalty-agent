"""
Sidebar UI

Renders the sidebar with API status, dataset stats, settings, and exports.
"""

import streamlit as st
from datetime import datetime

from src.config import API_KEYS, LLM_ARSENAL
from src.export.generator import generate_csv_export
from src.export.generator import generate_summary_report
from src.ui.onboarding import start_tour
from src.agent.memory import clear_memory
from src.agent.watches import (
    WATCHABLE_METRICS, load_watches, add_watch, remove_watch,
)
from src.agent.recipes import load_recipes, remove_recipe


def render_sidebar(features, orders, run_btn_callback):
    """
    Render the sidebar.
    Returns True if the run analysis button was clicked.
    """
    run_btn = False

    with st.sidebar:
        st.markdown("## 🛒 Loyalty Intelligence")
        st.divider()

        # API status section
        st.markdown("### 🔑 API Status")

        # Show each key's status
        if not API_KEYS:
            st.error("⚠️ No API keys found in .env")
            st.caption("Add GEMINI_KEY_1=your_key to .env file")
        else:
            current_idx = (
                st.session_state.model_idx % len(LLM_ARSENAL)
            )
            current_combo = LLM_ARSENAL[current_idx]

            st.success(f"✅ {len(API_KEYS)} key(s) loaded")

            used = min(st.session_state.model_idx, len(LLM_ARSENAL))
            remaining = len(LLM_ARSENAL) - used

            # 🔌 Model status — the metrics the chat used to show, moved here so
            # the chat-first page stays clean. The progress bar below is the only
            # other widget in this section, so the numbers aren't duplicated.
            m1, m2 = st.columns(2)
            m1.metric("Model", current_combo["model"].replace("gemini-", ""))
            m2.metric("Combos left", f"{remaining}/{len(LLM_ARSENAL)}")
            st.progress(used / len(LLM_ARSENAL), text="LLM quota used")

        st.divider()

        # Dataset stats
        st.markdown("### 📊 Dataset")
        st.metric("Users", f"{features['user_id'].nunique():,}")
        st.metric("Orders", f"{len(orders):,}")
        if "frequency" in features.columns:
            st.metric("Avg Orders/User", f"{features['frequency'].mean():.1f}")

        st.divider()

        # Analysis settings
        st.markdown("### ⚙️ Settings")

        # One weight slider per lever the dataset actually supports.
        from src.data.levers import LEVER_LABELS, renormalize_weights
        active = st.session_state.get('active_levers', [])
        raw_weights = {}
        for lv in active:
            raw_weights[lv] = st.slider(
                LEVER_LABELS.get(lv, lv), 0.0, 1.0,
                float(st.session_state['weights'].get(lv, 0.0)), 0.05,
            )
        total_w = sum(raw_weights.values())
        if abs(total_w - 1.0) > 0.01:
            st.caption(f"Weights sum to {total_w:.2f} — normalized to 1.0 at scoring time.")
        else:
            st.success(f"✅ Weights sum: {total_w:.2f}")

        top_pct = st.selectbox(
            "Power User %", [5, 10, 15, 20],
            index=[5, 10, 15, 20].index(st.session_state.top_pct)
        )
        
        if 'lookback' not in st.session_state:
            st.session_state.lookback = 4
            
        lookback = st.selectbox(
            "Happy Path Orders", [3, 4, 5],
            index=[3, 4, 5].index(st.session_state.lookback)
        )
        st.session_state.lookback = lookback

        # Update weights in session state (renormalized over active levers).
        st.session_state['weights'] = renormalize_weights(raw_weights, active)

        run_btn = st.button(
            "🚀 Run Full Analysis",
            use_container_width=True,
            type="primary"
        )
        if run_btn:
            run_btn_callback(top_pct)

        st.divider()

        # Analysis progress
        st.markdown("### 📈 Progress")
        progress_items = [
            ("Data Loaded", features is not None),
            ("Scored", st.session_state.get('scored_df') is not None),
            ("Segmented", st.session_state.get('power') is not None),
            ("Happy Path", 'paths' in st.session_state),
        ]
        for label, done in progress_items:
            if done:
                st.success(f"✅ {label}")
            else:
                st.info(f"⏳ {label}")

        st.divider()

        # Export buttons in sidebar
        st.markdown("### 📥 Export")

        csv_data = generate_csv_export()
        if csv_data:
            st.download_button(
                label="📊 Download Scored Users CSV",
                data=csv_data,
                file_name=f"loyalty_analysis_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True
            )

            report_text = generate_summary_report()
            st.download_button(
                label="📄 Download Summary Report",
                data=report_text.encode('utf-8'),
                file_name=f"loyalty_report_{datetime.now().strftime('%Y%m%d')}.md",
                mime="text/markdown",
                use_container_width=True
            )
        else:
            st.caption("Run analysis to enable exports")

        st.divider()
        c_replay, c_reset = st.columns(2)
        with c_replay:
            if st.button("🧭 Replay tour", use_container_width=True):
                start_tour()
                st.rerun()
        with c_reset:
            if st.button("🔄 Reset", use_container_width=True):
                keep = {'model_idx', 'features', 'full_data', 'weights', 'top_pct'}
                for k in list(st.session_state.keys()):
                    if k not in keep:
                        del st.session_state[k]
                st.rerun()

        if st.button("🧠 Forget what you remember", use_container_width=True):
            clear_memory()
            st.session_state.pop('_briefing_cache', None)
            st.toast("Cleared the agent's cross-session memory.")
            st.rerun()

        st.divider()
        st.markdown("### 🔔 Watches")
        st.caption("Get a banner when a metric crosses a line you set.")

        _metric_labels = {m["id"]: m["label"] for m in WATCHABLE_METRICS}
        with st.form("add_watch_form", clear_on_submit=True):
            metric_id = st.selectbox(
                "Metric",
                options=[m["id"] for m in WATCHABLE_METRICS],
                format_func=lambda mid: _metric_labels[mid],
            )
            direction = st.radio(
                "Alert when value is", options=["above", "below"], horizontal=True,
            )
            threshold = st.number_input("Threshold", value=0.0, step=1.0)
            if st.form_submit_button("➕ Add watch", use_container_width=True):
                try:
                    add_watch(metric_id, direction, threshold)
                    st.success("Watch added.")
                except ValueError as e:
                    st.error(str(e))

        _watches = load_watches()
        if _watches:
            for wch in _watches:
                label = _metric_labels.get(wch["metric"], wch["metric"])
                thr = wch["threshold"]
                thr_txt = int(thr) if float(thr).is_integer() else thr
                row, btn = st.columns([5, 1])
                row.markdown(f"**{label}** {wch['direction']} {thr_txt}")
                if btn.button("🗑", key=f"del_watch_{wch['id']}"):
                    remove_watch(wch["id"])
                    st.rerun()
        else:
            st.caption("No watches yet.")

        st.divider()
        st.markdown("### 🍳 Recipes")
        st.caption("Saved one-click questions. Run recomputes on current data.")
        _recipes = load_recipes()
        if _recipes:
            for rec in _recipes:
                row, runb, delb = st.columns([4, 1, 1])
                row.markdown(f"**{rec['name']}**")
                if runb.button("▶", key=f"run_recipe_{rec['id']}"):
                    st.session_state["run_recipe_id"] = rec["id"]
                    st.rerun()
                if delb.button("🗑", key=f"del_recipe_{rec['id']}"):
                    remove_recipe(rec["id"])
                    st.rerun()
        else:
            st.caption("No recipes yet.")

    return run_btn
