# tests/test_recipes.py — standalone script (pure store, no network, no Streamlit)
import os, sys, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent.recipes import (
    load_recipes, add_recipe, remove_recipe, describe_query,
)

def _tmp():
    d = tempfile.mkdtemp()
    return os.path.join(d, "recipes.json")

# describe_query --------------------------------------------------------------
assert describe_query({"table": "customers", "operation": "aggregate",
                       "metric": "frequency", "agg": "mean"}) == \
    "Mean of frequency (customers)", "scalar label"
assert describe_query({"table": "orders", "operation": "aggregate",
                       "metric": "order_amount", "agg": "mean",
                       "group_by": "category"}) == \
    "Mean of order amount by category (orders)", "grouped label"
assert describe_query({"table": "customers", "operation": "correlate",
                       "column_a": "frequency", "column_b": "monetary"}) == \
    "Correlation: frequency vs monetary (customers)", "correlation label"
assert describe_query({"table": "customers", "operation": "aggregate",
                       "metric": "frequency", "agg": "count",
                       "filter_column": "recency_days", "filter_op": ">"}) == \
    "Count of frequency (customers), filtered", "filtered label"
print("test_recipes: describe_query OK")

# round-trip ------------------------------------------------------------------
p = _tmp()
assert load_recipes(path=p) == [], "empty store -> []"
q = {"table": "customers", "operation": "aggregate", "metric": "frequency", "agg": "mean"}
rec = add_recipe("My avg freq", q, path=p)
assert rec["id"] and rec["name"] == "My avg freq" and rec["query"] == q, rec
assert "created" in rec, "timestamped"
got = load_recipes(path=p)
assert len(got) == 1 and got[0]["id"] == rec["id"], got
# second recipe appends
rec2 = add_recipe("Second", q, path=p)
assert len(load_recipes(path=p)) == 2
# remove
assert remove_recipe(rec["id"], path=p) is True
left = load_recipes(path=p)
assert len(left) == 1 and left[0]["id"] == rec2["id"], left
assert remove_recipe("nope", path=p) is False, "removing unknown id -> False"
print("test_recipes: round-trip OK")

# blank name falls back to derived label -------------------------------------
p2 = _tmp()
r = add_recipe("   ", q, path=p2)
assert r["name"] == "Mean of frequency (customers)", r
print("test_recipes: blank-name fallback OK")

# corrupt / non-list store tolerated -----------------------------------------
p3 = _tmp()
with open(p3, "w", encoding="utf-8") as f:
    f.write("{ this is not valid json ]")
assert load_recipes(path=p3) == [], "corrupt JSON -> []"
p4 = _tmp()
with open(p4, "w", encoding="utf-8") as f:
    json.dump({"not": "a list"}, f)
assert load_recipes(path=p4) == [], "non-list JSON -> []"
# entries missing a dict query are dropped
p5 = _tmp()
with open(p5, "w", encoding="utf-8") as f:
    json.dump([{"id": "a", "name": "x"}, {"id": "b", "name": "y", "query": {"k": 1}}], f)
kept = load_recipes(path=p5)
assert len(kept) == 1 and kept[0]["id"] == "b", kept
print("test_recipes: corrupt-store tolerance OK")

print("test_recipes: ALL PASSED")
