"""
Metrics

Additional metric calculations and helpers.
Reserved for future metric computations.
"""


def calculate_churn_risk(features, power_user_ids, churn_days=30):
    """
    Identify customers at risk of churning.

    Args:
        features: User feature DataFrame.
        power_user_ids: Set of power user IDs.
        churn_days: Days between orders threshold for at-risk.

    Returns:
        Tuple of (at_risk_df, at_risk_power_df).
    """
    at_risk = features[
        features['avg_days_between_orders'] > churn_days
    ]
    at_risk_power = at_risk[
        at_risk['user_id'].isin(power_user_ids)
    ]
    return at_risk, at_risk_power
