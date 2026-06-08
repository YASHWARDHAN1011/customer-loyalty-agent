"""
Gemini Tools

Python functions that Gemini can call autonomously via function calling.

HOW IT WORKS:
1. Functions are registered in ALL_TOOLS list
2. SDK converts function signatures to JSON schema
3. Gemini reads schema to know what each tool does
4. When Gemini wants to call a tool, SDK runs the function
5. Return value goes back to Gemini as context
6. Gemini writes its response using that context

KEY RULES:
- Must have type hints on ALL parameters
- Must have a descriptive docstring (Gemini reads this)
- Must handle errors gracefully (return error dict)
- Can read/write st.session_state
- Return value must be JSON-serializable (dict/str/int)
"""

import streamlit as st
import pandas as pd
import numpy as np

from src.analysis.scoring import score_users, get_power_users, get_thresholds
from src.analysis.happy_path import get_happy_paths
from src.analysis.segmentation import compute_segment_gaps, build_comparison_data
from src.analysis.interventions import INTERVENTION_TEMPLATES, compute_intervention_gaps
from src.analysis.metrics import calculate_churn_risk

import uuid
from datetime import date
from src.agent.deliverables import (
    select_target_users, to_csv_bytes,
    campaign_emails_markdown, action_plan_markdown,
)


def run_scoring_analysis(top_percentile: int = 10) -> dict:
    """
    Scores all customers on a loyalty scale from 0 to 100
    using behavioral features and identifies power users.

    Use this when the user wants to:
    - Identify their most loyal customers
    - Score the customer base
    - Find power users
    - Start the analysis

    Args:
        top_percentile: Percentage of top users to classify
                        as power users. Default is 10.
    """
    features = st.session_state.get('features')
    if features is None:
        return {"error": "Data not loaded yet."}

    weights = st.session_state.get('weights', {
        'total_orders': 0.30,
        'reorder_rate': 0.25,
        'dept_diversity': 0.20,
        'avg_basket_size': 0.15,
        'total_items': 0.10
    })

    scored = score_users(features, weights)
    power, regular, cutoff = get_power_users(
        scored, top_percentile
    )
    thresholds = get_thresholds(power, regular)

    # Save all results to session state
    st.session_state['scored_df'] = scored
    st.session_state['power'] = power
    st.session_state['regular'] = regular
    st.session_state['cutoff'] = cutoff
    st.session_state['thresholds_df'] = thresholds
    st.session_state['power_user_ids'] = set(
        power['user_id'].tolist()
    )
    st.session_state['top_pct'] = top_percentile

    # Add score distribution chart to chat
    counts, bins_arr = np.histogram(
        scored['loyalty_score'], bins=10, range=(0, 100)
    )
    hist_df = pd.DataFrame({
        'Score Range': [
            f"{int(bins_arr[i])}-{int(bins_arr[i+1])}"
            for i in range(len(counts))
        ],
        'Users': counts.tolist()
    })
    st.session_state.ui_history.append({
        "role": "assistant",
        "type": "chart",
        "chart_type": "bar",
        "title": "⚖️ Loyalty Score Distribution",
        "data": hist_df,
        "x": "Score Range",
        "y": "Users"
    })

    return {
        "status": "success",
        "total_users": len(scored),
        "power_user_count": len(power),
        "power_user_percentage": round(
            len(power) / len(scored) * 100, 1
        ),
        "score_cutoff": round(float(cutoff), 2),
        "avg_score": round(
            float(scored['loyalty_score'].mean()), 1
        ),
        "top_differentiators": thresholds[
            ['Feature', 'Ratio']
        ].head(3).to_dict('records'),
        "instruction": (
            "Summarize these results in 3 bullet points. "
            "Include specific numbers. "
            "Then suggest running segmentation next."
        )
    }


def run_segmentation() -> dict:
    """
    Compares behavioral features between power users and
    regular users to show what makes power users different.

    Use this when user asks about:
    - Differences between customer segments
    - What power users do differently
    - Behavioral gaps between groups
    """
    power = st.session_state.get('power')
    regular = st.session_state.get('regular')

    if power is None:
        return {
            "error": "Run scoring analysis first.",
            "instruction": "Tell user to ask you to run scoring first."
        }

    gaps = compute_segment_gaps(power, regular)
    compare_data = build_comparison_data(gaps)

    # Add grouped bar chart to chat
    st.session_state.ui_history.append({
        "role": "assistant",
        "type": "chart",
        "chart_type": "grouped_bar",
        "title": "👥 Power Users vs Regular Users",
        "data": compare_data,
        "x": "Feature",
        "y": "Value",
        "color": "Segment"
    })

    return {
        "status": "success",
        "behavioral_gaps": gaps,
        "biggest_gap_feature": gaps[0]['feature'],
        "biggest_ratio": gaps[0]['ratio'],
        "instruction": (
            "Give exactly 3 bullet insights with specific numbers. "
            "Then suggest running happy path analysis."
        )
    }


