"""Standalone tests for src/agent/proactive.py.

No network, no Streamlit runtime: generate is injected as a stub and the
session is a plain dict passed via the `state` seam.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

from src.agent.proactive import get_briefing, _fallback_narrative

_passed = 0
def check(name, cond):
    global _passed
    if cond:
        print(f"PASS  {name}"); _passed += 1
    else:
        print(f"FAIL  {name}"); sys.exit(1)


def _counting_stub(text):
    """generate-compatible stub that records how many times it was called."""
    calls = {"n": 0}
    def _g(prompt, *, system_instruction, tools=None, history=None,
           automatic_function_calling=False):
        calls["n"] += 1
        return {"text": text, "model_label": "stub", "chat": None}
    return _g, calls


def _boom_stub(prompt, *, system_instruction, tools=None, history=None,
               automatic_function_calling=False):
    raise RuntimeError("model exhausted")


def _state():
    features = pd.DataFrame({
        'user_id':                [1, 2, 3, 4, 5, 6],
        'total_orders':           [40, 35, 8, 12, 5, 10],
        'avg_days_between_orders': [10, 40, 50, 20, 60, 15],
        'reorder_rate':           [0.85, 0.80, 0.20, 0.30, 0.10, 0.25],
        'dept_diversity':         [16, 14, 4, 6, 3, 5],
        'avg_basket_size':        [13.0, 12.0, 4.0, 5.0, 3.0, 4.5],
        'total_items':            [520, 420, 32, 60, 15, 45],
    })
    scored_df = features.copy()
    scored_df['loyalty_score'] = [95.0, 88.0, 30.0, 40.0, 12.0, 28.0]
    power = features[features['user_id'].isin([1, 2])].copy()
    regular = features[features['user_id'].isin([3, 4, 5, 6])].copy()
    return {
        'features': features,
        'scored_df': scored_df,
        'power': power,
        'regular': regular,
        'power_user_ids': {1, 2},
        'full_data': pd.DataFrame(
            columns=['user_id', 'order_number', 'department']),
        'top_pct': 10,
    }


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


if __name__ == "__main__":
    main()
