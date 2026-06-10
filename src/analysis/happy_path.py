"""
Happy Path Analysis

Finds the most common behavioral sequences that lead
customers to become power users.
"""

import numpy as np


def get_happy_paths(full_data, power_user_ids,
                    lookback=4, top_n=5):
    """Find most common order sequences for power users."""
    early = full_data[
        full_data['order_number'] <= lookback
    ].copy()

    # Encode each order's set of departments as an integer bitmask
    # (one bit per department). A vectorized groupby.sum() over the
    # deduped rows is ~60x faster than a per-group Python
    # sorted/unique/join across the hundreds of thousands of
    # (user, order) groups. Each step is decoded back to readable
    # department names only for the handful of paths we return.
    depts = sorted(early['department'].unique())
    code = {d: i for i, d in enumerate(depts)}

    deduped = early[
        ['user_id', 'order_number', 'department']
    ].drop_duplicates()
    deduped['bit'] = np.left_shift(
        np.int64(1),
        deduped['department'].map(code).to_numpy().astype('int64'),
    )

    order_mask = (
        deduped
        .groupby(['user_id', 'order_number'], sort=False)['bit']
        .sum()
        .reset_index()
    )
    order_mask['step'] = (
        'O' + order_mask['order_number'].astype(str)
        + ':' + order_mask['bit'].astype(str)
    )

    def decode(step):
        onum, mask = step.split(':')
        mask = int(mask)
        names = ', '.join(
            d for i, d in enumerate(depts) if (mask >> i) & 1
        )
        return f"{onum}: {names}"

    all_paths = (
        order_mask
        .sort_values(['user_id', 'order_number'])
        .groupby('user_id')['step']
        .apply(tuple)
    )

    # Every complete path has exactly `lookback` steps (early was
    # capped at order_number <= lookback); truncating keeps prefixes
    # aligned.
    complete = all_paths[all_paths.apply(len) >= lookback]
    complete = complete.apply(lambda p: p[:lookback])

    pu_paths = complete[complete.index.isin(power_user_ids)]
    if len(pu_paths) == 0:
        return []

    top = pu_paths.value_counts().head(top_n)

    # For each prefix depth, how many of ALL complete users share
    # that prefix — one vectorized pass per depth instead of
    # rescanning every user path inside the funnel loop.
    prefix_counts = {}
    for depth in range(1, lookback + 1):
        prefix_counts[depth] = (
            complete.apply(lambda p: p[:depth])
            .value_counts()
            .to_dict()
        )

    results = []
    for path_tuple, pu_count in top.items():
        funnel = [
            {
                'step': decode(path_tuple[i]),
                'users': prefix_counts[i + 1].get(path_tuple[:i + 1], 0),
            }
            for i in range(len(path_tuple))
        ]
        results.append({
            'funnel': funnel,
            'power_users': int(pu_count),
        })
    return results
