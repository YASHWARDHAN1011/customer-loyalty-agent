"""
Segmentation Analysis

Compares behavioral features between power users and regular users.
Used by the run_segmentation agent tool.
"""

import pandas as pd

_PREFERRED_COLS = [
    'total_orders', 'reorder_rate', 'dept_diversity', 'avg_basket_size',
    'frequency', 'monetary', 'avg_order_value', 'tenure_days',
]

_NON_FEATURE = {'user_id', 'customer_id', 'loyalty_score', 'raw_score', 'segment'}


def compute_segment_gaps(power, regular):
    """
    Compute behavioral gaps between power and regular users.

    Column-agnostic: compares whatever numeric features are present in both
    frames (preferring the curated order), so it works on any dataset's levers
    — not just the original Instacart columns. Returns a list of gap dicts
    sorted by ratio (biggest gap first).
    """
    common = set(power.columns) & set(regular.columns)
    seen = set()
    candidates = []
    for col in _PREFERRED_COLS:
        if col in common and col not in _NON_FEATURE:
            candidates.append(col)
            seen.add(col)
    for col in power.columns:
        if col in common and col not in seen and col not in _NON_FEATURE:
            try:
                power[col].mean()  # numeric check
                candidates.append(col)
            except TypeError:
                pass

    gaps = []
    for col in candidates:
        try:
            pu_avg = float(power[col].mean())
            ru_avg = float(regular[col].mean())
        except (TypeError, ValueError):
            continue
        ratio = pu_avg / max(ru_avg, 0.001)
        gaps.append({
            'feature': col.replace('_', ' ').title(),
            'power_user_avg': round(pu_avg, 3),
            'regular_user_avg': round(ru_avg, 3),
            'ratio': round(ratio, 1)
        })

    gaps.sort(key=lambda x: x['ratio'], reverse=True)
    return gaps


def build_comparison_data(gaps):
    """
    Build a DataFrame suitable for grouped bar chart visualization.
    """
    compare_data = []
    for g in gaps:
        compare_data.append({
            'Feature': g['feature'],
            'Value': g['power_user_avg'],
            'Segment': 'Power User'
        })
        compare_data.append({
            'Feature': g['feature'],
            'Value': g['regular_user_avg'],
            'Segment': 'Regular User'
        })
    return pd.DataFrame(compare_data)
