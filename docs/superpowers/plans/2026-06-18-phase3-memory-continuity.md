# Phase 3 — Memory / Continuity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the briefing a durable, cross-session memory so it can say "churn is still elevated since last session — and you already exported a target list."

**Architecture:** A new best-effort JSON store (`src/agent/memory.py`, mirroring `src/utils/persistence.py`) keeps the most recent briefing snapshot plus a log of deliverable actions. Pure functions diff current signals against the last snapshot and build a deterministic continuity line; `proactive.py` prepends that line to the digest before the LLM narrates it (under a new `MEMORY_SYSTEM`), and records the new snapshot. Deliverable tools log their actions; a sidebar button clears memory.

**Tech Stack:** Python, Streamlit (UI only), standalone test scripts (not pytest), Gemini caller via existing `generate()`. No new dependencies.

---

## Conventions (read once)

- **Tests are standalone scripts**, not pytest. Each defines a `check(name, cond)` that prints `PASS`/`FAIL` and `sys.exit(1)` on failure (copy the harness from `tests/test_proactive.py`).
- **Run tests** from the inner project dir (`customer-loyalty-agent/customer-loyalty-agent/`):
  `..\venv\Scripts\python.exe tests/test_memory.py`
- **Boot check** (used in the final task):
  `..\venv\Scripts\python.exe -c "import app"` is NOT enough; use the headless run used elsewhere — see Task 7.
- **Keep `src/agent/memory.py` Streamlit-free** (pure logic + plain file I/O). It must never raise: all disk ops wrapped in try/except, failures swallowed (same contract as `persistence.py`).
- **Real signal shape** (from `src/agent/insights.py`): each signal dict has `id` (one of `churn`, `segment_gap`, `intervention`, `power_value`, `happy_path`), `severity` (int 0–100), `icon`, `headline`, `detail`, `action_label`, `action_prompt`. We persist only `id`, `severity`, `headline`.
- **Real deliverable tool names** (from `src/agent/tools.py`): `export_target_list`, `draft_campaign_emails`, `build_action_plan`.

---

## File Structure

- **Create** `src/agent/memory.py` — the whole memory unit: store I/O + pure diff/continuity logic + the action→signal map.
- **Create** `tests/test_memory.py` — standalone tests for the above.
- **Modify** `src/config.py` — add `MEMORY_SYSTEM` prompt constant.
- **Modify** `src/agent/proactive.py` — load memory, diff, weave continuity line into narration, record snapshot. Add injection seams.
- **Modify** `tests/test_proactive.py` — inject no-op memory stubs so existing tests stay pure (no disk side-effects).
- **Modify** `src/agent/tools.py` — one `record_action(...)` line in each of the three deliverable tools.
- **Modify** `src/ui/sidebar.py` — add "Forget what you remember" button calling `clear_memory()`.
- **Modify** `CLAUDE.md` — dated Project Journal entry.

---

## Task 1: Memory module — pure logic (map, diff, continuity line)

Build the no-I/O core first so it's trivially testable.

**Files:**
- Create: `src/agent/memory.py`
- Test: `tests/test_memory.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_memory.py`:

