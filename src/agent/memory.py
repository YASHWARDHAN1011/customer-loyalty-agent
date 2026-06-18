"""
Agent memory — durable, cross-session business memory for the briefing.

Distinct from src/utils/persistence.py (which saves the current chat transcript).
This module remembers, across separate sessions:
  - last_snapshot: the signals the briefing last surfaced (+ when, + the analysis
    params), so a new session can diff current-vs-last.
  - action_log: lightweight {action, when} entries for deliverable tools the user
    ran, so the diff can mark a still-present signal as already acted on.

Pure logic lives up top (no Streamlit, no disk); file I/O is at the bottom and is
best-effort — it must never crash the app.
"""

import json
import os
from datetime import datetime

# Which signal categories each deliverable action counts against. Used ONLY to
# set the `acted_on` flag in diff_signals. Keys are the real tool names in
# src/agent/tools.py; values are signal ids from src/agent/insights.py.
ACTION_SIGNAL_MAP = {
    "export_target_list": {"churn", "intervention"},
    "build_action_plan": {"churn", "intervention"},
    "draft_campaign_emails": {"segment_gap", "churn"},
}

# Stable, readable labels for continuity prose (headlines carry live numbers and
# would change every run, so we phrase continuity by signal id instead).
SIGNAL_LABELS = {
    "churn": "churn risk",
    "segment_gap": "the power/regular gap",
    "intervention": "the top conversion opportunity",
    "power_value": "your power-user core",
    "happy_path": "the happy-path drop-off",
}


def _trim(signal):
    """Keep only the stable fields worth persisting/diffing."""
    return {"id": signal["id"], "severity": signal["severity"],
            "headline": signal["headline"]}


def _acted_on(signal_id, memory):
    """True if a logged action mapped to this signal happened after the snapshot."""
    snap = memory.get("last_snapshot")
    since = snap.get("when") if snap else ""
    for entry in memory.get("action_log", []):
        cats = ACTION_SIGNAL_MAP.get(entry.get("action"), set())
        # ISO timestamps sort lexicographically, so a string compare is valid.
        if signal_id in cats and entry.get("when", "") >= (since or ""):
            return True
    return False


def diff_signals(current_signals, memory):
    """Bucket current signals vs the last snapshot in `memory`.

    Returns {"new": [...], "still_present": [...], "resolved": [...]}. Each entry
    is {id, severity, headline, acted_on}. With no prior snapshot, every current
    signal is 'new' and the other buckets are empty.
    """
    snap = (memory or {}).get("last_snapshot")
    prior = {s["id"]: s for s in (snap.get("signals", []) if snap else [])}
    cur = {s["id"]: s for s in current_signals}

    def _entry(sig):
        return {"id": sig["id"], "severity": sig["severity"],
                "headline": sig["headline"],
                "acted_on": _acted_on(sig["id"], memory or {})}

    new = [_entry(s) for s in current_signals if s["id"] not in prior]
    still = [_entry(s) for s in current_signals if s["id"] in prior]
    resolved = [{"id": s["id"], "severity": s["severity"],
                 "headline": s["headline"],
                 "acted_on": _acted_on(s["id"], memory or {})}
                for sid, s in prior.items() if sid not in cur]
    return {"new": new, "still_present": still, "resolved": resolved}


def continuity_line(diff):
    """Deterministic one-line continuity summary for the narrator. '' if no prior."""
    if not diff or (not diff["still_present"] and not diff["resolved"]
                    and not diff["new"]):
        return ""
    # No prior snapshot => only 'new' is populated and there's nothing to compare.
    if not diff["still_present"] and not diff["resolved"]:
        return ""

    parts = []
    for s in diff["still_present"]:
        label = SIGNAL_LABELS.get(s["id"], s["id"])
        if s["acted_on"]:
            parts.append(f"{label} is still present (you've already acted on it)")
        else:
            parts.append(f"{label} is still present")
    for s in diff["resolved"]:
        label = SIGNAL_LABELS.get(s["id"], s["id"])
        parts.append(f"{label} has resolved")
    if diff["new"]:
        n = len(diff["new"])
        parts.append(f"{n} new signal{'s' if n != 1 else ''}")
    return "Since last session: " + "; ".join(parts) + "."


# ── Disk I/O (best-effort; never raises) ──────────────────────────────────────

STATE_DIR = ".app_state"
MEMORY_FILE = os.path.join(STATE_DIR, "agent_memory.json")


def load_memory(path=MEMORY_FILE):
    """Return the stored memory dict, or a fresh default if absent/corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"last_snapshot": None, "action_log": []}
        data.setdefault("last_snapshot", None)
        data.setdefault("action_log", [])
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {"last_snapshot": None, "action_log": []}


def _save(data, path):
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception:
        pass


def record_snapshot(signals, params, path=MEMORY_FILE):
    """Write current signals + params as the last snapshot.

    Overwrite guard: if a snapshot already exists with identical `params`, leave
    it untouched so the baseline stays stable across same-config sessions and
    intra-session reruns never wipe it.
    """
    data = load_memory(path=path)
    snap = data.get("last_snapshot")
    if snap and snap.get("params") == params:
        return
    data["last_snapshot"] = {
        "when": datetime.now().isoformat(timespec="seconds"),
        "params": params,
        "signals": [_trim(s) for s in (signals or [])],
    }
    _save(data, path)


def record_action(action_name, path=MEMORY_FILE, now=None):
    """Append a {action, when} entry to the action log (best-effort)."""
    data = load_memory(path=path)
    data["action_log"].append({
        "action": action_name,
        "when": now or datetime.now().isoformat(timespec="seconds"),
    })
    _save(data, path)


def clear_memory(path=MEMORY_FILE):
    """Delete the memory file (best-effort)."""
    try:
        os.remove(path)
    except (FileNotFoundError, OSError):
        pass
