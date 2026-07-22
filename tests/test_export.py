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


_REPORT = '''
import os, sys
sys.path.insert(0, os.getcwd())
import pandas as pd, streamlit as st
from src.export.generator import generate_summary_report
st.session_state["scored_df"] = pd.DataFrame({"user_id": [1, 2], "loyalty_score": [40.0, 88.0]})
st.session_state["power"] = pd.DataFrame({"user_id": [2]})
st.session_state["dataset_label"] = "au_client.csv"
st.session_state["_report"] = generate_summary_report()
'''


def test_summary_report_uses_active_dataset_label():
    at = AppTest.from_string(_REPORT, default_timeout=60).run()
    check("report: no exception", not at.exception)
    rpt = at.session_state["_report"]
    check("report: uses active dataset label", "au_client.csv" in rpt)
    check("report: no hardcoded Instacart platform label",
          "Instacart Grocery Platform" not in rpt)


_INTERV = '''
import os, sys
sys.path.insert(0, os.getcwd())
import pandas as pd, streamlit as st
from src.export.generator import generate_summary_report
st.session_state["scored_df"] = pd.DataFrame({"user_id": [1, 2, 3, 4],
                                              "loyalty_score": [30.0, 50.0, 80.0, 95.0]})
# Canonical levers only (frequency/monetary) — power clearly above regular.
st.session_state["power"] = pd.DataFrame({"user_id": [3, 4], "frequency": [10, 12], "monetary": [500.0, 600.0]})
st.session_state["regular"] = pd.DataFrame({"user_id": [1, 2], "frequency": [2, 3], "monetary": [80.0, 100.0]})
st.session_state["dataset_label"] = "au_client.csv"
st.session_state["_report"] = generate_summary_report()
'''


def test_summary_report_interventions_dataset_aware():
    at = AppTest.from_string(_INTERV, default_timeout=60).run()
    check("interventions: no exception", not at.exception)
    rpt = at.session_state["_report"]
    # The old hardcoded Instacart copy must be gone.
    check("interventions: no hardcoded '< 5 orders' copy", "< 5 orders" not in rpt)
    check("interventions: no hardcoded 'departments' copy", "departments" not in rpt)
    # Data-driven from the dataset's real levers.
    check("interventions: references a real lever (frequency)", "frequency" in rpt.lower())
    check("interventions: shows a computed gap %", "% gap" in rpt)


_CANONICAL_CURRENCY = '''
import os, sys
sys.path.insert(0, os.getcwd())
import pandas as pd, streamlit as st
from src.export.generator import generate_csv_export
st.session_state["scored_df"] = pd.DataFrame({
    "user_id": [1, 2], "monetary": [100.0, 50.0], "loyalty_score": [80.0, 20.0]})
st.session_state["power_user_ids"] = {1}
st.session_state["reporting_currency"] = "AUD"
st.session_state["_csv_out"] = generate_csv_export()
'''


def test_csv_export_labels_monetary_currency():
    at = AppTest.from_string(_CANONICAL_CURRENCY, default_timeout=60).run()
    check("currency export: no exception", not at.exception)
    header = at.session_state["_csv_out"].decode("utf-8").splitlines()[0]
    check("currency export: monetary header carries (AUD)", "(AUD)" in header)


def main():
    test_export_canonical_no_keyerror()
    test_export_instacart_still_works()
    test_summary_report_uses_active_dataset_label()
    test_summary_report_interventions_dataset_aware()
    test_csv_export_labels_monetary_currency()
    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
