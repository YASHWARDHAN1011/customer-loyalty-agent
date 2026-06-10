"""
Happy Path Page

Renders Tab 4: Happy Path.
"""

import streamlit as st
import altair as alt
import pandas as pd
from src.analysis.happy_path import get_happy_paths


def render_happy_path(full_data):
    st.header("Happy Path Analysis")
    st.caption(
        "The most common behavioral sequences that lead "
        "customers to become power users. "
        "Each path shows the funnel with drop-off at every stage."
    )

    if st.session_state.get('power_user_ids'):
        lookback = st.session_state.get('lookback', 4)
        
        col_l, col_r = st.columns([1, 3])
        with col_l:
            run_path_btn = st.button(
                "🔍 Find Happy Paths",
                use_container_width=True,
                type="primary"
            )
        with col_r:
            st.caption(
                f"Will trace first **{lookback}** orders "
                f"for **{len(st.session_state['power_user_ids']):,}** "
                f"power users (~10 seconds)"
            )

        if run_path_btn:
            with st.spinner("Analyzing customer journeys..."):
                paths = get_happy_paths(
                    full_data,
                    st.session_state['power_user_ids'],
                    lookback=lookback,
                    top_n=5
                )
                st.session_state['paths'] = paths

        if 'paths' in st.session_state:
            paths = st.session_state['paths']

            if paths:
                total_pu = len(
                    st.session_state['power_user_ids']
                )
                best_conv = max(
                    p['power_users'] for p in paths
                )
                c1, c2, c3 = st.columns(3)
                c1.metric("Paths Found", len(paths))
                c2.metric(
                    "Best Path Conversion",
                    f"{best_conv:,} power users"
                )
                c3.metric(
                    "Total Power Users",
                    f"{total_pu:,}"
                )

                st.divider()

                for i, path_data in enumerate(paths, 1):
                    funnel = path_data['funnel']
                    pu_count = path_data['power_users']
                    start = funnel[0]['users']
                    conv_rate = round(
                        pu_count / max(start, 1) * 100, 1
                    )

                    with st.expander(
                        f"Path {i} — "
                        f"{conv_rate}% conversion rate — "
                        f"{pu_count:,} power users",
                        expanded=(i == 1)
                    ):
                        steps = " → ".join(
                            [s['step'] for s in funnel]
                        )
                        st.code(steps)

                        funnel_df = pd.DataFrame([
                            {
                                'Stage': f"Order {j+1}",
                                'Users': s['users'],
                                'Drop': (
                                    round(
                                        (1 - s['users'] /
                                         max(funnel[0]['users'], 1)
                                         ) * 100, 1
                                    ) if j > 0 else 0
                                )
                            }
                            for j, s in enumerate(funnel)
                        ])
                        funnel_df.loc[len(funnel_df)] = {
                            'Stage': '👑 Power User',
                            'Users': pu_count,
                            'Drop': round(
                                (1 - pu_count /
                                 max(start, 1)) * 100, 1
                            )
                        }

                        chart = (
                            alt.Chart(funnel_df)
                            .mark_bar(color='#F4C430', cornerRadius=0, stroke='#00141F', strokeWidth=2)
                            .encode(
                                x=alt.X('Stage:N', sort=None,
                                         axis=alt.Axis(
                                             labelColor='#FEF0D5',
                                             gridColor='rgba(254,240,213,0.12)',
                                             domainColor='#FEF0D5',
                                         )),
                                y=alt.Y('Users:Q',
                                         axis=alt.Axis(
                                             labelColor='#FEF0D5',
                                             gridColor='rgba(254,240,213,0.12)',
                                             domainColor='#FEF0D5',
                                         )),
                                tooltip=['Stage', 'Users', 'Drop']
                            )
                            .properties(height=200)
                            .configure_view(strokeWidth=0, fill='#0A3D5C')
                        )
                        st.altair_chart(
                            chart, use_container_width=True
                        )

                        col1, col2 = st.columns(2)
                        with col1:
                            st.caption(
                                f"**Started:** {start:,} users"
                            )
                        with col2:
                            st.caption(
                                f"**Converted:** "
                                f"{pu_count:,} power users "
                                f"({conv_rate}%)"
                            )
            else:
                st.warning(
                    "No paths found. Try fewer lookback orders."
                )
        else:
            st.info("👆 Click **Find Happy Paths** to start.")
    else:
        st.info("👈 Run full analysis first.")
