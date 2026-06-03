"""
Segmentation Analysis

Compares behavioral features between power users and regular users.
Used by the run_segmentation agent tool.
"""

import pandas as pd


def compute_segment_gaps(power, regular):
    """
    Compute behavioral gaps between power and regular users.

    Returns a list of gap dicts sorted by ratio (biggest gap first).
    """
    feature_cols = [
        'total_orders', 'reorder_rate',
        'dept_diversity', 'avg_basket_size'
    ]

    gaps = []
    for col in feature_cols:
        pu_avg = float(power[col].mean())
        ru_avg = float(regular[col].mean())
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
