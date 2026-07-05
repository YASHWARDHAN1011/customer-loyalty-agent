"""Loyalty scoring levers over the canonical FeatureMatrix.

A "lever" is a canonical feature where higher = more loyal, so it can carry a
scoring weight. recency_days and avg_days_between_orders are excluded — they are
"lower = better" churn signals, not loyalty levers (mirrors the old
simulation.LEVERS decision). Downstream reads the ACTIVE levers from the data's
availability map, never a hardcoded column list — that is the "never
malfunctions" mechanism at the scoring layer.
"""

from src.data.canonical import CORE_FEATURES, OPTIONAL_FEATURES  # noqa: F401

# Higher-is-better canonical features, in display order.
SCORING_LEVERS = [
    "frequency",
    "monetary",
    "avg_order_value",
    "tenure_days",
    "category_diversity",
    "avg_basket_size",
    "reorder_rate",
]

LEVER_LABELS = {
    "frequency": "Order Frequency",
    "monetary": "Total Spend",
    "avg_order_value": "Avg Order Value",
    "tenure_days": "Tenure",
    "category_diversity": "Category Diversity",
    "avg_basket_size": "Basket Size",
    "reorder_rate": "Reorder Rate",
}


def active_levers(matrix):
    """The SCORING_LEVERS the given FeatureMatrix can actually compute."""
    return [lv for lv in SCORING_LEVERS if matrix.is_available(lv)]


def default_weights(levers):
    """Equal weights over `levers`, summing to 1.0 (empty -> {})."""
    if not levers:
        return {}
    share = 1.0 / len(levers)
    return {lv: share for lv in levers}


def renormalize_weights(weights, levers):
    """Keep only weights for `levers` and rescale them to sum to 1.0.

    If none of the levers carry positive weight, fall back to equal weights so
    scoring never divides by zero or silently zeroes every score.
    """
    if not levers:
        return {}
    kept = {lv: float(weights.get(lv, 0.0)) for lv in levers}
    total = sum(kept.values())
    if total <= 0:
        return default_weights(levers)
    return {lv: w / total for lv, w in kept.items()}
