"""
Segments Page

Renders Tab 3: Power User Profile (Segments).
"""

import streamlit as st
import altair as alt
import pandas as pd
from src.ui.renderer import color_ratio


def render_segments():
    st.header("Power User Profile")
    st.caption(
        "Comparing what power users do vs regular customers "
        "to identify the behavioral targets."
    )

    if st.session_state.get('power') is not None:
        power = st.session_state['power']
        regular = st.session_state['regular']
        thresholds_df = st.session_state['thresholds_df']
        top_pct_val = st.session_state.get('top_pct', 10)

        c1, c2 = st.columns(2)
        c1.metric(
            f"Power Users (Top {top_pct_val}%)",
            f"{len(power):,}"
        )
        c2.metric(
            "Regular Users",
            f"{len(regular):,}"
        )

        st.divider()
        st.subheader("Behavioral Thresholds")
        st.caption(
            "The minimum values a user must reach in each "
            "feature to qualify as a power user. "
            "These become your campaign targets."
        )

        styled = thresholds_df.style.map(
            color_ratio, subset=['Ratio']
        )
        st.dataframe(
            styled, use_container_width=True,
            hide_index=True
        )

        st.divider()
        col_l, col_r = st.columns(2)

        with col_l:
            st.subheader("Feature Comparison")
            compare_data = []
            for col in [
                'total_orders', 'reorder_rate',
                'dept_diversity', 'avg_basket_size'
            ]:
                compare_data.append({
                    'Feature': col.replace('_', ' ').title(),
                    'Value': round(float(power[col].mean()), 3),
                    'Segment': '⭐ Power User'
                })
                compare_data.append({
                    'Feature': col.replace('_', ' ').title(),
                    'Value': round(float(regular[col].mean()), 3),
                    'Segment': '👤 Regular User'
                })

            chart = (
                alt.Chart(pd.DataFrame(compare_data))
                .mark_bar(
                    cornerRadiusTopLeft=4,
                    cornerRadiusTopRight=4,
                )
                .encode(
                    x=alt.X('Feature:N',
                            axis=alt.Axis(
                                labelAngle=-20, title='',
                                labelColor='rgba(255,255,255,0.35)',
                                gridColor='rgba(255,255,255,0.05)',
                                domainColor='rgba(255,255,255,0.08)',
                            )),
                    y=alt.Y('Value:Q',
                             axis=alt.Axis(
                                 labelColor='rgba(255,255,255,0.35)',
                                 gridColor='rgba(255,255,255,0.05)',
                                 domainColor='rgba(255,255,255,0.08)',
                             )),
                    xOffset='Segment:N',
                    color=alt.Color(
                        'Segment:N',
                        scale=alt.Scale(range=['#4f6aff', '#1e3a5f']),
                        legend=alt.Legend(labelColor='rgba(255,255,255,0.35)', titleColor='rgba(255,255,255,0.35)'),
                    ),
                    tooltip=['Feature', 'Segment', 'Value']
                )
                .properties(height=300)
                .configure_view(strokeWidth=0, fill='#050505')
            )
            st.altair_chart(chart, use_container_width=True)

        with col_r:
            st.subheader("Score Distribution by Segment")
            segment_data = pd.DataFrame({
                'Segment': ['⭐ Power Users', '👤 Regular Users'],
                'Count': [len(power), len(regular)]
            })
            segment_data['Percentage'] = (
                segment_data['Count'] /
                segment_data['Count'].sum() * 100
            ).round(1)

            donut = (
                alt.Chart(segment_data)
                .mark_arc(innerRadius=70, outerRadius=120)
                .encode(
                    theta=alt.Theta('Count:Q'),
                    color=alt.Color(
                        'Segment:N',
                        scale=alt.Scale(range=['#4f6aff', '#1e3a5f']),
                        legend=alt.Legend(
                            orient='bottom',
                            labelColor='rgba(255,255,255,0.35)',
                            titleColor='rgba(255,255,255,0.35)',
                        ),
                    ),
                    tooltip=['Segment', 'Count', 'Percentage']
                )
                .properties(height=300)
                .configure_view(strokeWidth=0, fill='#050505')
            )
            st.altair_chart(donut, use_container_width=True)

    else:
        st.info("👈 Run analysis first.")