def run_happy_path(lookback_orders: int = 4) -> dict:
    """
    Finds the most common behavioral sequences that lead
    customers to become power users. Shows funnel with
    drop-off at each stage of the customer journey.

    Use this when user asks about:
    - Customer journeys
    - What sequence of actions leads to loyalty
    - Happy path
    - Conversion funnel

    Args:
        lookback_orders: Number of orders to trace.
                         Use 3 for quick view, 5 for detail.
    """
    full_data = st.session_state.get('full_data')
    power_user_ids = st.session_state.get('power_user_ids')

    if full_data is None or power_user_ids is None:
        return {
            "error": "Run scoring analysis first.",
            "instruction": "Tell user to run scoring first."
        }

    paths = get_happy_paths(
        full_data, power_user_ids,
        lookback=lookback_orders, top_n=3
    )

    if not paths:
        return {"error": "No complete paths found."}

    st.session_state['paths'] = paths

    # Build summary for Gemini
    path_summaries = []
    for i, p in enumerate(paths, 1):
        steps = " → ".join([s['step'] for s in p['funnel']])
        start = p['funnel'][0]['users']
        end = p['funnel'][-1]['users']
        drop = round((1 - end/max(start, 1)) * 100, 1)
        conv = round(
            p['power_users'] / max(start, 1) * 100, 1
        )
        path_summaries.append({
            "path": i,
            "sequence": steps,
            "started": start,
            "completed": end,
            "overall_dropoff_pct": drop,
            "power_user_conversion_pct": conv,
            "became_power_users": p['power_users']
        })

    # Add text card to chat
    path_text = (
        f"### 🗺️ Top {len(paths)} Happy Paths "
        f"({lookback_orders} orders)\n\n"
    )
    for ps in path_summaries:
        path_text += (
            f"**Path {ps['path']}** — "
            f"{ps['power_user_conversion_pct']}% conversion:\n"
            f"`{ps['sequence']}`"
            f" → 👑 **{ps['became_power_users']:,}** "
            f"power users\n\n"
        )

    st.session_state.ui_history.append({
        "role": "assistant",
        "type": "text",
        "content": path_text
    })

    return {
        "status": "success",
        "paths": path_summaries,
        "instruction": (
            "Give 3 specific insights: "
            "1) where biggest drop-off is, "
            "2) most common starting departments, "
            "3) which path converts best and why. "
            "Then suggest generating campaign recommendations."
        )
    }


def get_current_stats() -> dict:
    """
    Returns a summary of what has been analyzed so far.

    Use this when user asks:
    - What do we know so far?
    - What has been analyzed?
    - Give me a summary
    - What are the current results?
    """
    features = st.session_state.get('features')
    scored = st.session_state.get('scored_df')
    power = st.session_state.get('power')

    if features is None:
        return {"status": "Data loading"}

    result = {
        "data_loaded": True,
        "total_users": int(features['user_id'].nunique()),
        "avg_orders_per_user": round(
            float(features['total_orders'].mean()), 1
        ),
        "avg_reorder_rate": round(
            float(features['reorder_rate'].mean()), 3
        ),
        "scoring_complete": scored is not None,
        "segmentation_complete": power is not None,
        "happy_path_complete": 'paths' in st.session_state
    }

    if power is not None:
        result["power_users"] = len(power)
        result["power_user_pct"] = round(
            len(power) / len(features) * 100, 1
        )

    return result


