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


from src.data.levers import LEVER_LABELS


def template_for(col, templates=None):
    """Return a campaign template for a feature column.

    Uses the hand-authored INTERVENTION_TEMPLATES when one exists, else a generic
    template built from the lever's label so campaigns/emails/action-plans work on
    any dataset's levers (not just the Instacart columns).
    """
    templates = INTERVENTION_TEMPLATES if templates is None else templates
    if col in templates:
        return templates[col]
    label = LEVER_LABELS.get(col, col.replace("_", " ").title())
    low = label.lower()
    return {
        "icon": "📈",
        "title": f"Grow {label}",
        "what": f"Power users show markedly higher {low} than regular customers.",
        "who": "Target {count} regular users below the midpoint.",
        "action": f"Run a campaign that nudges customers to increase their {low}.",
        "message": f"A small lift in {low} moves regulars toward power-user value.",
    }


_PREFERRED_COLS = [
    'total_orders', 'reorder_rate',
    'dept_diversity', 'avg_basket_size',
    'avg_days_between_orders',
]

_NON_FEATURE = {'user_id', 'customer_id', 'loyalty_score', 'raw_score',
                'segment', 'recency_days'}


def compute_intervention_gaps(power, regular):
    """Calculate behavioral gaps for intervention targeting.

    Column-agnostic: prefers the hand-curated Instacart column order when those
    columns exist, then falls back to any numeric feature present in both frames
    (skipping id / score / churn-direction columns). This lets the function work on
    any dataset's levers, not just the original Instacart ones.

    Returns sorted list of (gap_pct, col, ru_avg, pu_avg) tuples.
    """
    common = set(power.columns) & set(regular.columns)
    # Build candidate list: preferred first (in order), then remaining numerics.
    seen = set()
    candidates = []
    for col in _PREFERRED_COLS:
        if col in common:
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
        if ru_avg > 0.001:
            gap = ((pu_avg - ru_avg) / ru_avg) * 100
            gaps.append((gap, col, ru_avg, pu_avg))

    gaps.sort(reverse=True)
    return gaps
