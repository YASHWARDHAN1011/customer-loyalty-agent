"""Full-numbers panel tests via AppTest (no network)."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd
from streamlit.testing.v1 import AppTest

_SCRIPT = (
    "import streamlit as st\n"
    "from src.ui.full_numbers import render_full_numbers\n"
    "render_full_numbers()\n"
)

def _scored():
    return pd.DataFrame({
        "user_id": [1, 2, 3, 4],
        "frequency": [10, 3, 8, 1],
        "monetary": [100.0, 20.0, 80.0, 5.0],
        "recency_days": [5, 60, 10, 90],
        "loyalty_score": [90.0, 30.0, 75.0, 10.0],
    })

def test_hint_shown_before_analysis():
    at = AppTest.from_string(_SCRIPT, default_timeout=30).run()
    assert not at.exception
    # No metrics rendered when there's no scored_df.
    assert len(at.metric) == 0

def test_panel_renders_after_analysis():
    scored = _scored()
    power = scored[scored["loyalty_score"] >= 70].copy()
    regular = scored[scored["loyalty_score"] < 70].copy()
    at = AppTest.from_string(_SCRIPT, default_timeout=30)
    at.session_state["scored_df"] = scored
    at.session_state["features"] = scored
    at.session_state["power"] = power
    at.session_state["regular"] = regular
    at.session_state["cutoff"] = 70.0
    at.session_state["power_user_ids"] = set(power["user_id"])
    at.run()
    assert not at.exception
    assert len(at.metric) >= 4  # customers / power / at-risk / avg score

if __name__ == "__main__":
    test_hint_shown_before_analysis()
    test_panel_renders_after_analysis()
    print("test_full_numbers: OK")
