"""
Chat session persistence.

Saves the chat so it survives an app restart. Two structures are stored to
.app_state/chat_session.json:

- ui_history : the rendered messages. `table`/`chart` entries carry a pandas
  DataFrame in `data`, which is converted to records for JSON and rebuilt into
  a DataFrame on load.
- chat_history : Gemini conversation Content objects. Only the text of each
  turn is kept (`{role, text}`); function-call/response protobufs are NOT
  round-tripped — on reload the conversation is text + charts, which is enough
  context for the agent to continue. (Accepted tradeoff.)

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


def _part_text(part):
    text = getattr(part, 'text', None)
    if text is None and isinstance(part, str):
        text = part
    return text or ''


def _serialize_chat_history(chat_history):
    out = []
    for content in chat_history or []:
        if isinstance(content, dict):
            role, parts = content.get('role'), content.get('parts', [])
        else:
            role, parts = getattr(content, 'role', None), getattr(content, 'parts', [])
        text = ''.join(_part_text(p) for p in (parts or []))
        if role in ('user', 'model') and text.strip():
            out.append({'role': role, 'text': text})
    return out


def _deserialize_chat_history(raw):
    # Gemini's start_chat accepts history as [{'role', 'parts': [text]}].
    return [{'role': e['role'], 'parts': [e['text']]} for e in (raw or []) if e.get('text')]


# ── Disk I/O ──────────────────────────────────────────────────────────────────

def save_session():
    """Write current ui_history + chat_history to disk (best-effort)."""
    if st is None:
        return
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        payload = {
            'ui_history': _serialize_ui_history(st.session_state.get('ui_history', [])),
            'chat_history': _serialize_chat_history(st.session_state.get('chat_history', [])),
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
    return (
        _deserialize_ui_history(payload.get('ui_history', [])),
        _deserialize_chat_history(payload.get('chat_history', [])),
    )


def clear_session():
    """Delete the saved session file (best-effort)."""
    try:
        os.remove(SESSION_FILE)
    except (FileNotFoundError, OSError):
        pass
