"""
Overview Page

Renders Tab 1: Dataset Overview.
"""

import streamlit as st
import altair as alt
import pandas as pd


def render_overview(features, orders):
    st.header("Dataset Overview")
    st.caption(
        "Understanding the raw behavioral patterns "
        "across all customers"
    )

    # Key metrics row
    c1, c2, c3, c4 = st.columns(4)
    c1.metric(
        "Total Customers",
        f"{features['user_id'].nunique():,}"
    )
    c2.metric("Total Orders", f"{len(orders):,}")
    c3.metric(
        "Avg Orders/Customer",
        f"{features['total_orders'].mean():.1f}"
    )
    c4.metric(
        "Avg Reorder Rate",
        f"{features['reorder_rate'].mean():.1%}"
    )

    st.divider()
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Order Frequency Distribution")
        st.caption(
            "Most customers order fewer than 10 times. "
            "Power users are in the 20+ range."
        )
        bins = [0, 5, 10, 15, 20, 30, 50, 100]
        labels = [
            '1-5','6-10','11-15','16-20',
            '21-30','31-50','50+'
        ]
        tmp = pd.cut(
            features['total_orders'],
            bins=bins, labels=labels
        ).value_counts().reset_index()
        tmp.columns = ['Range', 'Customers']
        tmp = tmp.sort_values('Range')

        chart = (
            alt.Chart(tmp)
            .mark_bar(color='#FF5C5C', cornerRadius=0, stroke='#0A0A0A', strokeWidth=2)
            .encode(
                x=alt.X('Range:N', sort=labels,
                        axis=alt.Axis(labelAngle=0, labelColor='#F5F2E6',
                                      gridColor='rgba(245,242,230,0.12)',
                                      domainColor='#F5F2E6')),
                y=alt.Y('Customers:Q',
                        axis=alt.Axis(labelColor='#F5F2E6',
                                      gridColor='rgba(245,242,230,0.12)',
                                      domainColor='#F5F2E6')),
                tooltip=['Range', 'Customers']
            )
            .properties(height=280)
            .configure_view(strokeWidth=0, fill='#1F1F23')
        )
        st.altair_chart(chart, use_container_width=True)

    with col_r:
        st.subheader("Behavioral Feature Averages")
        st.caption(
            "Average values across all customers. "
            "Power users will score much higher on all metrics."
        )
        display_features = {
            'total_orders': 'Total Orders',
            'reorder_rate': 'Reorder Rate',
            'dept_diversity': 'Dept Diversity',
            'avg_basket_size': 'Basket Size'
        }
        avg_vals = {
            v: features[k].mean()
            for k, v in display_features.items()
        }
        avg_df = pd.DataFrame({
            'Feature': list(avg_vals.keys()),
            'Average': [round(v, 3) for v in avg_vals.values()]
        })
        chart = (
            alt.Chart(avg_df)
            .mark_bar(color='#3DDC84', cornerRadius=0, stroke='#0A0A0A', strokeWidth=2)
            .encode(
                x=alt.X('Feature:N',
                        axis=alt.Axis(labelAngle=-20, labelColor='#F5F2E6',
                                      gridColor='rgba(245,242,230,0.12)',
                                      domainColor='#F5F2E6')),
                y=alt.Y('Average:Q',
                        axis=alt.Axis(labelColor='#F5F2E6',
                                      gridColor='rgba(245,242,230,0.12)',
                                      domainColor='#F5F2E6')),
                tooltip=['Feature', 'Average']
            )
            .properties(height=280)
            .configure_view(strokeWidth=0, fill='#1F1F23')
        )
        st.altair_chart(chart, use_container_width=True)

    st.divider()
    st.subheader("Feature Statistics Table")
    st.caption(
        "Key statistical measures for every feature. "
        "Note the large difference between mean and max "
        "— indicating outlier customers."
    )
    show_cols = [
        'total_orders', 'avg_days_between_orders',
        'reorder_rate', 'dept_diversity',
        'avg_basket_size', 'total_items'
    ]
    stats_df = features[show_cols].describe().round(2)
    st.dataframe(stats_df, use_container_width=True)
