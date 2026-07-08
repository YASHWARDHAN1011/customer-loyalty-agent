"""
Deliverables — pure builders for downloadable campaign artifacts.

No Streamlit imports: every function takes plain DataFrames / dicts so it can
be unit-tested in isolation. The tool wrappers in tools.py read session_state
and call these.
"""

import pandas as pd
from src.agent import tool_context as tc


def select_target_users(features, scored_df, power_user_ids,
                        segment=None, min_orders=None,
                        churn_days=None, limit=500):
    """Filter the feature matrix into a target list DataFrame.

    Column-agnostic: filters use the dataset's resolved order-count / churn
    columns and the export includes whatever features are present.
    """
    df = features.copy()
    if scored_df is not None:
        df = df.merge(
            scored_df[['user_id', 'loyalty_score']], on='user_id', how='left'
        )
    order_col = tc.order_count_col(df)
    if min_orders is not None and order_col:
        df = df[df[order_col] >= min_orders]
    gap_col = tc.churn_gap_col(df)
    if churn_days is not None and gap_col:
        df = df[df[gap_col] >= churn_days]
    if segment is not None:
        s = str(segment).lower()
        if 'power' in s:
            df = df[df['user_id'].isin(power_user_ids)]
        elif 'regular' in s:
            df = df[~df['user_id'].isin(power_user_ids)]

    df = df.copy()
    df['segment'] = df['user_id'].apply(
        lambda u: 'Power User' if u in power_user_ids else 'Regular User'
    )
    feat_cols = [c for c in tc.present_feature_cols(df) if c != 'segment']
    cols = ['user_id'] + [c for c in feat_cols if c != 'user_id'] + ['segment']
    return df[cols].head(int(limit)).round(3).reset_index(drop=True)


def to_csv_bytes(df) -> bytes:
    """Serialize a DataFrame to UTF-8 CSV bytes for st.download_button."""
    return df.to_csv(index=False).encode('utf-8')


def campaign_emails_markdown(gaps, templates, max_campaigns=4) -> str:
    """Build a markdown file of ready-to-send email drafts.

    gaps: list of (gap_pct, col, ru_avg, pu_avg) from compute_intervention_gaps.
    Deterministic: numbers are interpolated from the data, no LLM call.
    """
    out = "# Campaign Email Drafts\n\n"
    shown = 0
    for gap_pct, col, ru_avg, pu_avg in gaps:
        if shown >= max_campaigns or col not in templates:
            continue
        t = templates[col]
        out += f"## {t['title']}  ({gap_pct:.0f}% gap)\n\n"
        out += f"**Subject:** {t['title']} — a little something for you\n\n"
        out += (
            "Hi there,\n\n"
            f"We noticed an opportunity to help you get more from every order. "
            f"Our most loyal shoppers average {pu_avg:.2f} here, versus "
            f"{ru_avg:.2f} for most customers. "
            f"Here's an idea: {t['action']}.\n\n"
            f"_{t['message']}_\n\n"
            "Warmly,\nThe Team\n\n---\n\n"
        )
        shown += 1
    if shown == 0:
        out += "_No campaigns available — run scoring + segmentation first._\n"
    return out


def action_plan_markdown(gaps, templates, at_risk_count,
                         at_risk_power, date_str, max_items=5) -> str:
    """Build a dated, prioritized retention action checklist (markdown)."""
    out = f"# Retention Action Plan — {date_str}\n\n"
    out += (
        f"**Churn snapshot:** {at_risk_count:,} customers at risk "
        f"({at_risk_power:,} of them power users).\n\n"
        "## Prioritized actions\n\n"
    )
    shown = 0
    for gap_pct, col, ru_avg, pu_avg in gaps:
        if shown >= max_items or col not in templates:
            continue
        t = templates[col]
        out += (
            f"- [ ] **{t['title']}** — close the {gap_pct:.0f}% gap. "
            f"{t['action']} "
            f"(regulars avg {ru_avg:.2f} vs power {pu_avg:.2f}).\n"
        )
        shown += 1
    if shown == 0:
        out += "- [ ] Run scoring + segmentation to populate recommendations.\n"
    return out
