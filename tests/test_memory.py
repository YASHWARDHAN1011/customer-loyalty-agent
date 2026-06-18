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

    print(f"\n{_passed} checks passed.")


if __name__ == "__main__":
    main()
