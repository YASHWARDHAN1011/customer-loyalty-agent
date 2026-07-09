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

if __name__ == "__main__":
    test_app_boots_on_demo_zero_exceptions()
    print("test_upload_flow(boot): OK")
