"""
What-If Simulation — campaign behavioral-lift projection.

Pure Python (no Streamlit, no LLM), per the src/analysis convention. Lifts a
single feature for regular (non-power) users and counts how many would cross the
baseline power-user cutoff, using a FROZEN baseline scaler so scores stay
comparable (see compute_scaler/apply_scoring in scoring.py). Every number is
deterministic; the LLM only narrates the result.
"""

from src.analysis.scoring import compute_scaler, apply_scoring, get_power_users

# The only simulatable levers: the 5 weighted scoring features. Higher = better
# for all of them. avg_days_between_orders is excluded (no scoring weight; it is
# the only "lower = better" feature and belongs to churn, not loyalty score).
LEVERS = ["total_orders", "reorder_rate", "dept_diversity",
          "avg_basket_size", "total_items"]


def simulate_campaign(features, weights, top_pct, feature, lift_pct):
    """Project a single-feature campaign lift on regular users.

    Returns a deterministic dict of conversions + key deltas. Assumes `feature`
    is a valid lever (validated at the tool layer) and `features` is one row per
    user with a `user_id` column.
    """
    # 1. Freeze the baseline scaler + cutoff.
    scaler = compute_scaler(features, weights)
    baseline = apply_scoring(features, weights, scaler)
    power, regular, cutoff = get_power_users(baseline, top_pct)

    total_users = len(features)
    baseline_power_count = len(power)
    regular_ids = set(regular["user_id"])

    # 2. Apply the lift to regular users only.
    lifted = features.copy()
    # Cast the target column to float so fractional lifts can be stored without
    # a LossySetitemError on int64 columns (pandas 2.x strict dtype enforcement).
    lifted[feature] = lifted[feature].astype(float)
    mask = lifted["user_id"].isin(regular_ids)
    before_avg = float(lifted.loc[mask, feature].mean()) if mask.any() else 0.0
    lifted.loc[mask, feature] = lifted.loc[mask, feature] * (1 + lift_pct / 100.0)
    if feature == "reorder_rate":
        lifted.loc[mask, feature] = lifted.loc[mask, feature].clip(upper=1.0)
    after_avg = float(lifted.loc[mask, feature].mean()) if mask.any() else 0.0

    # 3. Re-score with the FROZEN scaler so scores stay comparable.
    lifted_scored = apply_scoring(lifted, weights, scaler)

    # 4. Conversions = regulars whose new score clears the original cutoff.
    conv_mask = (lifted_scored["user_id"].isin(regular_ids)
                 & (lifted_scored["loyalty_score"] >= cutoff))
    conversions = int(conv_mask.sum())
    projected_power_count = baseline_power_count + conversions
    projected_power_pct = (round(projected_power_count / total_users * 100, 1)
                           if total_users else 0.0)

    return {
        "feature": feature,
        "lift_pct": lift_pct,
        "target_count": int(mask.sum()),
        "conversions": conversions,
        "baseline_power_count": baseline_power_count,
        "projected_power_count": projected_power_count,
        "projected_power_pct": projected_power_pct,
        "feature_avg_before": round(before_avg, 4),
        "feature_avg_after": round(after_avg, 4),
        "cutoff": round(float(cutoff), 2),
    }
