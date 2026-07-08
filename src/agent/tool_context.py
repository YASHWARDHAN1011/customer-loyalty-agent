# src/agent/tool_context.py
"""Column resolution for the agent tools.

Pure (no Streamlit). Tools call these instead of hardcoding Instacart column
names, so they read whatever features the loaded dataset actually has — the
"never malfunctions on a client's data" rule, applied at the tool layer.
"""

from src.data.levers import LEVER_LABELS

# Labels for non-lever columns the tools display (levers come from LEVER_LABELS).
_EXTRA_LABELS = {
    "recency_days": "Days Since Last Order",
    "avg_days_between_orders": "Avg Days Between Orders",
    "total_orders": "Total Orders",
    "total_items": "Total Items",
    "dept_diversity": "Department Diversity",
    "loyalty_score": "Loyalty Score",
}

_NON_FEATURE = {"user_id"}


def feature_label(col):
    """Human label for a feature column (levers first, then extras, then title-case)."""
    return (LEVER_LABELS.get(col) or _EXTRA_LABELS.get(col)
            or col.replace("_", " ").title())


def present_feature_cols(features):
    """Feature columns actually in the frame (drops user_id), preserving order."""
    return [c for c in features.columns if c not in _NON_FEATURE]


def order_count_col(features):
    """Column representing how many orders a customer placed, or None."""
    for c in ("total_orders", "frequency"):
        if c in features.columns:
            return c
    return None


def churn_gap_col(features):
    """Column a churn/recency filter should use (recency first), or None."""
    for c in ("recency_days", "avg_days_between_orders"):
        if c in features.columns:
            return c
    return None


def summary_stats(features, cols=None, max_cols=4):
    """Mean of up to max_cols present numeric feature columns -> {label: float}."""
    cols = cols if cols is not None else present_feature_cols(features)
    out = {}
    for c in cols:
        if len(out) >= max_cols:
            break
        if c in features.columns:
            try:
                out[feature_label(c)] = round(float(features[c].mean()), 3)
            except (TypeError, ValueError):
                pass
    return out
