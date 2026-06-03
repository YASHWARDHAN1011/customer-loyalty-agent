"""
Intervention Recommendations

Templates and logic for generating campaign recommendations
to convert regular users into power users.
"""


# Intervention templates — keyed by feature name
INTERVENTION_TEMPLATES = {
    'total_orders': {
        'icon': '🔁',
        'title': 'Drive Repeat Purchases',
        'what': 'Regular users average {ru:.0f} orders vs {pu:.0f} for power users',
        'who': 'Users with fewer than {mid:.0f} total orders ({count:,} users)',
        'action': 'Send personalized reorder reminder 7 days after last purchase',
        'message': '"Your usual items are waiting — reorder in one tap"',
        'metric': 'Target: increase avg orders from {ru:.0f} to {pu:.0f}',
        'color': '#3b82f6'
    },
    'reorder_rate': {
        'icon': '❤️',
        'title': 'Build Reorder Habits',
        'what': 'Regular users reorder {ru:.0%} of items vs {pu:.0%} for power users',
        'who': 'Users with reorder rate below {mid:.0%} ({count:,} users)',
        'action': 'Weekly "your favorites" reminder with one-click reorder',
        'message': '"You usually buy these — add them again?"',
        'metric': 'Target: increase reorder rate from {ru:.0%} to {pu:.0%}',
        'color': '#10b981'
    },
    'dept_diversity': {
        'icon': '🛒',
        'title': 'Expand Category Exploration',
        'what': 'Regular users shop {ru:.0f} departments vs {pu:.0f} for power users',
        'who': 'Users shopping fewer than {mid:.0f} departments ({count:,} users)',
        'action': 'Cross-category discovery offer after 3rd order',
        'message': '"Customers like you also love our [dept] section"',
        'metric': 'Target: increase dept diversity from {ru:.0f} to {pu:.0f}',
        'color': '#f59e0b'
    },
    'avg_basket_size': {
        'icon': '📦',
        'title': 'Grow Basket Size',
        'what': 'Regular users buy {ru:.0f} items/order vs {pu:.0f} for power users',
        'who': 'Users averaging fewer than {mid:.0f} items/order ({count:,} users)',
        'action': '"Complete your cart" suggestions at checkout',
        'message': '"Add 2 more items to qualify for free delivery"',
        'metric': 'Target: increase basket from {ru:.0f} to {pu:.0f} items',
        'color': '#8b5cf6'
    },
    'avg_days_between_orders': {
        'icon': '⚡',
        'title': 'Increase Order Frequency',
        'what': 'Regular users order every {ru:.0f} days vs {pu:.0f} for power users',
        'who': 'Users ordering less than every {mid:.0f} days ({count:,} users)',
        'action': 'Mid-week "running low?" push notification',
        'message': '"It\'s been a while — your essentials might be running low"',
        'metric': 'Target: reduce order gap from {ru:.0f} to {pu:.0f} days',
        'color': '#ef4444'
    }
}


def compute_intervention_gaps(power, regular):
    """
    Calculate behavioral gaps for intervention targeting.

    Returns sorted list of (gap_pct, col, ru_avg, pu_avg) tuples.
    """
    gaps = []
    for col in [
        'total_orders', 'reorder_rate',
        'dept_diversity', 'avg_basket_size',
        'avg_days_between_orders'
    ]:
        pu_avg = float(power[col].mean())
        ru_avg = float(regular[col].mean())
        if ru_avg > 0.001:
            gap = ((pu_avg - ru_avg) / ru_avg) * 100
            gaps.append((gap, col, ru_avg, pu_avg))

    gaps.sort(reverse=True)
    return gaps
