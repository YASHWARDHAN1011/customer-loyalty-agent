"""
Loyalty Scoring

Pure Python functions for scoring users and identifying power users.
No Streamlit dependency — can be tested independently.
"""

import pandas as pd


def compute_scaler(features: pd.DataFrame, weights: dict):
    """Fit the scoring scaler from a baseline population.

    Returns {"caps": {col: 95th-pctile cap}, "max_raw": float} — the parameters
    that make loyalty scores comparable. Freeze these to score a hypothetical
    population on the same yardstick (see src/analysis/simulation.py).
    """
    df = features.copy()
    caps = {}
    raw = pd.Series(0.0, index=df.index)
    for col, weight in weights.items():
        if col in df.columns:
            cap = df[col].quantile(0.95)
            caps[col] = cap
            if cap > 0:
                normalized = (df[col].clip(upper=cap) / cap) * 100
            else:
                normalized = pd.Series(0.0, index=df.index)
            raw += normalized * float(weight)
    return {"caps": caps, "max_raw": float(raw.max())}


def apply_scoring(features: pd.DataFrame, weights: dict, scaler: dict):
    """Score users with a *provided* scaler (caps + max_raw).

    Same math as the original score_users, but using the frozen scaler instead of
    deriving it from `features`. Returns the df with `raw_score`/`loyalty_score`,
    sorted by loyalty_score descending.
    """
    df = features.copy()
    df['raw_score'] = 0.0
    caps = scaler.get("caps", {})
    for col, weight in weights.items():
        if col in df.columns:
            cap = caps.get(col)
            if cap is None:
                cap = df[col].quantile(0.95)
            if cap and cap > 0:
                normalized = (df[col].clip(upper=cap) / cap) * 100
            else:
                normalized = pd.Series(0.0, index=df.index)
            df['raw_score'] += normalized * float(weight)

    max_raw = scaler.get("max_raw")
    if max_raw and max_raw > 0:
        df['loyalty_score'] = (df['raw_score'] / max_raw * 100).round(2)
    else:
        df['loyalty_score'] = 0.0

    return df.sort_values('loyalty_score', ascending=False)


def score_users(features: pd.DataFrame, weights: dict):
    """Score every user 0-100 using weighted features.

    Thin wrapper: fit the scaler from this population, then apply it. Behavior is
    identical to the original single-function implementation.
    """
    scaler = compute_scaler(features, weights)
    return apply_scoring(features, weights, scaler)


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


def get_thresholds(power, regular, feature_cols=None):
    """Build a feature-comparison table between segments.

    `feature_cols` defaults to whatever numeric feature columns both frames
    share (minus id/score columns), so it works on ANY dataset's levers.
    Columns not present in the frames are skipped rather than raising.
    """
    if feature_cols is None:
        skip = {"user_id", "customer_id", "raw_score", "loyalty_score"}
        feature_cols = [c for c in power.columns
                        if c not in skip and c in regular.columns]
    rows = []
    for col in feature_cols:
        if col not in power.columns or col not in regular.columns:
            continue
        pu_avg = power[col].mean()
        ru_avg = regular[col].mean()
        ratio = pu_avg / max(ru_avg, 0.001)
        rows.append({
            'Feature': col.replace('_', ' ').title(),
            'Power User Avg': round(pu_avg, 2),
            'Regular User Avg': round(ru_avg, 2),
            'Power User Min': round(power[col].min(), 2),
            'Ratio': round(ratio, 1),
        })
    return pd.DataFrame(rows).sort_values('Ratio', ascending=False)
