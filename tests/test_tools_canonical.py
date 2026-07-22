# tests/test_tools_canonical.py — standalone script (real Streamlit runtime, no network)
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest

# Script executed under a real runtime so st.session_state works and tools run
# for real on canonical (orders-only) data. Each tool's result is stashed in
# session_state["_r"] for the assertions below.
SCRIPT = r'''
import streamlit as st
import pandas as pd
from src.data.canonical import build_feature_matrix
from src.data.app_data import features_from_matrix

# Orders-only canonical dataset -> core features only (optional levers absent).
orders = pd.DataFrame({
    "customer_id": [1, 1, 1, 2, 2, 3, 3, 3, 3, 4],
    "order_id":    [1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
    "order_date": pd.to_datetime([
        "2024-01-01", "2024-01-10", "2024-01-25", "2024-02-01", "2024-03-01",
        "2024-01-05", "2024-01-06", "2024-01-20", "2024-02-15", "2024-01-02"]),
    "order_amount": [20.0, 25.0, 30.0, 10.0, 12.0, 40.0, 45.0, 50.0, 55.0, 5.0],
})
matrix = build_feature_matrix(orders)
features, available, active = features_from_matrix(matrix)
st.session_state["features"] = features
st.session_state["available"] = available
st.session_state["active_levers"] = active
st.session_state.setdefault("ui_history", [])

from src.agent import tools
r = st.session_state.setdefault("_r", {})
r["scoring"] = tools.run_scoring_analysis(50)   # 50% power split on tiny data
r["stats"] = tools.get_current_stats()
r["churn"] = tools.analyze_churn_risk(20)
r["profile"] = tools.get_user_profile(1)
r["search"] = tools.search_users(min_orders=2, limit=5)
from src.data import levers as _lv
st.session_state["weights"] = _lv.default_weights(st.session_state["active_levers"])
r["sim_bad"] = tools.simulate_campaign("total_items", 10)
r["sim_ok"] = tools.simulate_campaign("frequency", 10)
r["target"] = tools.export_target_list(segment="power", limit=10)
r["interventions"] = tools.run_interventions()
r["emails"] = tools.draft_campaign_emails()
r["plan"] = tools.build_action_plan(20)
r["segmentation"] = tools.run_segmentation()
r["happy"] = tools.run_happy_path(3)
# Phase 8 grounded query — scalar aggregate, correlation, order_items degrade.
r["gq_scalar"] = tools.run_grounded_query(
    table="customers", operation="aggregate", metric="frequency", agg="mean")
# Multi-currency labelling — a monetary scalar carries the reporting currency.
# Run BEFORE the correlation so the correlate query stays the last stashed one.
st.session_state["reporting_currency"] = "AUD"
r["gq_money"] = tools.run_grounded_query(
    table="customers", operation="aggregate", metric="monetary", agg="mean")
r["gq_corr"] = tools.run_grounded_query(
    table="customers", operation="correlate", column_a="frequency", column_b="monetary")
r["gq_badcol"] = tools.run_grounded_query(
    table="customers", operation="aggregate", metric="does_not_exist", agg="mean")
r["gq_items"] = tools.run_grounded_query(
    table="order_items", operation="aggregate", metric="anything", agg="count")
'''

def run():
    at = AppTest.from_string(SCRIPT, default_timeout=120)
    at.run()
    assert len(at.exception) == 0, f"tool crashed on canonical data: {[e.value for e in at.exception]}"
    return at

at = run()
r = at.session_state["_r"]
assert r["scoring"]["status"] == "success", f"scoring failed: {r['scoring']}"
assert r["scoring"]["power_user_count"] >= 1, "scoring produced power users on canonical data"
print("test_tools_canonical: run_scoring_analysis OK on canonical data")

assert r["stats"]["data_loaded"] is True, "stats: data_loaded"
assert r["stats"]["scoring_complete"] is True, "stats: scoring done after scoring call"
assert isinstance(r["stats"].get("metrics"), dict) and r["stats"]["metrics"], \
    "stats: metrics dict computed over available features"
print("test_tools_canonical: get_current_stats OK on canonical data")

assert r["churn"]["status"] == "success", f"churn failed: {r['churn']}"
assert "total_at_risk" in r["churn"], "churn: total_at_risk present"
assert r["churn"].get("at_risk_avg_gap") is not None, \
    "churn: at_risk_avg_gap populated via recency_days on canonical data"
print("test_tools_canonical: analyze_churn_risk OK on canonical data")

