"""Standalone tests for src/analysis/scoring.py scaler refactor. No network."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.analysis.scoring import (
    compute_scaler, apply_scoring, score_users, get_power_users,
)

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

    # compute_scaler returns caps for each weighted feature + a max_raw
    scaler = compute_scaler(f, WEIGHTS)
    check("scaler has caps", set(scaler["caps"].keys()) == set(WEIGHTS.keys()))
    check("scaler has positive max_raw", scaler["max_raw"] > 0)

    # score_users == apply_scoring(compute_scaler(...)) exactly
    su = score_users(f, WEIGHTS).set_index("user_id")["loyalty_score"]
    ap = apply_scoring(f, WEIGHTS, compute_scaler(f, WEIGHTS)).set_index("user_id")["loyalty_score"]
    check("score_users equals apply_scoring", (su == ap).all())

    # regression tripwire: top scorer normalizes to exactly 100
    check("top score is 100", su.max() == 100.0)

    # frozen-scaler property: lifting one user does NOT change an untouched user's score
    base = apply_scoring(f, WEIGHTS, scaler).set_index("user_id")["loyalty_score"]
    g = f.copy()
    g.loc[g["user_id"] == 9, "total_orders"] = 999      # bump only user 9
    lifted = apply_scoring(g, WEIGHTS, scaler).set_index("user_id")["loyalty_score"]
    check("untouched user score unchanged under frozen scaler",
          base.loc[1] == lifted.loc[1])
    check("bumped user score increased", lifted.loc[9] > base.loc[9])

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
