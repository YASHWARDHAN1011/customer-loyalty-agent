"""The single active-dataset swap seam.

Both an upload and "back to demo" call `set_active_dataset` to replace the
dataset the whole app reads from `session_state`. Pure: it operates on any
dict-like state (Streamlit's `session_state` or a plain dict in tests) and
imports no Streamlit. It resets the scoring weights to the new dataset's active
levers and clears any stale analysis results so a switch never mixes datasets.
"""

from src.data.levers import default_weights

# Analysis outputs that belong to the *previous* dataset and must be dropped.
_STALE_ANALYSIS = ("scored_df", "power", "regular", "cutoff", "thresholds_df")


def set_active_dataset(state, *, orders, order_items, features, available,
                       active_levers, label, source):
    """Replace the active dataset in `state`.

    `state` is a dict-like (session_state). `source` is "demo" or "upload".
    Writes the dataset keys + label/source/counts, resets `weights` to the new
    active levers, and clears stale analysis so the next `run_analysis` recomputes.
    """
    state["orders"] = orders
    state["full_data"] = order_items
    state["features"] = features
    state["available"] = available
    state["active_levers"] = active_levers
    state["dataset_label"] = label
    state["dataset_source"] = source
    state["dataset_counts"] = {"customers": int(len(features)),
                               "orders": int(len(orders))}
    state["weights"] = default_weights(active_levers)
    for k in _STALE_ANALYSIS:
        state[k] = None
    state["power_user_ids"] = set()
