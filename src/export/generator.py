"""
CSV Export

Generates a downloadable CSV of scored users.
"""

import io
import pandas as pd
import streamlit as st


def generate_csv_export():
    """
    Generate downloadable CSV of all users with
    their loyalty scores, tiers, and features.

    Returns bytes that st.download_button can serve.
    io.BytesIO creates an in-memory file — no disk needed.
    """
    scored = st.session_state.get('scored_df')
    if scored is None:
        return None

    export_df = scored.copy()

    # Add human-readable tier labels
    # pd.cut divides continuous scores into named buckets
    export_df['loyalty_tier'] = pd.cut(
        export_df['loyalty_score'],
        bins=[0, 25, 50, 75, 90, 100],
        labels=[
            'Casual', 'Active', 'Engaged',
            'Loyal', 'Power User'
        ],
        include_lowest=True
    )

    # Add power user flag
    power_ids = st.session_state.get('power_user_ids', set())
    export_df['is_power_user'] = (
        export_df['user_id'].isin(power_ids)
    ).astype(int)

    # Fixed meta columns, then WHATEVER feature columns this dataset actually has
    # (labelled via feature_label) — so the export works on canonical RFM data as
    # well as the Instacart demo instead of KeyError-ing on hardcoded columns.
    from src.agent.tool_context import feature_label

    _META = {'user_id', 'customer_id', 'loyalty_score',
             'loyalty_tier', 'is_power_user'}
    feature_cols = [c for c in export_df.columns if c not in _META]

    final = pd.DataFrame({
        'Customer ID': export_df['user_id'],
        'Loyalty Score (0-100)': export_df['loyalty_score'],
        'Loyalty Tier': export_df['loyalty_tier'],
        'Is Power User (1=Yes)': export_df['is_power_user'],
    })
    for c in feature_cols:
        final[feature_label(c)] = export_df[c]

    # Convert to CSV bytes
    # io.StringIO is an in-memory string buffer
    # .encode('utf-8') converts string to bytes
    # Streamlit's download_button needs bytes
    buffer = io.StringIO()
    final.to_csv(buffer, index=False)
    return buffer.getvalue().encode('utf-8')
"""
Report Export

Generates a markdown text summary of the analysis findings.
"""

from datetime import datetime
import streamlit as st


def generate_summary_report():
    """
    Generate a text summary report of the analysis.
    Returns markdown string.
    """
    scored = st.session_state.get('scored_df')
    power = st.session_state.get('power')
    regular = st.session_state.get('regular')
    thresholds = st.session_state.get('thresholds_df')

    if scored is None:
        return "No analysis run yet."

    now = datetime.now().strftime("%B %d, %Y at %H:%M")
    dataset = st.session_state.get('dataset_label', 'Your dataset')

    report = f"""# Customer Loyalty Intelligence Report
**Generated:** {now}
**Dataset:** {dataset}

---

## Executive Summary

- **Total Customers Analyzed:** {len(scored):,}
- **Power Users Identified:** {len(power):,} ({len(power)/len(scored)*100:.1f}% of base)
- **Average Loyalty Score:** {scored['loyalty_score'].mean():.1f}/100
- **Score Threshold for Power Users:** {st.session_state.get('cutoff', 0):.1f}/100

---

## Power User Profile

Power users are the top {st.session_state.get('top_pct', 10)}% of customers by loyalty score.

| Metric | Power Users | Regular Users | Ratio |
|--------|-------------|---------------|-------|
"""

    if thresholds is not None:
        for _, row in thresholds.iterrows():
            report += (
                f"| {row['Feature']} | "
                f"{row['Power User Avg']} | "
                f"{row['Regular User Avg']} | "
                f"{row['Ratio']}x |\n"
            )

    report += """
---

## Key Findings

"""
    if thresholds is not None:
        top_3 = thresholds.head(3)
        for i, (_, row) in enumerate(top_3.iterrows(), 1):
            report += (
                f"{i}. **{row['Feature']}** is the "
                f"#{i} differentiator — power users have "
                f"**{row['Ratio']}x more** "
                f"({row['Power User Avg']} vs "
                f"{row['Regular User Avg']})\n\n"
            )

    # Recommended interventions — derived from the dataset's OWN biggest
    # power-vs-regular gaps (compute_intervention_gaps is column-agnostic and
    # template_for falls back to a generic template), so this section is
    # meaningful on any client's levers instead of hardcoded Instacart copy.
    report += "---\n\n## Recommended Interventions\n\n"
    recs = []
    if power is not None and regular is not None and len(power) and len(regular):
        from src.analysis.interventions import compute_intervention_gaps, template_for
        from src.agent.tool_context import feature_label
        for i, (gap, col, ru, pu) in enumerate(
                compute_intervention_gaps(power, regular)[:3], 1):
            tpl = template_for(col)
            recs.append(
                f"{i}. **{tpl['title']}** — {tpl['action']} "
                f"({feature_label(col)}: regulars {ru:.1f} vs power users "
                f"{pu:.1f}, a {gap:.0f}% gap)"
            )
    if recs:
        report += "\n\n".join(recs) + "\n"
    else:
        report += ("Run the analysis to surface the biggest behavioral gaps "
                   "between regular and power users.\n")
    report += "\n---\n\n*Generated by Customer Loyalty Intelligence Agent*\n"
    return report