def run_interventions() -> dict:
    """
    Generates prioritized campaign recommendations to convert
    regular users into power users, ranked by behavioral gap size.

    Use this when the user asks about: campaigns, interventions,
    what to do next, how to convert regular users, marketing
    actions, what to improve, growth tactics.
    """
    power = st.session_state.get('power')
    regular = st.session_state.get('regular')

    if power is None:
        return {
            "error": "Run scoring analysis first.",
            "instruction": "Tell user to run scoring before interventions."
        }

    gaps = compute_intervention_gaps(power, regular)

    campaign_text = "### 🎯 Top Campaign Recommendations\n\n"
    results = []
    shown = 0

    for gap_pct, col, ru_avg, pu_avg in gaps:
        if shown >= 4 or col not in INTERVENTION_TEMPLATES:
            continue
        t = INTERVENTION_TEMPLATES[col]
        mid = (ru_avg + pu_avg) / 2
        features_col = st.session_state['features'][col]
        count = int((features_col < mid).sum())

        campaign_text += (
            f"**{t['icon']} {t['title']}** — {gap_pct:.0f}% gap\n"
            f"- {t['what'].format(ru=round(ru_avg, 2), pu=round(pu_avg, 2))}\n"
            f"- Target: {t['who'].format(mid=round(mid, 2), count=count, ru=round(ru_avg, 2), pu=round(pu_avg, 2))}\n"
            f"- Action: {t['action']}\n\n"
        )
        results.append({
            "feature": col,
            "gap_pct": round(gap_pct, 1),
            "regular_avg": round(ru_avg, 3),
            "power_avg": round(pu_avg, 3),
            "title": t['title'],
            "action": t['action']
        })
        shown += 1

    st.session_state.ui_history.append({
        "role": "assistant",
        "type": "text",
        "content": campaign_text
    })

    return {
        "status": "success",
        "campaigns_generated": shown,
        "top_campaigns": results,
        "instruction": (
            "Summarize the top 3 campaigns with specific numbers. "
            "Rank them by expected impact. "
            "Then suggest running churn risk analysis."
        )
    }


def analyze_churn_risk(churn_days: int = 30) -> dict:
    """
    Identifies customers at risk of churning based on how long
    since their last order. Separates at-risk power users
    (highest priority) from at-risk regular users.

    Use this when user asks about: churn, at-risk users,
    inactive customers, win-back, retention, who hasn't
    ordered recently, lapsing customers.

    Args:
        churn_days: Days without ordering to flag as at-risk.
                    Default is 30. Use 60 or 90 for stricter.
    """
    features = st.session_state.get('features')
    power_user_ids = st.session_state.get('power_user_ids', set())

    if features is None:
        return {"error": "Data not loaded yet."}

    at_risk, at_risk_power = calculate_churn_risk(
        features, power_user_ids, churn_days
    )

    total = len(features)
    summary_text = (
        f"### ⚠️ Churn Risk Analysis ({churn_days}-day threshold)\n\n"
        f"- **{len(at_risk):,}** customers at risk "
        f"({len(at_risk)/total*100:.1f}% of all users)\n"
        f"- **{len(at_risk_power):,}** are power users "
        f"(high-value churn risk)\n"
        f"- At-risk avg gap: "
        f"**{at_risk['avg_days_between_orders'].mean():.0f} days** "
        f"between orders\n"
    )

    st.session_state.ui_history.append({
        "role": "assistant",
        "type": "text",
        "content": summary_text
    })

    return {
        "status": "success",
        "threshold_days": churn_days,
        "total_at_risk": len(at_risk),
        "at_risk_pct": round(len(at_risk) / total * 100, 1),
        "at_risk_power_users": len(at_risk_power),
        "at_risk_avg_gap_days": round(
            float(at_risk['avg_days_between_orders'].mean()), 1
        ),
        "instruction": (
            "Give 2 insights: how urgent is the power-user churn risk, "
            "and what win-back action should they take immediately. "
            "Be specific with numbers."
        )
    }


