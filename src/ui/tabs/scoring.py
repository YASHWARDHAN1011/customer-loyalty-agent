"""
Scoring Page

Renders Tab 2: Loyalty Scoring.
"""

import streamlit as st
import altair as alt
import pandas as pd
import numpy as np


def render_scoring():
    st.header("Loyalty Scoring")
    st.caption(
        "Every customer scored 0-100 based on their "
        "behavioral patterns. Higher = more loyal."
    )

    if st.session_state.get('scored_df') is not None:
        scored = st.session_state['scored_df']
        cutoff = st.session_state['cutoff']
        power = st.session_state['power']
        top_pct_val = st.session_state.get('top_pct', 10)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric(
            "Avg Score",
            f"{scored['loyalty_score'].mean():.1f}/100"
        )
        c2.metric(
            "Median Score",
            f"{scored['loyalty_score'].median():.1f}/100"
        )
        c3.metric(
            "Score Cutoff",
            f"{cutoff:.1f}/100",
            help="Minimum score to be a power user"
        )
        c4.metric(
            f"Power Users",
            f"{len(power):,}",
            f"Top {top_pct_val}%"
        )

        st.divider()
        col_l, col_r = st.columns(2)

        with col_l:
            st.subheader("Score Distribution")
            st.caption(
                "Most customers cluster in the 30-50 range. "
                "Power users are in the top tail."
            )
            counts, bins_arr = np.histogram(
                scored['loyalty_score'],
                bins=10, range=(0, 100)
            )
            hist_df = pd.DataFrame({
                'Score': [
                    f"{int(bins_arr[i])}-{int(bins_arr[i+1])}"
                    for i in range(len(counts))
                ],
                'Customers': counts.tolist()
            })
            chart = (
                alt.Chart(hist_df)
                .mark_bar(
                    color=alt.Gradient(
                        gradient='linear',
                        stops=[
                            alt.GradientStop(color='#4f6aff', offset=0),
                            alt.GradientStop(color='#8b5cf6', offset=1),
                        ],
                        x1=0, x2=0, y1=1, y2=0,
                    ),
                    cornerRadiusTopLeft=4,
                    cornerRadiusTopRight=4,
                )
                .encode(
                    x=alt.X('Score:N', sort=None,
                             axis=alt.Axis(labelColor='rgba(255,255,255,0.35)',
                                           gridColor='rgba(255,255,255,0.05)',
                                           domainColor='rgba(255,255,255,0.08)')),
                    y=alt.Y('Customers:Q',
                             axis=alt.Axis(labelColor='rgba(255,255,255,0.35)',
                                           gridColor='rgba(255,255,255,0.05)',
                                           domainColor='rgba(255,255,255,0.08)')),
                    tooltip=['Score', 'Customers']
                )
                .properties(height=280)
                .configure_view(strokeWidth=0, fill='#050505')
            )
            st.altair_chart(chart, use_container_width=True)

        with col_r:
            st.subheader("Loyalty Tiers")
            st.caption(
                "5 tiers from Casual to Power User. "
                "Each tier has distinct behavioral characteristics."
            )
            scored_copy = scored.copy()
            scored_copy['Tier'] = pd.cut(
                scored_copy['loyalty_score'],
                bins=[0, 25, 50, 75, 90, 100],
                labels=[
                    'Casual', 'Active', 'Engaged',
                    'Loyal', 'Power User'
                ],
                include_lowest=True
            )
            tier_df = (
                scored_copy['Tier']
                .value_counts()
                .reset_index()
            )
            tier_df.columns = ['Tier', 'Customers']

            tier_order = [
                'Casual', 'Active', 'Engaged',
                'Loyal', 'Power User'
            ]
            tier_colors = [
                '#64748b', '#3b82f6', '#10b981',
                '#f59e0b', '#ef4444'
            ]

            chart = (
                alt.Chart(tier_df)
                .mark_bar(
                    cornerRadiusTopLeft=4,
                    cornerRadiusTopRight=4,
                )
                .encode(
                    x=alt.X(
                        'Tier:N',
                        sort=tier_order,
                        axis=alt.Axis(labelAngle=0, labelColor='rgba(255,255,255,0.35)',
                                      gridColor='rgba(255,255,255,0.05)',
                                      domainColor='rgba(255,255,255,0.08)')
                    ),
                    y=alt.Y('Customers:Q',
                             axis=alt.Axis(labelColor='rgba(255,255,255,0.35)',
                                           gridColor='rgba(255,255,255,0.05)',
                                           domainColor='rgba(255,255,255,0.08)')),
                    color=alt.Color(
                        'Tier:N',
                        sort=tier_order,
                        scale=alt.Scale(domain=tier_order, range=tier_colors),
                        legend=None
                    ),
                    tooltip=['Tier', 'Customers']
                )
                .properties(height=280)
                .configure_view(strokeWidth=0, fill='#050505')
            )
            st.altair_chart(chart, use_container_width=True)

        st.divider()
        st.subheader("Top 20 Highest-Scoring Customers")
        st.caption("Sample of your most loyal customers")
        top20 = scored.head(20)[[
            'user_id', 'loyalty_score', 'total_orders',
            'reorder_rate', 'dept_diversity', 'avg_basket_size'
        ]].copy()
        top20['reorder_rate'] = top20['reorder_rate'].map(
            '{:.1%}'.format
        )
        top20['loyalty_score'] = top20['loyalty_score'].map(
            '{:.1f}'.format
        )
        st.dataframe(top20, use_container_width=True,
                     hide_index=True)

    else:
        st.info(
            "👈 Set weights in the sidebar and click "
            "**Run Full Analysis** to score customers."
        )
