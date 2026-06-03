"""
Loyalty Scoring

Pure Python functions for scoring users and identifying power users.
No Streamlit dependency — can be tested independently.
"""

import pandas as pd


def score_users(features: pd.DataFrame, weights: dict):
    """
    Score every user 0-100 using weighted features.

    Steps:
    1. For each feature: cap at 95th percentile, normalize 0-100
    2. Multiply each normalized feature by its weight
    3. Sum weighted features = raw score
    4. Normalize raw scores to 0-100 final scale
    """
    df = features.copy()
    df['raw_score'] = 0.0

    for col, weight in weights.items():
        if col in df.columns:
            # Cap outliers at 95th percentile
            # This prevents extreme users from dominating
            cap = df[col].quantile(0.95)
            if cap > 0:
                # clip sets values above cap to exactly cap
                # Then normalize to 0-100
                normalized = (
                    df[col].clip(upper=cap) / cap
                ) * 100
            else:
                normalized = pd.Series(0.0, index=df.index)
            # Add weighted contribution
            df['raw_score'] += normalized * float(weight)

    # Final normalization to 0-100
    max_score = df['raw_score'].max()
    if max_score > 0:
        df['loyalty_score'] = (
            df['raw_score'] / max_score * 100
        ).round(2)
    else:
        df['loyalty_score'] = 0.0

    return df.sort_values('loyalty_score', ascending=False)


def get_power_users(scored_df, top_pct):
    """
    Split scored users into power users and regular users.
    quantile(1 - top_pct/100) finds the score cutoff.
    """
    cutoff = scored_df['loyalty_score'].quantile(
        1 - top_pct / 100
    )
    power = scored_df[
        scored_df['loyalty_score'] >= cutoff
    ].copy()
    regular = scored_df[
        scored_df['loyalty_score'] < cutoff
    ].copy()
    return power, regular, cutoff


def get_thresholds(power, regular):
    """Build feature comparison table between segments."""
    feature_cols = [
        'total_orders', 'avg_days_between_orders',
        'reorder_rate', 'dept_diversity',
        'avg_basket_size', 'total_items'
    ]
    rows = []
    for col in feature_cols:
        pu_avg = power[col].mean()
        ru_avg = regular[col].mean()
        ratio = pu_avg / max(ru_avg, 0.001)
        rows.append({
            'Feature': col.replace('_', ' ').title(),
            'Power User Avg': round(pu_avg, 2),
            'Regular User Avg': round(ru_avg, 2),
            'Power User Min': round(power[col].min(), 2),
            'Ratio': round(ratio, 1)
        })
    return pd.DataFrame(rows).sort_values(
        'Ratio', ascending=False
    )