```python
"""Standalone tests for src/agent/memory.py. No network, no Streamlit."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import memory as mem

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def _sig(sid, sev=50, head=None):
    return {"id": sid, "severity": sev, "headline": head or f"{sid} headline",
            "icon": "x", "detail": "d", "action_label": "a", "action_prompt": "p"}


def main():
    # --- ACTION_SIGNAL_MAP covers the three real tools ---
    check("map has export_target_list", "export_target_list" in mem.ACTION_SIGNAL_MAP)
    check("map has draft_campaign_emails", "draft_campaign_emails" in mem.ACTION_SIGNAL_MAP)
    check("map has build_action_plan", "build_action_plan" in mem.ACTION_SIGNAL_MAP)
    check("export maps to churn", "churn" in mem.ACTION_SIGNAL_MAP["export_target_list"])

    # --- diff_signals: no prior snapshot -> everything is 'new', nothing else ---
    empty_mem = {"last_snapshot": None, "action_log": []}
    d0 = mem.diff_signals([_sig("churn"), _sig("segment_gap")], empty_mem)
    check("no snapshot -> 2 new", len(d0["new"]) == 2)
    check("no snapshot -> 0 still_present", d0["still_present"] == [])
    check("no snapshot -> 0 resolved", d0["resolved"] == [])

    # --- diff_signals: new / still_present / resolved buckets ---
    prior = {
        "last_snapshot": {
            "when": "2026-06-10T00:00:00",
            "params": {"top_pct": 10, "churn_days": 30, "n": 6},
            "signals": [{"id": "churn", "severity": 80, "headline": "old churn"},
                        {"id": "segment_gap", "severity": 40, "headline": "old gap"}],
        },
        "action_log": [],
    }
    cur = [_sig("churn", 70), _sig("power_value", 30)]
    d1 = mem.diff_signals(cur, prior)
    check("still_present is churn", [s["id"] for s in d1["still_present"]] == ["churn"])
    check("new is power_value", [s["id"] for s in d1["new"]] == ["power_value"])
    check("resolved is segment_gap", [s["id"] for s in d1["resolved"]] == ["segment_gap"])

    # --- acted_on: action after snapshot, mapped to a present signal ---
    prior_acted = dict(prior)
    prior_acted["action_log"] = [
        {"action": "export_target_list", "when": "2026-06-12T00:00:00"},  # after snapshot, maps to churn
        {"action": "draft_campaign_emails", "when": "2026-06-01T00:00:00"},  # BEFORE snapshot -> ignored
    ]
    d2 = mem.diff_signals([_sig("churn")], prior_acted)
    churn_entry = d2["still_present"][0]
    check("churn acted_on True", churn_entry["acted_on"] is True)

    prior_noact = dict(prior); prior_noact["action_log"] = []
    d3 = mem.diff_signals([_sig("churn")], prior_noact)
    check("churn acted_on False when no action", d3["still_present"][0]["acted_on"] is False)

    # --- continuity_line ---
    check("continuity empty when no snapshot", mem.continuity_line(d0) == "")
    line = mem.continuity_line(d2)
    check("continuity is a string", isinstance(line, str) and line.startswith("Since last session"))
    check("continuity mentions acted", "already acted" in line)

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_memory.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.agent.memory'` (or `AttributeError`).

- [ ] **Step 3: Write minimal implementation**

Create `src/agent/memory.py` (pure logic only for now):

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_memory.py`
Expected: PASS — all checks pass, prints "N checks passed."

- [ ] **Step 5: Commit**

```bash
git add src/agent/memory.py tests/test_memory.py
git commit -m "Phase 3: memory pure logic — diff_signals + continuity_line"
```

---

## Task 2: Memory module — disk I/O (load / record / clear)

Add the best-effort persistence layer beneath the pure logic.

**Files:**
- Modify: `src/agent/memory.py` (append I/O functions)
- Test: `tests/test_memory.py` (add a second test block)

- [ ] **Step 1: Write the failing test**

Append this block to `tests/test_memory.py` `main()`, just before the final `print`:

```python
    # --- disk I/O round-trip in a temp path ---
    import tempfile
    tmp = os.path.join(tempfile.mkdtemp(), "agent_memory.json")

    # absent file -> well-formed empty default
    d_empty = mem.load_memory(path=tmp)
    check("absent -> default shape",
          d_empty == {"last_snapshot": None, "action_log": []})

    # record a snapshot, read it back
    sigs = [_sig("churn", 80), _sig("segment_gap", 40)]
    params = {"top_pct": 10, "churn_days": 30, "n": 6}
    mem.record_snapshot(sigs, params, path=tmp)
    loaded = mem.load_memory(path=tmp)
    check("snapshot persisted", loaded["last_snapshot"]["params"] == params)
    check("snapshot trims fields",
          set(loaded["last_snapshot"]["signals"][0].keys()) == {"id", "severity", "headline"})

    # overwrite guard: same params -> no change; the 'when' stays put
    first_when = loaded["last_snapshot"]["when"]
    mem.record_snapshot([_sig("churn", 10)], params, path=tmp)  # same params
    guarded = mem.load_memory(path=tmp)
    check("same params -> snapshot unchanged",
          guarded["last_snapshot"]["when"] == first_when
          and len(guarded["last_snapshot"]["signals"]) == 2)

    # changed params -> overwrite
    mem.record_snapshot([_sig("churn", 10)], {"top_pct": 20, "churn_days": 30, "n": 6}, path=tmp)
    changed = mem.load_memory(path=tmp)
    check("changed params -> overwrite", changed["last_snapshot"]["params"]["top_pct"] == 20)

    # record_action appends with a timestamp
    mem.record_action("export_target_list", path=tmp, now="2026-06-18T12:00:00")
    after = mem.load_memory(path=tmp)
    check("action logged", after["action_log"][-1]["action"] == "export_target_list")
    check("action has when", after["action_log"][-1]["when"] == "2026-06-18T12:00:00")

    # clear wipes the file
    mem.clear_memory(path=tmp)
    check("cleared -> default", mem.load_memory(path=tmp) == {"last_snapshot": None, "action_log": []})

    # best-effort: corrupt file -> default, never raises
    with open(tmp, "w", encoding="utf-8") as f:
        f.write("{ not json")
    check("corrupt -> default", mem.load_memory(path=tmp) == {"last_snapshot": None, "action_log": []})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_memory.py`
Expected: FAIL — `AttributeError: module 'src.agent.memory' has no attribute 'load_memory'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/agent/memory.py`:

```python
# ── Disk I/O (best-effort; never raises) ──────────────────────────────────────

