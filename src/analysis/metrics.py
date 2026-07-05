"""
Metrics

Additional metric calculations and helpers.
Reserved for future metric computations.
"""


def calculate_churn_risk(features, power_user_ids, churn_days=30):
    """Identify customers at risk of churning.

    Primary signal is `recency_days` (days since last order) — the RFM churn
    measure that works on any store. Falls back to `avg_days_between_orders`
    for legacy/Instacart frames that lack recency. Id column is whichever of
    `customer_id` / `user_id` is present.
    """
    id_col = "customer_id" if "customer_id" in features.columns else "user_id"
    signal = "recency_days" if "recency_days" in features.columns \
        else "avg_days_between_orders"
    at_risk = features[features[signal] > churn_days]
    at_risk_power = at_risk[at_risk[id_col].isin(power_user_ids)]
    return at_risk, at_risk_power
