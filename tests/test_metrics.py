# tests/test_metrics.py — standalone script
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.analysis.metrics import calculate_churn_risk

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

# recency-based churn (canonical): recency_days > threshold = at risk
feat = pd.DataFrame({
    "customer_id": [1, 2, 3],
    "recency_days": [10, 45, 90],
    "frequency": [5, 3, 2],
})
at_risk, at_risk_power = calculate_churn_risk(feat, power_user_ids={2}, churn_days=30)
ok(set(at_risk["customer_id"]) == {2, 3}, "recency>30 flags customers 2 and 3")
ok(set(at_risk_power["customer_id"]) == {2}, "at-risk power = intersection with power ids")

# legacy fallback: no recency_days but avg_days_between_orders + user_id present
legacy = pd.DataFrame({
    "user_id": [1, 2],
    "avg_days_between_orders": [10, 60],
})
lr, lrp = calculate_churn_risk(legacy, power_user_ids=set(), churn_days=30)
ok(set(lr["user_id"]) == {2}, "falls back to avg_days_between_orders when no recency")

print(f"test_metrics: {checks} checks passed")