STATE_DIR = ".app_state"
MEMORY_FILE = os.path.join(STATE_DIR, "agent_memory.json")

_DEFAULT = {"last_snapshot": None, "action_log": []}


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_memory.py`
Expected: PASS — all checks pass.

- [ ] **Step 5: Commit**

```bash
git add src/agent/memory.py tests/test_memory.py
git commit -m "Phase 3: memory disk I/O — load/record_snapshot/record_action/clear"
```

---

## Task 3: Add `MEMORY_SYSTEM` prompt to config

**Files:**
- Modify: `src/config.py` (add constant after `PROACTIVE_SYSTEM`)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_memory.py` `main()` before the final `print`:

```python
    # --- MEMORY_SYSTEM prompt exists and forbids invention ---
    from src.config import MEMORY_SYSTEM
    check("MEMORY_SYSTEM is non-empty str",
          isinstance(MEMORY_SYSTEM, str) and len(MEMORY_SYSTEM) > 50)
    check("MEMORY_SYSTEM mentions since last session",
          "since last session" in MEMORY_SYSTEM.lower())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_memory.py`
Expected: FAIL — `ImportError: cannot import name 'MEMORY_SYSTEM'`.

- [ ] **Step 3: Write minimal implementation**

In `src/config.py`, immediately after the `PROACTIVE_SYSTEM = """ ... """` block, add:

```python
MEMORY_SYSTEM = """
You are a proactive customer-loyalty analyst opening the conversation with a
busy operator you have briefed before. You are given a digest of detected
signals (each with exact numbers already computed for you) and, when available,
a "Since last session:" continuity note describing what changed since you last
spoke.

Write a 2-3 sentence briefing in the confident voice of a senior consultant.

HARD RULES:
- Use ONLY numbers that appear in the digest. Never invent, round differently,
  or extrapolate a figure that is not given.
- You may reference continuity ONLY as stated in the "Since last session:" note.
  Never invent prior sessions, dates, actions, or outcomes that are not in it.
  If no continuity note is given, do not imply you have spoken before.
- Weave continuity naturally into the narrative; do not restate the note verbatim.
- End with the single most urgent recommendation, phrased as a clear next step.

Do not use headers, bullet points, or markdown — just the briefing prose.
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_memory.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/config.py tests/test_memory.py
git commit -m "Phase 3: add MEMORY_SYSTEM continuity-aware narration prompt"
```

---

## Task 4: Wire memory into the briefing (`proactive.py`)

Load memory, diff against the snapshot, prepend the continuity line to the
narration, narrate under `MEMORY_SYSTEM`, and record the new snapshot — with
injection seams so tests stay pure (no disk).

