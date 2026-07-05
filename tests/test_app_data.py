# tests/test_app_data.py — standalone script
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.data.canonical import build_feature_matrix
from src.data.app_data import features_from_matrix

checks = 0
def ok(c, m):
    global checks; assert c, m; checks += 1

orders = pd.DataFrame({
    "customer_id": [1, 1, 2],
    "order_id": [10, 11, 12],
    "order_date": ["2024-01-01", "2024-01-10", "2024-01-05"],
    "order_amount": [50.0, 30.0, 20.0],
})
matrix = build_feature_matrix(orders)
features, available, active = features_from_matrix(matrix)

ok("user_id" in features.columns, "adapter aliases customer_id -> user_id")
ok("customer_id" in features.columns, "adapter keeps customer_id too")
ok(list(features["user_id"]) == list(features["customer_id"]), "user_id equals customer_id")
ok("frequency" in features.columns, "canonical feature columns pass through")
ok(available["frequency"] is True, "availability map is returned")
ok("frequency" in active and "avg_basket_size" not in active,
   "active levers reflect availability")

print(f"test_app_data: {checks} checks passed")
