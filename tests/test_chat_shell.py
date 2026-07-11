"""Chat-first shell boots with 0 exceptions and has no 6-tab dashboard."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from streamlit.testing.v1 import AppTest

def test_chat_first_shell_boots():
    at = AppTest.from_file("app.py", default_timeout=60).run()
    assert not at.exception, f"app raised: {at.exception}"
    # Chat input is present (the landing surface).
    assert len(at.chat_input) >= 1
    # The old analytical dashboard is gone: at most 0 top-level tab groups
    # containing the retired tab labels.
    labels = [t.label for t in at.tabs]
    for gone in ("Overview", "Scoring", "Segments", "Happy Path", "Interventions"):
        assert gone not in labels, f"retired tab still present: {gone}"

if __name__ == "__main__":
    test_chat_first_shell_boots()
    print("test_chat_shell: OK")