**Files:**
- Modify: `src/agent/proactive.py`
- Modify: `tests/test_proactive.py` (inject no-op memory stubs + add continuity assertions)

- [ ] **Step 1: Write the failing test**

In `tests/test_proactive.py`, update the existing `get_briefing(...)` calls to inject memory stubs, and add continuity coverage. Replace the body of `main()` with:

```python
def main():
    # no-op memory seams keep these tests off disk
    empty_mem = {"last_snapshot": None, "action_log": []}
    load_noop = lambda: empty_mem
    rec_calls = {"n": 0}
    def rec_noop(signals, params):
        rec_calls["n"] += 1

    # --- not ready before analysis has run ---
    empty = get_briefing(state={}, generate_fn=_counting_stub("x")[0],
                         load_memory_fn=load_noop, record_snapshot_fn=rec_noop)
    check("empty state -> not ready", empty["ready"] is False)
    check("empty state -> no signals", empty["signals"] == [])

    # --- ready path: narrates via the injected model ---
    gen, calls = _counting_stub("Churn is your top threat today.")
    state = _state()
    out = get_briefing(state=state, generate_fn=gen,
                       load_memory_fn=load_noop, record_snapshot_fn=rec_noop)
    check("ready when scored", out["ready"] is True)
    check("returns signals", len(out["signals"]) >= 1)
    check("narrative is the model text",
          out["narrative"] == "Churn is your top threat today.")
    check("model called once", calls["n"] == 1)
    check("snapshot recorded once", rec_calls["n"] == 1)

    # --- caching: same inputs must not re-call the model OR re-record ---
    out2 = get_briefing(state=state, generate_fn=gen,
                        load_memory_fn=load_noop, record_snapshot_fn=rec_noop)
    check("cache hit -> model not called again", calls["n"] == 1)
    check("cache hit -> snapshot not re-recorded", rec_calls["n"] == 1)
    check("cache returns same narrative", out2["narrative"] == out["narrative"])

    # --- continuity line is passed to the model when memory has a prior snapshot ---
    captured = {"prompt": None}
    def capture_gen(prompt, *, system_instruction, tools=None, history=None,
                    automatic_function_calling=False):
        captured["prompt"] = prompt
        return {"text": "ok", "model_label": "stub", "chat": None}
    prior_mem = {
        "last_snapshot": {"when": "2026-06-10T00:00:00",
                          "params": {"top_pct": 10, "churn_days": 30, "n": 6},
                          "signals": [{"id": "power_value", "severity": 5,
                                       "headline": "old"}]},
        "action_log": [],
    }
    fresh2 = _state()
    get_briefing(state=fresh2, generate_fn=capture_gen,
                 load_memory_fn=lambda: prior_mem, record_snapshot_fn=rec_noop)
    check("continuity line reaches the model",
          captured["prompt"] is not None and "Since last session" in captured["prompt"])

    # --- LLM failure falls back to a deterministic narrative, never crashes ---
    fresh = _state()
    out3 = get_briefing(state=fresh, generate_fn=_boom_stub,
                        load_memory_fn=load_noop, record_snapshot_fn=rec_noop)
    check("fallback: still ready", out3["ready"] is True)
    check("fallback: non-empty narrative",
          isinstance(out3["narrative"], str) and len(out3["narrative"]) > 0)

    # --- _fallback_narrative is pure and references the top signal ---
    fb = _fallback_narrative(out["signals"])
    check("fallback narrative is a string", isinstance(fb, str))
    check("fallback mentions top headline", out["signals"][0]["headline"] in fb)

    print(f"\n{_passed} checks passed.")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `..\venv\Scripts\python.exe tests/test_proactive.py`
Expected: FAIL — `get_briefing()` got an unexpected keyword `load_memory_fn` (and/or continuity assertion fails).

- [ ] **Step 3: Write minimal implementation**

Edit `src/agent/proactive.py`:

1. Update imports near the top:

```python
from src.config import MEMORY_SYSTEM
from src.agent.caller import generate
from src.agent.insights import detect_signals, briefing_digest
from src.agent.memory import (
    load_memory, record_snapshot, diff_signals, continuity_line,
)
```

(Remove the old `from src.config import PROACTIVE_SYSTEM` import — it is replaced by `MEMORY_SYSTEM`.)

2. Update `_fallback_narrative` to accept an optional continuity prefix:

```python
def _fallback_narrative(signals, continuity=""):
    """Deterministic briefing used when the LLM is unavailable.

    Pure — references only already-computed signal headlines/details (+ the
    deterministic continuity line), so it stays grounded like the model path.
    """
    if not signals:
        return "Analysis is ready, but nothing stands out as urgent right now."
    top = signals[0]
    lead = f"{top['headline']}. {top['detail']}."
    if len(signals) > 1:
        others = "; ".join(s["headline"] for s in signals[1:])
        lead += f" Also worth your attention: {others}."
    lead += f" Start here: {top['action_label'].lower()}."
    return f"{continuity} {lead}".strip() if continuity else lead
