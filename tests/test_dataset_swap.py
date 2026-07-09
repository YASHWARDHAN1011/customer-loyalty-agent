"""Unit tests for the active-dataset swap helper (no Streamlit, no network)."""
import os, sys, pandas as pd
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from src.ui.dataset import set_active_dataset

def _demo_state():
    # Simulate a session_state with stale analysis from a previous dataset.
    return {
        "weights": {"old_lever": 1.0},
        "scored_df": pd.DataFrame({"x": [1]}),
        "power": pd.DataFrame({"x": [1]}), "regular": pd.DataFrame({"x": [1]}),
        "cutoff": 5.0, "thresholds_df": pd.DataFrame({"x": [1]}),
        "power_user_ids": {1, 2, 3},
    }

def _dataset():
    features = pd.DataFrame({"user_id": [1, 2], "frequency": [3, 5], "monetary": [10, 20]})
    orders = pd.DataFrame({"customer_id": [1, 1, 2], "order_id": [1, 2, 3],
                           "order_date": pd.to_datetime(["2024-01-01"] * 3),
                           "order_amount": [10.0, 5.0, 20.0]})
    return orders, None, features, {"frequency": True, "monetary": True}, ["frequency", "monetary"]

def test_sets_dataset_keys_and_label():
    state = _demo_state()
    orders, items, features, available, active = _dataset()
    set_active_dataset(state, orders=orders, order_items=items, features=features,
                       available=available, active_levers=active,
                       label="sales.csv", source="upload")
    assert state["features"] is features
    assert state["full_data"] is items
    assert state["orders"] is orders
    assert state["available"] == available
    assert state["active_levers"] == active
    assert state["dataset_label"] == "sales.csv"
    assert state["dataset_source"] == "upload"
    assert state["dataset_counts"] == {"customers": 2, "orders": 3}

def test_resets_weights_to_new_active_levers():
    state = _demo_state()
    orders, items, features, available, active = _dataset()
    set_active_dataset(state, orders=orders, order_items=items, features=features,
                       available=available, active_levers=active,
                       label="x", source="upload")
    assert set(state["weights"]) == {"frequency", "monetary"}
    assert abs(sum(state["weights"].values()) - 1.0) < 1e-9

def test_clears_stale_analysis():
    state = _demo_state()
    orders, items, features, available, active = _dataset()
    set_active_dataset(state, orders=orders, order_items=items, features=features,
                       available=available, active_levers=active,
                       label="x", source="upload")
    for k in ("scored_df", "power", "regular", "cutoff", "thresholds_df"):
        assert state[k] is None, f"{k} not cleared"
    assert state["power_user_ids"] == set()

if __name__ == "__main__":
    test_sets_dataset_keys_and_label()
    test_resets_weights_to_new_active_levers()
    test_clears_stale_analysis()
    print("test_dataset_swap: OK")
