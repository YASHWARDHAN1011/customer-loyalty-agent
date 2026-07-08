# tests/test_tool_context.py — standalone script
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.agent import tool_context as tc

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

# canonical (orders-only) frame: core features, no optional
canon = pd.DataFrame({
    "user_id": [1, 2],
    "recency_days": [5, 40],
    "frequency": [10, 3],
    "monetary": [200.0, 50.0],
    "avg_order_value": [20.0, 16.7],
    "tenure_days": [100, 90],
    "avg_days_between_orders": [10.0, 30.0],
})
# instacart-style frame
insta = pd.DataFrame({
    "user_id": [1], "total_orders": [10], "reorder_rate": [0.5],
    "dept_diversity": [4], "avg_basket_size": [8.0], "total_items": [80],
})

ok(tc.feature_label("frequency") == "Order Frequency", "lever label from LEVER_LABELS")
ok(tc.feature_label("recency_days") == "Days Since Last Order", "core label")
ok(tc.feature_label("whatever_new") == "Whatever New", "fallback title-cases")

ok("user_id" not in tc.present_feature_cols(canon), "present cols drop user_id")
ok(tc.present_feature_cols(canon)[0] == "recency_days", "present cols keep frame order")

ok(tc.order_count_col(canon) == "frequency", "canonical order count = frequency")
ok(tc.order_count_col(insta) == "total_orders", "instacart order count = total_orders")
ok(tc.order_count_col(pd.DataFrame({"user_id": [1]})) is None, "no order col -> None")

ok(tc.churn_gap_col(canon) == "recency_days", "canonical churn col = recency_days")
ok(tc.churn_gap_col(insta) is None, "no churn col -> None")
ok(tc.churn_gap_col(pd.DataFrame({"user_id": [1], "avg_days_between_orders": [5.0]}))
   == "avg_days_between_orders", "avg-gap fallback")

stats = tc.summary_stats(canon, max_cols=3)
ok(len(stats) == 3, "summary_stats caps at max_cols")
ok(all(isinstance(v, float) for v in stats.values()), "summary_stats values are floats")
ok("Order Frequency" in stats, "summary_stats keys are labels")

print(f"test_tool_context: {checks} checks passed")