```

3. Update `_narrate` to weave the continuity line in and use `MEMORY_SYSTEM`:

```python
def _narrate(signals, generate_fn, continuity=""):
    """Narrate the signal digest (with continuity) via the LLM; fall back safely."""
    digest = briefing_digest(signals)
    prompt = f"{continuity}\n\n{digest}" if continuity else digest
    try:
        result = generate_fn(prompt, system_instruction=MEMORY_SYSTEM)
        text = (result.get("text") or "").strip()
        if not text:
            raise ValueError("empty narration")
        return text
    except Exception:
        return _fallback_narrative(signals, continuity)
```

4. Rewrite `get_briefing` signature and body:

```python
def get_briefing(*, generate_fn=generate, state=None,
                 load_memory_fn=load_memory, record_snapshot_fn=record_snapshot):
    """Build the proactive, continuity-aware briefing from the current session.

    Returns {"ready": bool, "signals": list[dict], "narrative": str}.
    `state`, `generate_fn`, `load_memory_fn`, and `record_snapshot_fn` are
    injectable for testing; in the app they default to st.session_state, the real
    Gemini caller, and the real memory store.
    """
    state = st.session_state if state is None else state

    scored_df = state.get("scored_df")
    if scored_df is None or len(scored_df) == 0:
        return {"ready": False, "signals": [], "narrative": ""}

    top_pct = state.get("top_pct", 10)
    signals = detect_signals(
        state.get("features"),
        scored_df,
        state.get("power"),
        state.get("regular"),
        state.get("power_user_ids") or set(),
        state.get("full_data"),
        churn_days=CHURN_DAYS,
        top_pct=top_pct,
    )

    if not signals:
        return {
            "ready": True,
            "signals": [],
            "narrative": _fallback_narrative(signals),
        }

    # Cache the narrative so reruns don't re-call the model. Key on the inputs
    # that actually change what we'd say.
    cache_key = (top_pct, CHURN_DAYS, len(scored_df))
    cached = state.get("_briefing_cache")
    if cached and cached.get("key") == cache_key:
        narrative = cached["narrative"]
    else:
        memory = load_memory_fn()
        params = {"top_pct": top_pct, "churn_days": CHURN_DAYS, "n": len(scored_df)}
        continuity = continuity_line(diff_signals(signals, memory))
        narrative = _narrate(signals, generate_fn, continuity)
        record_snapshot_fn(signals, params)
        state["_briefing_cache"] = {"key": cache_key, "narrative": narrative}

    return {"ready": True, "signals": signals, "narrative": narrative}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `..\venv\Scripts\python.exe tests/test_proactive.py`
Expected: PASS — all checks pass (including the new snapshot + continuity checks).

Run: `..\venv\Scripts\python.exe tests/test_memory.py`
Expected: PASS (still green).

- [ ] **Step 5: Commit**

```bash
git add src/agent/proactive.py tests/test_proactive.py
git commit -m "Phase 3: weave continuity into the briefing + record snapshot"
```

---

## Task 5: Log deliverable actions (`tools.py`)

Record each deliverable action so the diff can mark signals as acted-on.

**Files:**
- Modify: `src/agent/tools.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_memory.py` `main()` before the final `print` — assert the three tool names are mapped (a lightweight guard that the wiring targets real tools; the wiring itself is exercised manually + by the boot check, since `tools.py` requires Streamlit runtime):

