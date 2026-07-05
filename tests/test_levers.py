# tests/test_levers.py — standalone script (repo convention)
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.data.canonical import build_feature_matrix
from src.data import levers

checks = 0
def ok(cond, msg):
    global checks
    assert cond, msg
    checks += 1

# orders-only matrix -> only orders-derivable levers are active
orders = pd.DataFrame({
    "customer_id": [1, 1, 2],
    "order_id": [10, 11, 12],
    "order_date": ["2024-01-01", "2024-01-10", "2024-01-05"],
    "order_amount": [50.0, 30.0, 20.0],
})
m_core = build_feature_matrix(orders)
al = levers.active_levers(m_core)
ok("frequency" in al, "frequency should be an active lever on orders-only")
ok("monetary" in al, "monetary should be active")
ok("avg_basket_size" not in al, "optional levers inactive without order_items")
ok("recency_days" not in levers.SCORING_LEVERS, "recency is churn, not a loyalty lever")
ok("avg_days_between_orders" not in levers.SCORING_LEVERS, "avg-gap is churn, not a lever")

# default_weights: equal, sums to 1.0, one entry per active lever
w = levers.default_weights(al)
ok(abs(sum(w.values()) - 1.0) < 1e-9, "default weights must sum to 1.0")
ok(set(w.keys()) == set(al), "default weights cover exactly the active levers")

# renormalize_weights: drop absent levers, rescale remainder to sum 1.0
raw = {"frequency": 0.5, "monetary": 0.25, "avg_basket_size": 0.25}
rn = levers.renormalize_weights(raw, ["frequency", "monetary"])
ok(set(rn.keys()) == {"frequency", "monetary"}, "renorm drops unavailable levers")
ok(abs(sum(rn.values()) - 1.0) < 1e-9, "renorm rescales to 1.0")
ok(abs(rn["frequency"] - (0.5 / 0.75)) < 1e-9, "renorm preserves relative weight")

# all-zero weights over the levers -> fall back to equal
rz = levers.renormalize_weights({"frequency": 0.0, "monetary": 0.0}, ["frequency", "monetary"])
ok(abs(rz["frequency"] - 0.5) < 1e-9, "all-zero renorm falls back to equal weights")

# every lever has a human label
for lv in levers.SCORING_LEVERS:
    ok(lv in levers.LEVER_LABELS, f"{lv} needs a UI label")

print(f"test_levers: {checks} checks passed")
