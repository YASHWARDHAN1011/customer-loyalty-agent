# tests/test_query.py — standalone script (pure engine, no network, no Streamlit)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
from src.analysis.query import run_query

# Hand-computable fixtures ----------------------------------------------------
customers = pd.DataFrame({
    "customer_id": [1, 2, 3, 4, 5],
    "frequency":   [10, 20, 30, 40, 50],   # mean 30, sum 150, median 30
    "monetary":    [100.0, 400.0, 900.0, 1600.0, 2500.0],
    "recency_days":[5, 50, 95, 120, 200],
    "region":      ["N", "N", "S", "S", "S"],  # N: freq 10,20 ; S: 30,40,50
})
orders = pd.DataFrame({
    "order_id":     [1, 2, 3, 4],
    "order_amount": [10.0, 20.0, 30.0, 40.0],
    "category":     ["a", "a", "b", "b"],
})
tables = {"customers": customers, "orders": orders, "order_items": None}

def approx(a, b, tol=1e-6):
    return abs(a - b) <= tol

# 1) scalar aggregates: every agg -------------------------------------------
r = run_query(tables, table="customers", operation="aggregate", metric="frequency", agg="mean")
assert r["ok"] and r["kind"] == "scalar" and approx(r["value"], 30.0), r
assert r["n"] == 5 and r["query"]["metric"] == "frequency", r
assert run_query(tables, metric="frequency", agg="sum")["value"] == 150.0
assert run_query(tables, metric="frequency", agg="median")["value"] == 30.0
assert run_query(tables, metric="frequency", agg="min")["value"] == 10.0
assert run_query(tables, metric="frequency", agg="max")["value"] == 50.0
assert run_query(tables, metric="region", agg="count")["value"] == 5   # count works on text
print("test_query: scalar aggregates OK")

# 2) group-by ----------------------------------------------------------------
g = run_query(tables, table="customers", operation="aggregate",
              metric="frequency", agg="mean", group_by="region")
assert g["ok"] and g["kind"] == "table" and g["n_groups"] == 2, g
by = {row["group"]: row["value"] for row in g["rows"]}
assert approx(by["N"], 15.0) and approx(by["S"], 40.0), g   # N=(10+20)/2, S=(30+40+50)/3
# sorted descending by value: S (40) before N (15)
assert g["rows"][0]["group"] == "S", g
assert g["truncated"] is False, g
print("test_query: group-by OK")

# 3) limit cap + truncated ---------------------------------------------------
many = pd.DataFrame({"g": list(range(60)), "v": list(range(60))})
gt = run_query({"customers": many}, metric="v", agg="sum", group_by="g", limit=100)
assert len(gt["rows"]) == 50 and gt["truncated"] is True and gt["n_groups"] == 60, gt
gsmall = run_query({"customers": many}, metric="v", agg="sum", group_by="g", limit=5)
assert len(gsmall["rows"]) == 5 and gsmall["truncated"] is True, gsmall
print("test_query: limit cap + truncated OK")

# 4) filters: every op -------------------------------------------------------
f = run_query(tables, metric="frequency", agg="count",
              filter_column="recency_days", filter_op=">", filter_value="90")
assert f["value"] == 3, f   # 95, 120, 200
assert run_query(tables, metric="frequency", agg="count",
                 filter_column="recency_days", filter_op="<", filter_value="90")["value"] == 2
assert run_query(tables, metric="frequency", agg="count",
                 filter_column="recency_days", filter_op=">=", filter_value="95")["value"] == 3
assert run_query(tables, metric="frequency", agg="count",
                 filter_column="recency_days", filter_op="<=", filter_value="50")["value"] == 2
assert run_query(tables, metric="frequency", agg="count",
                 filter_column="frequency", filter_op="==", filter_value="30")["value"] == 1
btw = run_query(tables, metric="frequency", agg="count", filter_column="recency_days",
                filter_op="between", filter_value="50", filter_value2="120")
assert btw["value"] == 3, btw   # 50, 95, 120
# string-equality filter
seq = run_query(tables, metric="frequency", agg="sum",
                filter_column="region", filter_op="==", filter_value="S")
assert seq["value"] == 120.0, seq   # 30+40+50
print("test_query: filters OK")

# 5) correlation -------------------------------------------------------------
c = run_query(tables, table="customers", operation="correlate",
              column_a="frequency", column_b="monetary")
assert c["ok"] and c["kind"] == "correlation", c
assert 0.9 <= c["r"] <= 1.0 and c["n"] == 5, c   # monetary = (freq/10)^2 * 100, strongly +
print("test_query: correlation OK")

# 6) guards: never raise, always {"ok": False, "error": str} ----------------
def bad(**kw):
    out = run_query(tables, **kw)
    assert out["ok"] is False and isinstance(out.get("error"), str) and out["error"], out
    return out["error"]

assert "table" in bad(table="widgets").lower()
assert "operation" in bad(operation="frobnicate").lower()
assert "aggregation" in bad(metric="frequency", agg="stddev").lower()
assert "no such column" in bad(metric="nope").lower()
assert "no such column" in bad(metric="frequency", group_by="nope").lower()
assert "numeric" in bad(metric="region", agg="mean").lower()          # sum/mean on text
assert "numeric" in bad(operation="correlate", column_a="region", column_b="frequency").lower()
assert "product-level" in bad(table="order_items").lower()            # None degradation
# empty filtered population -> no divide-by-zero, clear message
empty = run_query(tables, metric="frequency", agg="mean",
                  filter_column="frequency", filter_op=">", filter_value="9999")
assert empty["ok"] is False and "no rows" in empty["error"].lower(), empty
# correlation needs >= 2 non-null pairs
one = run_query({"customers": pd.DataFrame({"a": [1.0], "b": [2.0]})},
                operation="correlate", column_a="a", column_b="b")
assert one["ok"] is False and "at least 2" in one["error"].lower(), one
# between with a missing bound
mb = run_query(tables, metric="frequency", agg="count", filter_column="recency_days",
               filter_op="between", filter_value="50")
assert mb["ok"] is False and "between" in mb["error"].lower(), mb
print("test_query: guards OK")

# 7) NaN-group handling: a group whose metric is all-null is dropped from rows,
#    but still counted in n_groups; values stay JSON-clean (no NaN token).
import json
nan_df = pd.DataFrame({
    "grp":    ["x", "x", "y", "y"],
    "val":    [1.0, 3.0, None, None],   # group y has no non-null values
})
ng = run_query({"customers": nan_df}, metric="val", agg="mean", group_by="grp")
assert ng["ok"] and ng["n_groups"] == 2, ng          # both x and y are distinct groups
groups = [row["group"] for row in ng["rows"]]
assert "y" not in groups and "x" in groups, ng        # all-null group dropped from rows
json.dumps(ng)  # must not raise / must be JSON-clean (no bare NaN token)
print("test_query: NaN-group handling OK")

print("test_query: ALL PASSED")
