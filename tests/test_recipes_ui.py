# tests/test_recipes_ui.py — AppTest (real Streamlit runtime, no network)
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from streamlit.testing.v1 import AppTest
from src.agent import recipes

# Isolate the store on a temp path so the test never touches real .app_state.
_TMP = os.path.join(tempfile.mkdtemp(), "recipes.json")
recipes.RECIPES_FILE = _TMP  # module-level default used by load/add/remove

SCRIPT = r'''
import streamlit as st
import pandas as pd
from src.agent import recipes
recipes.RECIPES_FILE = %r  # keep the child runtime on the same temp store
from src.data.canonical import build_feature_matrix
from src.data.app_data import features_from_matrix

orders = pd.DataFrame({
    "customer_id": [1, 1, 2, 2, 3, 3],
    "order_id":    [1, 2, 3, 4, 5, 6],
    "order_date": pd.to_datetime(["2024-01-01","2024-01-10","2024-02-01",
                                  "2024-02-20","2024-01-05","2024-03-01"]),
    "order_amount": [20.0, 25.0, 10.0, 12.0, 40.0, 45.0],
})
matrix = build_feature_matrix(orders)
features, available, active = features_from_matrix(matrix)
st.session_state["features"] = features
st.session_state["orders"] = orders
st.session_state["available"] = available
st.session_state["active_levers"] = active
st.session_state.setdefault("ui_history", [])
st.session_state.setdefault("chat_history", [])

from src.ui.tabs.chat import render_chat
render_chat(features, orders)
''' % _TMP


def _labels(buttons):
    return [b.label for b in buttons]


# A) Save form appears when a grounded query has just run.
at = AppTest.from_string(SCRIPT, default_timeout=60)
at.session_state["last_grounded_query"] = {
    "query": {"table": "customers", "operation": "aggregate",
              "metric": "frequency", "agg": "mean"},
    "label": "Mean of frequency (customers)",
}
at.run()
assert not at.exception, f"chat crashed: {[e.value for e in at.exception]}"
assert any("Save recipe" in (l or "") for l in _labels(at.button)), \
    f"save-recipe button present: {_labels(at.button)}"
print("test_recipes_ui: save form appears OK")

# B) A saved recipe renders a chip, and clicking it runs the query.
recipes.add_recipe("Avg frequency", {"table": "customers", "operation": "aggregate",
                                     "metric": "frequency", "agg": "mean"}, path=_TMP)
at2 = AppTest.from_string(SCRIPT, default_timeout=60).run()
assert not at2.exception, f"chat crashed with a recipe: {[e.value for e in at2.exception]}"
chips = [b for b in at2.button if (b.label or "").startswith("▶ Avg frequency")]
assert chips, f"recipe chip present: {_labels(at2.button)}"
chips[0].click()
at2.run()
assert not at2.exception, f"running recipe crashed: {[e.value for e in at2.exception]}"
hist = at2.session_state["ui_history"]
assert any((m.get("content") or "").startswith("▶ Avg frequency") for m in hist), \
    "recipe run appended a ▶ user marker"
assert any(m.get("type") in ("text", "table", "chart") and m.get("role") == "assistant"
           for m in hist), "recipe run rendered a result card"
print("test_recipes_ui: recipe chip runs OK")

print("test_recipes_ui: ALL PASSED")
