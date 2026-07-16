"""Standalone tests for src/export/generator.py — CSV export must work on ANY
dataset's feature columns (canonical RFM or Instacart), never KeyError. No network."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


_CANONICAL = '''
import os, sys
sys.path.insert(0, os.getcwd())
import pandas as pd, streamlit as st
from src.export.generator import generate_csv_export
# Canonical RFM scored_df — NONE of the hardcoded Instacart columns exist.
st.session_state["scored_df"] = pd.DataFrame({
    "user_id": [1, 2], "frequency": [3, 5], "monetary": [100.0, 250.0],
    "recency_days": [10, 4], "loyalty_score": [40.0, 88.0]})
st.session_state["power_user_ids"] = {2}
st.session_state["_csv_out"] = generate_csv_export()
'''

_INSTACART = '''
import os, sys
sys.path.insert(0, os.getcwd())
import pandas as pd, streamlit as st
from src.export.generator import generate_csv_export
st.session_state["scored_df"] = pd.DataFrame({
    "user_id": [1], "total_orders": [10], "reorder_rate": [0.5], "dept_diversity": [8],
    "avg_basket_size": [12.0], "total_items": [120], "avg_days_between_orders": [7.0],
    "loyalty_score": [75.0]})
st.session_state["power_user_ids"] = {1}
st.session_state["_csv_out"] = generate_csv_export()
'''


def test_export_canonical_no_keyerror():
    at = AppTest.from_string(_CANONICAL, default_timeout=60).run()
    check("canonical export: no exception", not at.exception)
    csv = at.session_state["_csv_out"]
    check("canonical export: returns bytes", isinstance(csv, (bytes, bytearray)))
    text = csv.decode("utf-8")
    check("canonical export: has Customer ID header", "Customer ID" in text)
    check("canonical export: has Loyalty Score header", "Loyalty Score (0-100)" in text)
    check("canonical export: includes a canonical feature column",
          "Frequency" in text or "Monetary" in text)


def test_export_instacart_still_works():
    at = AppTest.from_string(_INSTACART, default_timeout=60).run()
    check("instacart export: no exception", not at.exception)
    text = at.session_state["_csv_out"].decode("utf-8")
    check("instacart export: keeps Total Orders label", "Total Orders" in text)


def main():
    test_export_canonical_no_keyerror()
    test_export_instacart_still_works()
    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
