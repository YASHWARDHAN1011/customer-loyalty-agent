"""Standalone tests for src/analysis/simulation.py. No network, no Streamlit."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.analysis import simulation as sim

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


WEIGHTS = {"total_orders": 0.30, "reorder_rate": 0.25, "dept_diversity": 0.20,
           "avg_basket_size": 0.15, "total_items": 0.10}


def _features():
    return pd.DataFrame({
        "user_id":         list(range(1, 11)),
        "total_orders":    [50, 45, 40, 35, 30, 25, 20, 15, 10, 5],
        "reorder_rate":    [0.9, 0.85, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1],
        "dept_diversity":  [18, 16, 15, 13, 11, 9, 7, 6, 4, 3],
        "avg_basket_size": [14, 13, 12, 11, 10, 8, 7, 6, 5, 4],
        "total_items":     [600, 500, 450, 380, 300, 240, 180, 120, 70, 30],
    })


def main():
    f = _features()

    # --- LEVERS: exactly the 5 weighted features, excludes days-between-orders ---
    check("LEVERS has 5", len(sim.LEVERS) == 5)
    check("LEVERS excludes days", "avg_days_between_orders" not in sim.LEVERS)
    check("LEVERS == weight keys", set(sim.LEVERS) == set(WEIGHTS.keys()))

    # --- zero lift converts nobody; projected == baseline ---
    r0 = sim.simulate_campaign(f, WEIGHTS, 20, "total_orders", 0)
    check("zero lift -> 0 conversions", r0["conversions"] == 0)
    check("zero lift -> projected == baseline",
          r0["projected_power_count"] == r0["baseline_power_count"])
    check("result reports the feature", r0["feature"] == "total_orders")

    # --- a large lift converts at least one regular ---
    r100 = sim.simulate_campaign(f, WEIGHTS, 20, "total_orders", 100)
    check("big lift -> >=1 conversion", r100["conversions"] >= 1)
    check("projected == baseline + conversions",
          r100["projected_power_count"]
          == r100["baseline_power_count"] + r100["conversions"])
    check("after avg > before avg for positive lift",
          r100["feature_avg_after"] > r100["feature_avg_before"])

    # --- monotonicity: more lift never converts fewer ---
    seq = [sim.simulate_campaign(f, WEIGHTS, 20, "total_orders", p)["conversions"]
           for p in (0, 25, 50, 100)]
    check("conversions monotonic non-decreasing",
          all(seq[i] <= seq[i + 1] for i in range(len(seq) - 1)))

    # --- reorder_rate is clipped to <= 1.0 even under a huge lift ---
    rr = sim.simulate_campaign(f, WEIGHTS, 20, "reorder_rate", 100)
    check("reorder_rate avg after stays <= 1.0", rr["feature_avg_after"] <= 1.0)

    # --- result dict shape ---
    for key in ("feature", "lift_pct", "target_count", "conversions",
                "baseline_power_count", "projected_power_count",
                "projected_power_pct", "feature_avg_before",
                "feature_avg_after", "cutoff"):
        check(f"result has {key}", key in r100)

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