def get_user_profile(user_id: int) -> dict:
    """
    Returns the full behavioral profile for a specific customer,
    including their loyalty score and segment (power/regular).

    Use this when user asks about a specific user ID, wants to
    understand an individual customer, or says things like
    'show me user 12345' or 'tell me about customer X'.

    Args:
        user_id: The customer's integer user_id.
    """
    features = st.session_state.get('features')
    if features is None:
        return {"error": "Data not loaded yet."}

    row = features[features['user_id'] == user_id]
    if row.empty:
        return {"error": f"User {user_id} not found in dataset."}

    row = row.iloc[0]
    scored = st.session_state.get('scored_df')
    power_user_ids = st.session_state.get('power_user_ids', set())

    profile = {
        "user_id": int(user_id),
        "total_orders": int(row['total_orders']),
        "avg_days_between_orders": round(float(row['avg_days_between_orders']), 1),
        "reorder_rate": round(float(row['reorder_rate']), 3),
        "dept_diversity": int(row['dept_diversity']),
        "avg_basket_size": round(float(row['avg_basket_size']), 1),
        "total_items": int(row['total_items']),
        "segment": "Power User" if user_id in power_user_ids else "Regular User"
    }

    if scored is not None:
        score_row = scored[scored['user_id'] == user_id]
        if not score_row.empty:
            profile["loyalty_score"] = round(
                float(score_row.iloc[0]['loyalty_score']), 1
            )

    import pandas as pd
    profile_df = pd.DataFrame([{
        "Field": k.replace('_', ' ').title(),
        "Value": str(v)
    } for k, v in profile.items()])

    st.session_state.ui_history.append({
        "role": "assistant",
        "type": "table",
        "title": f"👤 User {user_id} Profile",
        "data": profile_df
    })

    return {
        "status": "success",
        "profile": profile,
        "instruction": (
            "Interpret this user's profile in 2-3 sentences. "
            "Highlight their strongest and weakest loyalty signals. "
            "Suggest one specific action to improve their engagement."
        )
    }


def search_users(
    min_orders: int = None,
    max_orders: int = None,
    min_reorder_rate: float = None,
    max_reorder_rate: float = None,
    segment: str = None,
    limit: int = 10
) -> dict:
    """
    Finds customers matching specific behavioral criteria.

    Use this when user asks to find or filter customers by:
    - number of orders (e.g., 'users with more than 20 orders')
    - reorder rate (e.g., 'users with reorder rate above 0.7')
    - segment (e.g., 'show me some power users' or 'regular users')
    - combinations of the above

    Args:
        min_orders: Minimum total orders (inclusive).
        max_orders: Maximum total orders (inclusive).
        min_reorder_rate: Minimum reorder rate 0.0–1.0.
        max_reorder_rate: Maximum reorder rate 0.0–1.0.
        segment: 'power' or 'regular' to filter by segment.
        limit: Max users to return (default 10, max 50).
    """
    features = st.session_state.get('features')
    if features is None:
        return {"error": "Data not loaded yet."}

    scored = st.session_state.get('scored_df')
    power_user_ids = st.session_state.get('power_user_ids', set())

    df = features.copy()
    if scored is not None:
        df = df.merge(
            scored[['user_id', 'loyalty_score']], on='user_id', how='left'
        )

    if min_orders is not None:
        df = df[df['total_orders'] >= min_orders]
    if max_orders is not None:
        df = df[df['total_orders'] <= max_orders]
    if min_reorder_rate is not None:
        df = df[df['reorder_rate'] >= min_reorder_rate]
    if max_reorder_rate is not None:
        df = df[df['reorder_rate'] <= max_reorder_rate]
    if segment is not None:
        seg_lower = segment.lower()
        if 'power' in seg_lower:
            df = df[df['user_id'].isin(power_user_ids)]
        elif 'regular' in seg_lower:
            df = df[~df['user_id'].isin(power_user_ids)]

    limit = min(int(limit), 50)
    result = df.head(limit).copy()

    if result.empty:
        return {
            "status": "no_results",
            "instruction": "Tell user no customers matched their filters."
        }

    result['segment'] = result['user_id'].apply(
        lambda uid: 'Power User' if uid in power_user_ids else 'Regular User'
    )

    display_cols = ['user_id', 'total_orders', 'reorder_rate',
                    'dept_diversity', 'avg_basket_size', 'segment']
    if 'loyalty_score' in result.columns:
        display_cols.insert(-1, 'loyalty_score')

    import pandas as pd
    display_df = result[display_cols].round(3).reset_index(drop=True)

    st.session_state.ui_history.append({
        "role": "assistant",
        "type": "table",
        "title": f"🔍 Found {len(df):,} matching users (showing {len(result)})",
        "data": display_df
    })

    return {
        "status": "success",
        "total_matching": len(df),
        "showing": len(result),
        "avg_orders": round(float(df['total_orders'].mean()), 1),
        "avg_reorder_rate": round(float(df['reorder_rate'].mean()), 3),
        "instruction": (
            "Summarize who these users are in 1-2 sentences. "
            "Note any interesting patterns in the results."
        )
    }


def _add_artifact(filename: str, mime: str, content, label: str) -> str:
    """Store a downloadable artifact in session_state and append a chat entry."""
    art_id = uuid.uuid4().hex[:8]
    art = {
        "id": art_id, "filename": filename,
        "mime": mime, "content": content, "label": label,
    }
    st.session_state.setdefault('artifacts', []).append(art)
    st.session_state.ui_history.append({
        "role": "assistant", "type": "artifact",
        "filename": filename, "mime": mime,
        "content": content, "label": label, "artifact_id": art_id,
    })
    return art_id


