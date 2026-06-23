"""Standalone tests for src/agent/watches.py. No network, no Streamlit."""
import os
import sys
import tempfile

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import watches as w

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def _snapshot():
    # 5 customers; 2 are "at risk" (avg_days_between_orders > 30): u1, u2.
    features = pd.DataFrame({
        "user_id": [1, 2, 3, 4, 5],
        "avg_days_between_orders": [40, 35, 10, 5, 20],
    })
    # power_user_ids = {1} -> 1 at-risk power user (u1).
    power = pd.DataFrame({
        "total_orders": [50.0], "reorder_rate": [0.8],
        "dept_diversity": [12.0], "avg_basket_size": [10.0],
    })
    regular = pd.DataFrame({
        "total_orders": [10.0], "reorder_rate": [0.4],
        "dept_diversity": [6.0], "avg_basket_size": [5.0],
    })
    return {
        "features": features, "power": power, "regular": regular,
        "power_user_ids": {1}, "cutoff": 0.62, "churn_days": 30,
    }


def main():
    snap = _snapshot()

    # --- registry shape ---
    ids = [m["id"] for m in w.WATCHABLE_METRICS]
    check("4 metrics registered", len(w.WATCHABLE_METRICS) == 4)
    check("churn_pct present", "churn_pct" in ids)
    check("at_risk_power present", "at_risk_power" in ids)
    check("power_cutoff present", "power_cutoff" in ids)
    check("top_segment_gap present", "top_segment_gap" in ids)

    # --- metric computations ---
    check("churn_pct = 40.0", abs(w.evaluate_metric("churn_pct", snap) - 40.0) < 1e-6)
    check("at_risk_power = 1", w.evaluate_metric("at_risk_power", snap) == 1.0)
    check("power_cutoff = 0.62", abs(w.evaluate_metric("power_cutoff", snap) - 0.62) < 1e-6)
    # gaps ratios: total_orders 5.0, reorder 2.0, dept 2.0, basket 2.0 -> max 5.0
    check("top_segment_gap = 5.0", abs(w.evaluate_metric("top_segment_gap", snap) - 5.0) < 1e-6)
    check("unknown metric -> None", w.evaluate_metric("nope", snap) is None)

    # --- None on empty/missing inputs ---
    empty = {"features": pd.DataFrame(), "power": None, "regular": None}
    check("churn_pct None on empty", w.evaluate_metric("churn_pct", empty) is None)
    check("at_risk_power None on empty", w.evaluate_metric("at_risk_power", empty) is None)
    check("power_cutoff None when absent", w.evaluate_metric("power_cutoff", {}) is None)
    check("top_segment_gap None when absent", w.evaluate_metric("top_segment_gap", empty) is None)

    # --- evaluate_watches: fire logic ---
    fire = w.evaluate_watches(
        [{"id": "a", "metric": "churn_pct", "direction": "above", "threshold": 15.0}], snap)
    check("above fires (40 > 15)", len(fire) == 1)
    check("fired carries current", abs(fire[0]["current"] - 40.0) < 1e-6)
    check("churn above -> error severity", fire[0]["severity"] == "error")
    check("message mentions label", "Churn risk" in fire[0]["message"])
    check("message mentions percent", "40%" in fire[0]["message"])

    no_fire = w.evaluate_watches(
        [{"id": "b", "metric": "churn_pct", "direction": "above", "threshold": 40.0}], snap)
    check("equality does NOT fire (40 > 40 false)", no_fire == [])

    below = w.evaluate_watches(
        [{"id": "c", "metric": "power_cutoff", "direction": "below", "threshold": 0.7}], snap)
    check("below fires (0.62 < 0.7)", len(below) == 1)
    check("non-error metric -> warning", below[0]["severity"] == "warning")

    # --- unavailable metric never fires ---
    none_fire = w.evaluate_watches(
        [{"id": "d", "metric": "churn_pct", "direction": "above", "threshold": 1.0}], empty)
    check("unavailable metric never fires", none_fire == [])

    # --- ordering preserved ---
    multi = w.evaluate_watches([
        {"id": "x", "metric": "at_risk_power", "direction": "above", "threshold": 0},
        {"id": "y", "metric": "churn_pct", "direction": "above", "threshold": 0},
    ], snap)
    check("two fire", len(multi) == 2)
    check("order preserved", multi[0]["watch_id"] == "x" and multi[1]["watch_id"] == "y")

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