```python
    # --- the actions we log from tools.py are all in the map ---
    for tool_name in ("export_target_list", "draft_campaign_emails", "build_action_plan"):
        check(f"{tool_name} mapped", tool_name in mem.ACTION_SIGNAL_MAP)
```

- [ ] **Step 2: Run test to verify it fails or passes**

Run: `..\venv\Scripts\python.exe tests/test_memory.py`
Expected: PASS (the map already covers these from Task 1). This step documents the contract the tool edits must honor; no failure expected.

- [ ] **Step 3: Write minimal implementation**

In `src/agent/tools.py`:

1. Add to the imports block (near `from src.agent.deliverables import ...`):

```python
from src.agent import memory
```

2. In `export_target_list`, immediately after the successful `_add_artifact(...)` call (right before `return {`), add:

```python
    memory.record_action("export_target_list")
```

3. In `draft_campaign_emails`, immediately after its `_add_artifact(...)` call, add:

```python
    memory.record_action("draft_campaign_emails")
```

4. In `build_action_plan`, immediately after its `_add_artifact(...)` call, add:

```python
    memory.record_action("build_action_plan")
```

(Place each call after the artifact is created so we only log actions that actually produced a deliverable. `record_action` is best-effort and never raises.)

- [ ] **Step 4: Run test to verify it passes**

Run: `..\venv\Scripts\python.exe tests/test_memory.py`
Expected: PASS.
Run: `..\venv\Scripts\python.exe -c "import ast; ast.parse(open('src/agent/tools.py').read()); print('tools.py parses')"`
Expected: prints `tools.py parses`.

- [ ] **Step 5: Commit**

```bash
git add src/agent/tools.py tests/test_memory.py
git commit -m "Phase 3: log deliverable actions to agent memory"
```

---

## Task 6: "Forget what you remember" button (`sidebar.py`)

**Files:**
- Modify: `src/ui/sidebar.py`

- [ ] **Step 1: Write the implementation (UI — verified via boot check, no unit test)**

In `src/ui/sidebar.py`:

1. Add to imports at the top:

```python
from src.agent.memory import clear_memory
```

2. Replace the existing two-column Replay/Reset block (the `c_replay, c_reset = st.columns(2)` section near the end) with a version that adds the forget button beneath it:

```python
        st.divider()
        c_replay, c_reset = st.columns(2)
        with c_replay:
            if st.button("🧭 Replay tour", use_container_width=True):
                start_tour()
                st.rerun()
        with c_reset:
            if st.button("🔄 Reset", use_container_width=True):
                keep = {'model_idx', 'features', 'full_data', 'weights', 'top_pct'}
                for k in list(st.session_state.keys()):
                    if k not in keep:
                        del st.session_state[k]
                st.rerun()

        if st.button("🧠 Forget what you remember", use_container_width=True):
            clear_memory()
            st.session_state.pop('_briefing_cache', None)
            st.toast("Cleared the agent's cross-session memory.")
            st.rerun()
```

(Clearing `_briefing_cache` forces the next briefing to recompute against the now-empty memory.)

- [ ] **Step 2: Verify the module parses**

Run: `..\venv\Scripts\python.exe -c "import ast; ast.parse(open('src/ui/sidebar.py').read()); print('sidebar.py parses')"`
Expected: prints `sidebar.py parses`.

- [ ] **Step 3: Commit**

```bash
git add src/ui/sidebar.py
git commit -m "Phase 3: add 'Forget what you remember' sidebar button"
```

---

## Task 7: Journal entry + full verification

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add the Project Journal entry**

At the TOP of the `## 📓 Project Journal` section in `CLAUDE.md` (above the 2026-06-16 entry), add:

