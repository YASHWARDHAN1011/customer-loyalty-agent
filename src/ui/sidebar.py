"""
Sidebar UI

Renders the sidebar with API status, dataset stats, settings, and exports.
"""

import streamlit as st
from datetime import datetime

from src.config import API_KEYS, MODEL_ARSENAL
from src.export.generator import generate_csv_export
from src.export.generator import generate_summary_report


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
                st.session_state.model_idx % len(MODEL_ARSENAL)
            )
            current_combo = MODEL_ARSENAL[current_idx]

            st.success(f"✅ {len(API_KEYS)} key(s) loaded")
            st.caption(
                f"Active: {current_combo['model']} "
                f"(combo {current_idx + 1}/{len(MODEL_ARSENAL)})"
            )

            used = min(st.session_state.model_idx, len(MODEL_ARSENAL))
            remaining = len(MODEL_ARSENAL) - used
            st.progress(
                used / len(MODEL_ARSENAL),
                text=f"{remaining}/{len(MODEL_ARSENAL)} combos remaining"
            )

        st.divider()

        # Dataset stats
        st.markdown("### 📊 Dataset")
        st.metric("Users", f"{features['user_id'].nunique():,}")
        st.metric("Orders", f"{len(orders):,}")
        st.metric(
            "Avg Orders/User",
            f"{features['total_orders'].mean():.1f}"
        )

        st.divider()

        # Analysis settings
        st.markdown("### ⚙️ Settings")

        # Sliders for feature weights
        w_orders = st.slider("Total Orders", 0.0, 1.0, st.session_state.weights['total_orders'], 0.05)
        w_reorder = st.slider("Reorder Rate", 0.0, 1.0, st.session_state.weights['reorder_rate'], 0.05)
        w_diversity = st.slider("Dept Diversity", 0.0, 1.0, st.session_state.weights['dept_diversity'], 0.05)
        w_basket = st.slider("Basket Size", 0.0, 1.0, st.session_state.weights['avg_basket_size'], 0.05)
        w_items = st.slider("Total Items", 0.0, 1.0, st.session_state.weights['total_items'], 0.05)

        total_w = w_orders + w_reorder + w_diversity + w_basket + w_items
        if abs(total_w - 1.0) > 0.01:
            st.warning(f"Weights sum to {total_w:.2f} (ideally 1.0)")
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

        # Update weights in session state
        st.session_state['weights'] = {
            'total_orders': w_orders,
            'reorder_rate': w_reorder,
            'dept_diversity': w_diversity,
            'avg_basket_size': w_basket,
            'total_items': w_items
        }

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
        if st.button("🔄 Reset", use_container_width=True):
            keep = {'model_idx', 'features', 'full_data', 'weights', 'top_pct'}
            for k in list(st.session_state.keys()):
                if k not in keep:
                    del st.session_state[k]
            st.rerun()

    return run_btn
