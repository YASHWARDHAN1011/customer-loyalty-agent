# Memory / Continuity — Design

**Date:** 2026-06-18
**Phase:** Proactive Analyst roadmap, Phase 3 (Memory / Continuity)
**Status:** Approved design, pre-implementation

## Goal

Give the agent a durable memory of *this* business across separate sessions, so
it stops being analytically amnesiac. Today the briefing (Phase 1) and Autopilot
(Phase 2) are sharp in the moment but forget everything between sessions — if
churn was the #1 issue last week and you ran a campaign about it, the agent
re-flags it as if nothing happened.

Phase 3 makes the briefing **continuity-aware**: "churn is still elevated since
you flagged it last session — and you already exported a target list, but the gap
hasn't closed." Memory only earns its place by feeding back into reasoning;
a file that just accumulates facts is not the goal.

This is distinct from `src/utils/persistence.py`, which saves the *current chat
transcript* so one conversation survives a restart. Phase 3 is durable
business-level memory that persists across totally separate sessions.

## Decisions locked during brainstorming

- **What to remember (lean):** signals the briefing surfaced + actions you took.
  No preferences modeling, no full run journal.
- **Continuity model:** last snapshot only. Each session diffs current signals
  against the most recent snapshot (new / still-present / resolved). No rolling
  history, no trend-over-N-sessions.
- **Mechanism (Approach A):** generic action log with fuzzy linking. Tools record
  *that* an action happened; the diff links action-type → signal-category to set
  an `acted_on` flag. No per-signal causal IDs threaded through the agent path.
- **Surface:** continuity phrasing woven into the briefing narrative + a "Forget
  what you remember" button. No dedicated panel, no new tab.
- **Provider:** Gemini-only. Provider abstraction remains Phase 5.

## Architecture

New module `src/agent/memory.py` — best-effort, never crashes the app (same
contract as `persistence.py`: all disk ops wrapped, failures swallowed). Backed
by `.app_state/agent_memory.json`.

The pure logic (diffing, time-filtering, serialization) stays Streamlit-free and
independently testable; only the read/write helpers touch the filesystem.

### Stored shape (`.app_state/agent_memory.json`)

```json
{
  "last_snapshot": {
    "when": "2026-06-18T14:03:00",
    "params": {"top_pct": 10, "churn_days": 30, "n": 206209},
    "signals": [
      {"id": "churn", "severity": 5, "headline": "..."},
      {"id": "segment_gap", "severity": 4, "headline": "..."}
    ]
  },
  "action_log": [
    {"action": "export_target_list", "when": "2026-06-16T09:10:00"}
  ]
}
```

`signals` stores only the stable, deterministic fields of a detected signal
(`id`, `severity`, `headline`) — enough to diff and narrate, nothing the LLM
could treat as a live number.

### Public functions

- `load_memory() -> dict` — returns the stored dict, or a well-formed empty
  default `{"last_snapshot": None, "action_log": []}` if absent/corrupt.
- `record_snapshot(signals, params)` — writes the current signals + params as the
  new `last_snapshot`. **Overwrite guard:** only writes when `params` differs from
  the loaded snapshot's `params`, so re-renders within one session do not wipe the
  "since last time" baseline.
- `record_action(action_name)` — appends `{action, when}` to `action_log`.
- `diff_signals(current, last) -> dict` — pure. Returns buckets:
  - `new`: signals present now, absent in `last`.
  - `still_present`: present in both.
  - `resolved`: present in `last`, absent now.
  Each entry carries `acted_on: bool` — true when a relevant action sits in
  `action_log` dated after `last_snapshot.when` (see action→signal map below).
- `continuity_line(diff) -> str` — pure. Builds the deterministic plain-text
  summary handed to the narrator, e.g. *"Since last session: churn still elevated
  (you exported a target list); segment gap resolved; 1 new signal."* Returns an
  empty string when there is no prior snapshot (first run).
- `clear_memory()` — deletes the file (best-effort).

### Action → signal map

A small static dict used **only** to compute `acted_on`:

| Action (tool)          | Linked signal categories       |
|------------------------|--------------------------------|
| `export_target_list`   | `churn`, `intervention`        |
| `build_action_plan`    | `churn`, `intervention`        |
| `draft_campaign_emails`| `segment_gap`, `churn`         |

(Final mapping verified against the actual signal `id`s emitted by
`insights.detect_signals` and the tool names in `tools.py`/`deliverables.py`
during implementation.)

## Data flow

- **On briefing render** (`src/agent/proactive.py`):
  1. detect signals as today;
  2. `mem = load_memory()`;
  3. `diff = diff_signals(current, mem["last_snapshot"])`;
  4. `line = continuity_line(diff)` — prepended to the digest before narration;
  5. narrate via `generate(...)` using `MEMORY_SYSTEM` (falls back to the existing
     deterministic templated briefing on any LLM failure; the continuity line is
     itself deterministic so it survives the fallback);
  6. `record_snapshot(current, params)` — establishes the new baseline (guarded).
- **On any deliverable tool running** (`src/agent/tools.py`): add a one-line
  `memory.record_action(<tool_name>)` alongside the existing `ui_history` append.
- **On "Forget what you remember"** (`src/ui/sidebar.py`): `clear_memory()`.

## Narration & grounding

New constant `MEMORY_SYSTEM` in `src/config.py`, sibling to `PROACTIVE_SYSTEM` /
`REFLEXIVE_SYSTEM`. The narrator receives the deterministic digest **plus** the
continuity line. Rule (same as Phase 1/2): it may only restate what is in the
digest and continuity line — it must never invent prior sessions, dates, or
outcomes. Every number and every "since last time" claim is deterministic before
the LLM sees it.

## UI / control

No new panel or tab. Continuity phrasing appears naturally inside the existing
"💡 Today's Briefing" narrative. A **"Forget what you remember"** button is added
to the sidebar near the existing Reset / "New conversation" controls; it calls
`clear_memory()` and is best-effort (must never crash).

## Testing

New `tests/test_memory.py` — standalone script (not pytest), exits non-zero on
failure, no network, `test_insights.py` style. Covers:

- save / load / clear round-trip, and graceful empty-default on missing/corrupt
  file;
- `record_snapshot` overwrite guard (same params → no overwrite; changed params →
  overwrite);
- `record_action` append + time filtering relative to `last_snapshot.when`;
- `diff_signals` buckets (new / still_present / resolved) and `acted_on` flag set
  correctly via the action→signal map;
- `continuity_line` output incl. the empty-string first-run case.

Existing suites must stay green; app boots headless HTTP 200. A dated entry is
added to the top of the CLAUDE.md Project Journal.

## Scope guardrails (YAGNI)

Explicitly **out of scope** for Phase 3:

- rolling multi-session history / trend-over-N-sessions;
- preference modeling ("always show churn");
- per-signal causal IDs threaded through `_handle_quick_action` → `call_agent`;
- cross-dataset memory identity (the app runs on one fixed dataset);
- any new tab, and provider abstraction (stays Phase 5).
