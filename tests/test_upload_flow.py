"""Phase 6 upload flow + app-boot wiring tests (no network)."""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from streamlit.testing.v1 import AppTest

def test_app_boots_on_demo_zero_exceptions():
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception, f"app raised: {at.exception}"
    # The active dataset is populated and labelled as the demo.
    assert at.session_state["dataset_source"] == "demo"
    assert at.session_state["dataset_label"]
    assert at.session_state["dataset_counts"]["customers"] > 0

import io, json, tempfile, pandas as pd
from src.ui.upload import prepare_upload, apply_mapping

_GOOD_CSV = (
    "Cust,Ord,When,Paid\n"
    "1,100,2024-01-01,10.00\n"
    "1,101,2024-01-15,5.50\n"
    "2,102,2024-02-01,20.00\n"
)

def _fake_generate(_prompt):
    # Deterministic "LLM": returns the correct mapping JSON for _GOOD_CSV.
    return json.dumps({"customer_id": "Cust", "order_id": "Ord",
                       "order_date": "When", "order_amount": "Paid"})

def test_prepare_upload_proposes_mapping_no_saved_recipe():
    df = pd.read_csv(io.StringIO(_GOOD_CSV), dtype=str)
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        state = prepare_upload(df, generate_fn=_fake_generate, store_path=store)
    assert state["stage"] == "confirm"
    assert state["saved"] is False
    assert state["mapping"]["order_amount"] == "Paid"
    assert [p["name"] for p in state["profile"]] == ["Cust", "Ord", "When", "Paid"]

def test_prepare_upload_uses_saved_recipe_fast_path():
    df = pd.read_csv(io.StringIO(_GOOD_CSV), dtype=str)
    mapping = {"customer_id": "Cust", "order_id": "Ord",
               "order_date": "When", "order_amount": "Paid"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        from src.data.ingest.mapping_store import save_mapping
        save_mapping(list(df.columns), mapping, path=store)
        state = prepare_upload(df, generate_fn=_fake_generate, store_path=store)
    assert state["stage"] == "build"      # skips confirm
    assert state["saved"] is True
    assert state["mapping"] == mapping

def test_apply_mapping_success_builds_canonical():
    df = pd.read_csv(io.StringIO(_GOOD_CSV), dtype=str)
    mapping = {"customer_id": "Cust", "order_id": "Ord",
               "order_date": "When", "order_amount": "Paid"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        result = apply_mapping(df, mapping, store_path=store)
        assert result["ok"] is True
        assert result["matrix"] is not None
        with open(store) as fh:
            assert json.load(fh)  # non-empty store (mapping persisted)

def test_apply_mapping_failure_returns_errors():
    bad = "Cust,Ord,When,Paid\n1,100,2024-01-01,notmoney\n2,101,2024-01-02,alsobad\n"
    df = pd.read_csv(io.StringIO(bad), dtype=str)
    mapping = {"customer_id": "Cust", "order_id": "Ord",
               "order_date": "When", "order_amount": "Paid"}
    with tempfile.TemporaryDirectory() as d:
        store = os.path.join(d, "mappings.json")
        result = apply_mapping(df, mapping, store_path=store)
    assert result["ok"] is False
    assert result["errors"]
    assert result["matrix"] is None

if __name__ == "__main__":
    test_app_boots_on_demo_zero_exceptions()
    test_prepare_upload_proposes_mapping_no_saved_recipe()
    test_prepare_upload_uses_saved_recipe_fast_path()
    test_apply_mapping_success_builds_canonical()
    test_apply_mapping_failure_returns_errors()
    print("test_upload_flow: OK")
