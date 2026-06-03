"""
Happy Path Analysis

Finds the most common behavioral sequences that lead
customers to become power users.
"""


def get_happy_paths(full_data, power_user_ids,
                    lookback=4, top_n=5):
    """Find most common order sequences for power users."""
    early = full_data[
        full_data['order_number'] <= lookback
    ].copy()

    order_dept = (
        early.groupby(['user_id', 'order_number'])['department']
        .apply(lambda x: ', '.join(sorted(x.unique())))
        .reset_index()
    )

    order_dept['step'] = (
        'O' + order_dept['order_number'].astype(str)
        + ': ' + order_dept['department']
    )

    all_paths = (
        order_dept
        .sort_values(['user_id', 'order_number'])
        .groupby('user_id')['step']
        .apply(list)
    )

    complete = all_paths[all_paths.apply(len) >= lookback]
    pu_paths = complete[complete.index.isin(power_user_ids)]

    if len(pu_paths) == 0:
        return []

    top = pu_paths.apply(tuple).value_counts().head(top_n)

    results = []
    for path_tuple, _ in top.items():
        funnel = []
        for i in range(len(path_tuple)):
            prefix = list(path_tuple[:i+1])
            users_here = sum(
                1 for p in complete
                if list(p)[:i+1] == prefix
            )
            funnel.append({
                'step': path_tuple[i],
                'users': users_here
            })
        pu_count = sum(
            1 for p in pu_paths
            if list(p)[:len(path_tuple)] == list(path_tuple)
        )
        results.append({
            'funnel': funnel,
            'power_users': pu_count
        })
    return results