```markdown
### 2026-06-18 — Proactive Analyst, Phase 3: Memory / Continuity
Gave the briefing a durable, cross-session memory so it stops being amnesiac.
- **`src/agent/memory.py`** (NEW, Streamlit-free, best-effort like
  `persistence.py`): a JSON store at `.app_state/agent_memory.json` holding the
  last briefing `snapshot` (signal id/severity/headline + params + when) and an
  `action_log`. Pure logic: `diff_signals` (new / still_present / resolved, each
  with an `acted_on` flag via `ACTION_SIGNAL_MAP`) and `continuity_line`
  ("Since last session: churn risk is still present (you've already acted on
  it)…"). I/O: `load_memory`, `record_snapshot` (overwrite-guarded by params),
  `record_action`, `clear_memory`.
- **`src/config.py`**: added `MEMORY_SYSTEM` — narrate continuity ONLY from the
  given note, never invent prior sessions.
- **`src/agent/proactive.py`**: `get_briefing` now loads memory, diffs, prepends
  the deterministic continuity line to the digest, narrates under
  `MEMORY_SYSTEM`, and records the new snapshot — all on the cache-miss path, so
  reruns neither re-call the model nor re-record. New `load_memory_fn`/
  `record_snapshot_fn` seams keep tests off disk.
- **`src/agent/tools.py`**: the three deliverable tools log their action.
- **`src/ui/sidebar.py`**: "🧠 Forget what you remember" button clears memory.
- Tests: `tests/test_memory.py` (pure logic + disk round-trip), updated
  `tests/test_proactive.py` (continuity + snapshot). No network. App boots
  headless HTTP 200.
- Provider stays Gemini-only; provider abstraction is still Phase 5.
```

- [ ] **Step 2: Run the full no-network test suite**

Run each; each must print its passing summary and exit 0:

```
..\venv\Scripts\python.exe tests/test_memory.py
..\venv\Scripts\python.exe tests/test_proactive.py
..\venv\Scripts\python.exe tests/test_insights.py
..\venv\Scripts\python.exe tests/test_orchestrator.py
..\venv\Scripts\python.exe tests/test_reflexive.py
..\venv\Scripts\python.exe tests/test_deliverables.py
..\venv\Scripts\python.exe tests/test_persistence.py
```

Expected: all PASS.

- [ ] **Step 3: Boot the app headless and confirm HTTP 200**

Run (PowerShell), then check it serves:

```powershell
Start-Process -NoNewWindow ..\venv\Scripts\python.exe `
  -ArgumentList "-m","streamlit","run","app.py","--server.headless","true","--server.port","8599"
Start-Sleep -Seconds 12
(Invoke-WebRequest http://localhost:8599 -UseBasicParsing).StatusCode
```

Expected: `200`. Then stop the process:

```powershell
Get-Process python | Where-Object { $_.Path -like "*venv*" } | Stop-Process -Force
```

(If port 8599 is busy, pick another free port.)

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "Phase 3: journal entry for Memory/Continuity"
```

---

## Self-Review (completed by plan author)

**Spec coverage:**
- Store + shape (`agent_memory.json`, last_snapshot + action_log) → Task 2. ✓
- `load_memory` / `record_snapshot` (param overwrite guard) / `record_action` / `diff_signals` / `continuity_line` / `clear_memory` → Tasks 1–2. ✓
- Action→signal map → Task 1 (`ACTION_SIGNAL_MAP`), verified against real tool names in Task 5. ✓
- `MEMORY_SYSTEM` grounding prompt → Task 3. ✓
- Briefing data flow (load → diff → continuity → narrate → record, on cache-miss) → Task 4. ✓
- Tools record actions → Task 5. ✓
- "Forget" button → Task 6. ✓
- Tests `tests/test_memory.py` + green suite + HTTP 200 + journal → Tasks 1–7. ✓

**Placeholder scan:** none — every code/test step shows complete content. ✓

**Type consistency:** signal entries persist `{id, severity, headline}` everywhere; `diff_signals` returns buckets of `{id, severity, headline, acted_on}`; `get_briefing` seams named `load_memory_fn`/`record_snapshot_fn` consistently across `proactive.py` and `test_proactive.py`; tool names match `ACTION_SIGNAL_MAP` keys. ✓

**Note on the overwrite guard:** with identical params across same-config sessions the snapshot stays fixed at first-seen (stable "since you first looked" baseline), as reviewed and approved in the spec. Changing top_pct/churn-days establishes a new baseline.
