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
print("test_tools_canonical: analyze_churn_risk OK on canonical data")

assert r["profile"]["status"] == "success", f"profile failed: {r['profile']}"
p = r["profile"]["profile"]
assert p["user_id"] == 1 and "segment" in p, "profile: id + segment"
assert "frequency" in p, "profile: includes an available canonical feature"
assert "total_orders" not in p, "profile: does not fabricate Instacart columns"
print("test_tools_canonical: get_user_profile OK on canonical data")

assert r["search"]["status"] in ("success", "no_results"), f"search failed: {r['search']}"
print("test_tools_canonical: search_users OK on canonical data")

assert "error" in r["sim_bad"], "sim rejects a lever absent from this dataset"
assert r["sim_ok"].get("conversions") is not None, f"sim ran on an active lever: {r['sim_ok']}"
print("test_tools_canonical: simulate_campaign OK on canonical data")
