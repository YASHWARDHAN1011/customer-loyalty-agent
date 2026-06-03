"""
Standalone test for chat persistence (Feature 4).

Run from the inner project dir:
  ..\\venv\\Scripts\\python.exe tests/test_persistence.py

Verifies the serialize/deserialize round-trip (including a DataFrame chart and
a Gemini-style chat history), that load_session reads what was written, and
that clear_session removes the file.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd  # noqa: E402
from src.utils import persistence as P  # noqa: E402

failures = []


def check(cond, msg):
    print(f"[{'OK ' if cond else 'FAIL'}] {msg}")
    if not cond:
        failures.append(msg)


print("=== Chat persistence test ===")

# Sample state: a text msg + a chart msg carrying a DataFrame.
chart_df = pd.DataFrame({'dept': ['produce', 'dairy'], 'count': [120, 80]})
ui_history = [
    {'role': 'assistant', 'type': 'text', 'content': 'Hello there'},
    {'role': 'assistant', 'type': 'chart', 'title': 'Top depts',
     'chart_type': 'bar', 'x': 'dept', 'y': 'count', 'data': chart_df},
]
# Gemini-style history: dict turns plus a tool-call turn that must be dropped.
chat_history = [
    {'role': 'user', 'parts': ['who are power users?']},
    {'role': 'model', 'parts': ['Here is the analysis.']},
    {'role': 'model', 'parts': []},  # tool-call protobuf stand-in -> dropped
]

# --- round-trip via the on-disk format (write serialized payload, load it) ---
payload = {
    'ui_history': P._serialize_ui_history(ui_history),
    'chat_history': P._serialize_chat_history(chat_history),
}
check(isinstance(payload['ui_history'][1]['data'], list), "chart DataFrame serialized to records")
json.dumps(payload)  # must be JSON-safe; raises if not
check(True, "payload is JSON-serializable")

os.makedirs(P.STATE_DIR, exist_ok=True)
with open(P.SESSION_FILE, 'w', encoding='utf-8') as f:
    json.dump(payload, f)

loaded_ui, loaded_chat = P.load_session()
check(loaded_ui is not None, "load_session found the file")
check(loaded_ui[0]['content'] == 'Hello there', "text message preserved")

restored_df = loaded_ui[1]['data']
check(isinstance(restored_df, pd.DataFrame), "chart data rebuilt into a DataFrame")
check(restored_df.equals(chart_df), "chart DataFrame round-trips exactly")

check(len(loaded_chat) == 2, "chat history keeps 2 text turns, drops tool-call turn")
check(loaded_chat[0] == {'role': 'user', 'parts': ['who are power users?']},
      "chat turn restored in start_chat format")

# --- clear ---
P.clear_session()
check(not os.path.exists(P.SESSION_FILE), "clear_session removed the file")

print()
if failures:
    print(f"FAILED ({len(failures)} check(s)).")
    sys.exit(1)
print("ALL CHECKS PASSED.")
