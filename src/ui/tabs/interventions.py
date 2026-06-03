"""
Interventions Page

Renders Tab 5: Interventions.
"""

import streamlit as st
from src.analysis.interventions import INTERVENTION_TEMPLATES, compute_intervention_gaps
from src.ui.renderer import render_intervention_card
from src.analysis.metrics import calculate_churn_risk


def render_interventions():
    st.header("Intervention Recommendations")
    st.caption(
        "Specific campaigns to convert regular users "
        "into power users, ranked by behavioral gap size."
    )

    if st.session_state.get('power') is not None:
        power = st.session_state['power']
        regular = st.session_state['regular']

        gaps = compute_intervention_gaps(power, regular)

        shown = 0
        for gap_pct, col, ru_avg, pu_avg in gaps:
            if shown >= 4 or col not in INTERVENTION_TEMPLATES:
                continue

            t = INTERVENTION_TEMPLATES[col]
            mid = (ru_avg + pu_avg) / 2

            # Estimate target users
            features_col = st.session_state['features'][col]
            count = int((features_col < mid).sum())

            render_intervention_card(t, gap_pct, ru_avg, pu_avg, mid, count)
            shown += 1

        # Churn risk section
        st.divider()
        st.subheader("⚠️ Churn Risk Analysis")
        st.caption(
            "Customers whose purchase gap exceeds the "
            "threshold are flagged as at-risk."
        )

        churn_col1, churn_col2 = st.columns([1, 3])
        with churn_col1:
            churn_days = st.slider(
                "At-risk threshold (days)",
                14, 90, 30, 7
            )

        features_data = st.session_state['features']
        power_user_ids = st.session_state.get('power_user_ids', set())
        
        at_risk, at_risk_power = calculate_churn_risk(features_data, power_user_ids, churn_days)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Total At-Risk",
            f"{len(at_risk):,}",
            f"{len(at_risk)/len(features_data)*100:.1f}%"
        )
        c2.metric(
            "At-Risk Power Users",
            f"{len(at_risk_power):,}",
            "High Priority"
        )
        c3.metric(
            "At-Risk Avg Gap",
            f"{at_risk['avg_days_between_orders'].mean():.0f} days"
        )
        c4.metric(
            "Revenue Risk",
            "High" if len(at_risk_power) > 1000 else "Medium"
        )

    else:
        st.info("👈 Run full analysis first.")