assert r["profile"]["status"] == "success", f"profile failed: {r['profile']}"
p = r["profile"]["profile"]
assert p["user_id"] == 1 and "segment" in p, "profile: id + segment"
assert "frequency" in p, "profile: includes an available canonical feature"
assert "total_orders" not in p, "profile: does not fabricate Instacart columns"
print("test_tools_canonical: get_user_profile OK on canonical data")

assert r["search"]["status"] == "success", f"search failed: {r['search']}"
assert r["search"]["total_matching"] >= 1, "search: at least one user matches min_orders=2"
print("test_tools_canonical: search_users OK on canonical data")

assert "error" in r["sim_bad"], "sim rejects a lever absent from this dataset"
assert r["sim_ok"].get("conversions") is not None, f"sim ran on an active lever: {r['sim_ok']}"
print("test_tools_canonical: simulate_campaign OK on canonical data")

assert r["target"]["status"] in ("success", "no_results"), f"export failed: {r['target']}"
print("test_tools_canonical: export_target_list OK on canonical data")

assert r["interventions"]["status"] == "success", f"interventions failed: {r['interventions']}"
assert r["interventions"]["campaigns_generated"] >= 1, "interventions produced content on canonical levers"
assert r["emails"]["status"] == "success", f"emails failed: {r['emails']}"
assert r["plan"]["status"] == "success", f"plan failed: {r['plan']}"
print("test_tools_canonical: interventions/emails/plan OK on canonical data")

assert r["segmentation"]["status"] == "success", f"segmentation failed: {r['segmentation']}"
assert r["segmentation"]["biggest_gap_feature"], "segmentation named a biggest-gap feature"
print("test_tools_canonical: run_segmentation OK on canonical data")
# run_happy_path needs product-level order_items (absent on orders-only data),
# so it must DEGRADE cleanly (error/no_results), never crash.
assert r["happy"].get("status") != "success" or "paths" in r["happy"], \
    f"happy_path should degrade cleanly on orders-only data: {r['happy']}"
print("test_tools_canonical: run_happy_path degrades cleanly on canonical data")

# --- Phase 8: run_grounded_query on canonical (orders-only) data ---
assert r["gq_scalar"]["status"] == "success", f"grounded scalar failed: {r['gq_scalar']}"
assert isinstance(r["gq_scalar"].get("value"), (int, float)), "grounded scalar returned a real number"
assert r["gq_scalar"]["n"] >= 1, "grounded scalar counted real rows"
print("test_tools_canonical: run_grounded_query scalar OK on canonical data")

assert r["gq_corr"]["status"] == "success", f"grounded correlation failed: {r['gq_corr']}"
assert isinstance(r["gq_corr"].get("r"), (int, float)), "grounded correlation returned a real r"
print("test_tools_canonical: run_grounded_query correlation OK on canonical data")

assert r["gq_badcol"]["status"] == "error", "grounded query reports a bad column as an error"
assert "no such column" in r["gq_badcol"]["error"].lower(), r["gq_badcol"]
print("test_tools_canonical: run_grounded_query bad-column degrades cleanly")

assert r["gq_items"]["status"] == "error", "order_items query degrades (not loaded on canonical)"
assert "product-level" in r["gq_items"]["error"].lower(), r["gq_items"]
print("test_tools_canonical: run_grounded_query order_items degrades cleanly")

# --- Phase 9: successful grounded query stashes last_grounded_query ---
try:
    lgq = at.session_state["last_grounded_query"]
except KeyError:
    lgq = None
assert lgq and isinstance(lgq.get("query"), dict), f"last_grounded_query stashed: {lgq}"
assert lgq["query"]["operation"] == "correlate", "stash holds the LAST successful query"
assert isinstance(lgq.get("label"), str) and lgq["label"], "stash carries a human label"
print("test_tools_canonical: last_grounded_query stash OK")

# --- Multi-currency: a monetary scalar is labelled with the reporting currency ---
assert r["gq_money"]["status"] == "success", f"grounded money query failed: {r['gq_money']}"
assert r["gq_money"].get("currency") == "AUD", f"scalar carries currency: {r['gq_money']}"
_texts = [m.get("content", "") for m in at.session_state["ui_history"]
          if isinstance(m.get("content"), str)]
assert any("A$" in t for t in _texts), f"a rendered card shows the A$ symbol: {_texts}"
print("test_tools_canonical: run_grounded_query monetary scalar carries currency")