def export_target_list(
    segment: str = None,
    min_orders: int = None,
    churn_days: int = None,
    limit: int = 500,
) -> dict:
    """
    Exports a downloadable CSV of the exact customers to target for a campaign.

    Use this when the user wants a list/export/file of users to contact, a
    target list for a campaign, or to "pull the users" matching a segment or
    churn threshold.

    Args:
        segment: 'power' or 'regular' to restrict the list.
        min_orders: only include users with at least this many orders.
        churn_days: only include users whose avg days between orders >= this.
        limit: max rows in the CSV (default 500).
    """
    features = st.session_state.get('features')
    if features is None:
        return {"error": "Data not loaded yet."}

    scored = st.session_state.get('scored_df')
    power_ids = st.session_state.get('power_user_ids', set())

    target = select_target_users(
        features, scored, power_ids,
        segment=segment, min_orders=min_orders,
        churn_days=churn_days, limit=limit,
    )
    if target.empty:
        return {
            "status": "no_results",
            "instruction": "Tell the user no customers matched their criteria.",
        }

    _add_artifact(
        "target_list.csv", "text/csv", to_csv_bytes(target),
        f"🎯 Target list — {len(target):,} users",
    )
    return {
        "status": "success",
        "target_count": int(len(target)),
        "filename": "target_list.csv",
        "instruction": (
            "Tell the user their target-list CSV is ready to download and "
            "how many customers it contains."
        ),
    }


def draft_campaign_emails(segment: str = None) -> dict:
    """
    Writes downloadable campaign email drafts, personalized to the biggest
    behavioral gaps between power users and regular users.

    Use this when the user asks to draft/write emails, create campaign copy,
    or generate outreach messages.

    Args:
        segment: optional label noted in the brief (e.g. 'regular', 'power').
    """
    power = st.session_state.get('power')
    regular = st.session_state.get('regular')
    if power is None:
        return {
            "error": "Run scoring analysis first.",
            "instruction": "Tell the user to run scoring before drafting emails.",
        }

    gaps = compute_intervention_gaps(power, regular)
    md = campaign_emails_markdown(gaps, INTERVENTION_TEMPLATES)
    _add_artifact("campaign_emails.md", "text/markdown", md,
                  "✉️ Campaign email drafts")
    return {
        "status": "success",
        "filename": "campaign_emails.md",
        "instruction": (
            "Tell the user the email drafts are ready to download and name "
            "the top campaign they cover."
        ),
    }


def build_action_plan(churn_days: int = 30) -> dict:
    """
    Compiles a downloadable, prioritized retention action checklist combining
    the biggest behavioral gaps with the current churn-risk snapshot.

    Use this when the user wants a plan, a checklist, a to-do list, next steps,
    or "what should we do" as a deliverable.

    Args:
        churn_days: days-without-order threshold for the churn snapshot.
    """
    power = st.session_state.get('power')
    regular = st.session_state.get('regular')
    features = st.session_state.get('features')
    if power is None or features is None:
        return {
            "error": "Run scoring analysis first.",
            "instruction": "Tell the user to run scoring before the action plan.",
        }

    gaps = compute_intervention_gaps(power, regular)
    power_ids = st.session_state.get('power_user_ids', set())
    at_risk, at_risk_power = calculate_churn_risk(features, power_ids, churn_days)

    md = action_plan_markdown(
        gaps, INTERVENTION_TEMPLATES,
        at_risk_count=len(at_risk), at_risk_power=len(at_risk_power),
        date_str=date.today().isoformat(),
    )
    _add_artifact("action_plan.md", "text/markdown", md,
                  "✅ Retention action plan")
    return {
        "status": "success",
        "filename": "action_plan.md",
        "at_risk": int(len(at_risk)),
        "instruction": (
            "Tell the user the action plan is ready to download and summarize "
            "its single highest-priority item."
        ),
    }


# All tools Gemini can call
ALL_TOOLS = [
    run_scoring_analysis,
    run_segmentation,
    run_happy_path,
    run_interventions,
    analyze_churn_risk,
    get_user_profile,
    search_users,
    get_current_stats,
    export_target_list,
    draft_campaign_emails,
    build_action_plan,
]
