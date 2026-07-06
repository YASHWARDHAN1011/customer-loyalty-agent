"""
Chat session persistence.

Saves the chat so it survives an app restart. Two structures are stored to
.app_state/chat_session.json:

- ui_history : the rendered messages. `table`/`chart` entries carry a pandas
  DataFrame in `data`, which is converted to records for JSON and rebuilt into
  a DataFrame on load.
- chat_history : the Phase-4.5 neutral message list — plain JSON already
  (`{role, content:[{type,...}]}` text / tool_call / tool_result blocks). Saved
  as-is and restored as-is. A pre-4.5 saved session (old Gemini `{role, text}`
  shape) is discarded on load so the tool loop never sees an incompatible shape.

All operations are best-effort: persistence must never crash the app.
"""

import json
import os

import pandas as pd

try:
    import streamlit as st
except Exception:  # pragma: no cover - allows importing in a bare test process
    st = None

STATE_DIR = '.app_state'
SESSION_FILE = os.path.join(STATE_DIR, 'chat_session.json')

_DATA_TYPES = ('table', 'chart')


# ── Serialization (pure, no Streamlit) ────────────────────────────────────────

def _serialize_ui_history(ui_history):
    out = []
    for msg in ui_history or []:
        e = {'role': msg.get('role'), 'type': msg.get('type')}
        if msg.get('type') == 'text':
            e['content'] = msg.get('content', '')
        else:
            data = msg.get('data')
            e['data'] = data.to_dict('records') if isinstance(data, pd.DataFrame) else data
            for k in ('title', 'chart_type', 'x', 'y', 'color'):
                if k in msg:
                    e[k] = msg[k]
        out.append(e)
    return out


def _deserialize_ui_history(raw):
    out = []
    for e in raw or []:
        msg = dict(e)
        if msg.get('type') in _DATA_TYPES and isinstance(msg.get('data'), list):
            msg['data'] = pd.DataFrame(msg['data'])
        out.append(msg)
    return out


def is_neutral_history(history):
    """True if `history` is the Phase-4.5 neutral message list.

    Neutral = list of {"role","content":[blocks]} where each block is a dict
    with a "type". Guards restore against pre-4.5 saved sessions (old Gemini
    `{role, text}` shape), which are discarded rather than replayed.
    """
    if not isinstance(history, list):
        return False
    for m in history:
        if not isinstance(m, dict) or "content" not in m or "role" not in m:
            return False
        if not isinstance(m["content"], list):
            return False
        if not all(isinstance(b, dict) and "type" in b for b in m["content"]):
            return False
    return True


# ── Disk I/O ──────────────────────────────────────────────────────────────────

def save_session():
    """Write current ui_history + chat_history to disk (best-effort)."""
    if st is None:
        return
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        chat = st.session_state.get('chat_history', [])
        payload = {
            'ui_history': _serialize_ui_history(st.session_state.get('ui_history', [])),
            # Neutral history is already JSON-safe; store it verbatim.
            'chat_history': chat if is_neutral_history(chat) else [],
        }
        with open(SESSION_FILE, 'w', encoding='utf-8') as f:
            json.dump(payload, f)
    except Exception:
        pass


def load_session():
    """Return (ui_history, chat_history) from disk, or (None, None) if absent."""
    try:
        with open(SESSION_FILE, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None, None
    saved_chat = payload.get('chat_history', [])
    if not is_neutral_history(saved_chat):
        saved_chat = []  # discard incompatible pre-4.5 history (best-effort)
    return (
        _deserialize_ui_history(payload.get('ui_history', [])),
        saved_chat,
    )


def clear_session():
    """Delete the saved session file (best-effort)."""
    try:
        os.remove(SESSION_FILE)
    except (FileNotFoundError, OSError):
        pass
