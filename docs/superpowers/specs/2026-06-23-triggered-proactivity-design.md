# Phase 6 — Triggered Proactivity (Watches & Alerts)

**Date:** 2026-06-23
**Roadmap:** Proactive Analyst, Phase 6 (final roadmap item)
**Status:** Approved design, pending implementation plan

## Summary

Give the agent a watch/alert system. The user defines threshold conditions on
real loyalty metrics; on every app interaction the app evaluates them, and any
crossed condition surfaces as a banner at the top of whatever tab the user is on.
This is the "triggered" half of proactivity: Phase 1 shows an on-load briefing,
Phase 6 makes the agent speak up only when a condition the user cares about is
actually met.

Like the rest of the project, every number is deterministic. Here the LLM is not
even in the path — alert messages are templated. This keeps alerts reliable,
free, and impossible to hallucinate.

## Decisions (locked in brainstorm)

- **Trigger type:** user-defined watch thresholds (not auto-anomaly, not
  change-deltas, not per-tab offers).
- **Watch input:** structured form (metric dropdown + direction + number). No
  natural-language parsing.
- **Surface:** a colored banner at the top of any tab when a watch fires; watches
  are created / listed / deleted in the sidebar.
- **Persistence:** watches survive restart (best-effort JSON store, like
  `memory.py` / `persistence.py`).
- **Evaluation timing:** on every Streamlit rerun once analysis has run. Pure
  arithmetic on already-computed values, so it is cheap.

## Watchable metrics

Each maps to a deterministic value the analysis layer already produces. A watch
is `{id, metric, direction, threshold, created_at}` where `direction ∈
{above, below}`.

| metric id | label | computation |
|-----------|-------|-------------|
| `churn_pct` | Churn risk (% of customers) | `100 * len(at_risk) / len(features)` via `calculate_churn_risk` |
| `at_risk_power` | At-risk power users (count) | `len(at_risk_power)` via `calculate_churn_risk` |
| `power_cutoff` | Power-user loyalty cutoff (score) | `cutoff` from scoring |
| `top_segment_gap` | Largest power-vs-regular gap (%) | max gap pct from `compute_segment_gaps` |

A watch **fires** when `direction == "above"` and `current > threshold`, or
`direction == "below"` and `current < threshold`. (Strict inequality; equality
does not fire.)

## Components

### 1. `src/agent/watches.py` (NEW, pure / Streamlit-free)

Follows the `insights.py` convention — no Streamlit, no LLM; imports analysis
functions directly.

- `WATCHABLE_METRICS` — ordered registry of the 4 metric definitions, each:
  `{id, label, unit, compute(snapshot) -> float | None}`. `compute` returns
  `None` when the inputs are missing/empty (so an unready metric never fires).
- `evaluate_metric(metric_id, snapshot) -> float | None` — convenience lookup +
  compute.
- `evaluate_watches(watches, snapshot) -> list[dict]` — returns fired alerts in
  the watches' order, each:
  `{watch_id, metric, label, direction, threshold, current, severity, message}`.
  - `severity`: `"error"` if the metric is in the "bad" direction beyond
    threshold for the always-bad metrics (`churn_pct` above, `at_risk_power`
    above) else `"warning"`. (Simple static mapping; documented in code.)
  - `message`: deterministic template, e.g.
    `"⚠️ Churn risk is 18.2%, above your 15% watch."`
- Persistence (best-effort, never raises — mirror `memory.py`):
  - `STATE_DIR = ".app_state"`, `WATCHES_FILE = ".app_state/watches.json"`.
  - `load_watches(path=WATCHES_FILE) -> list[dict]` — `[]` on any failure.
  - `add_watch(metric, direction, threshold, path=WATCHES_FILE) -> dict` —
    validates `metric` is known, `direction ∈ {above, below}`, `threshold` is a
    finite number; assigns a stable `id` (uuid4 hex) + `created_at`; appends and
    saves; returns the new watch. Raises `ValueError` on invalid input (caught by
    the UI to show a message — persistence I/O itself stays best-effort).
  - `remove_watch(watch_id, path=WATCHES_FILE) -> bool` — drops by id, saves.
  - `_save(data, path)` — guarded write, like `memory._save`.

The snapshot is a plain dict the UI assembles from `session_state` so
`watches.py` stays Streamlit-free:
`{features, scored_df, power, regular, power_user_ids, full_data, cutoff,
top_pct, churn_days}`. `CHURN_DAYS = 30` constant shared with `proactive.py`
(re-declare locally to avoid a UI import; value matches).

### 2. `src/ui/sidebar.py` — "🔔 Watches" section

- A form (`st.form` to avoid firing on each widget change): metric `st.selectbox`
  (labels from `WATCHABLE_METRICS`), direction `st.radio` (Above / Below), value
  `st.number_input`, submit "Add watch". On submit call `add_watch`; show
  `st.success` / `st.error` from the return / `ValueError`.
- Below the form, list current watches (`load_watches`) — one row each:
  `"{label} {direction} {threshold}"` + a 🗑 button calling `remove_watch` then
  `st.rerun()`.
- Placed after the existing controls; must not interfere with
  "Run Full Analysis" / exports / reset.

### 3. Banner glue in `app.py`

- New `render_watch_alerts()` (small helper, may live in `src/ui/renderer.py` or
  inline in `app.py` near the header). Called near the top of the main content
  area, before the tabs, so alerts render above whichever tab is active.
- It guards on analysis readiness (`scored_df` present and non-empty); if not
  ready, render nothing.
- Assembles the snapshot dict from `session_state`, calls `load_watches` +
  `evaluate_watches`, and renders each fired alert via `st.error` (severity
  error) or `st.warning` (severity warning) using its `message`.
- If no watches or none fired, render nothing (no empty box).

### 4. `tests/test_watches.py` (NEW, standalone script)

Matches the repo's standalone style (no pytest; `check()` helper, non-zero exit
on failure), no network, no Streamlit:

- Each metric's `compute` on a small synthetic snapshot returns the expected
  number; returns `None` on empty/missing inputs.
- `evaluate_watches`: above/below fire logic, strict inequality (equality does
  not fire), unready metric (`compute -> None`) never fires, message text,
  severity mapping, ordering preserved.
- Persistence round-trip: `add_watch` → `load_watches` → `remove_watch` on a
  temp path; invalid metric / direction / non-finite threshold raise
  `ValueError`; corrupt/missing file → `load_watches` returns `[]`.

## Non-goals (YAGNI)

- No LLM anywhere in the alert path (templated messages only).
- No natural-language watch creation.
- No background or scheduled evaluation — triggers fire on app interaction, the
  only thing a Streamlit app can do.
- No alert history / acknowledgement state — a fired watch simply shows while its
  condition holds.
- No new tab (app stays at 6 tabs).

## Testing & acceptance

- `tests/test_watches.py` passes (standalone, non-zero exit on failure).
- Full existing no-network suite still green.
- App boots headless HTTP 200.
- Manual browser check: add a watch whose threshold is already crossed → banner
  appears on every tab; delete it → banner disappears; restart app → watch
  persists.

## Journal / memory

- Add a dated entry to `CLAUDE.md`'s Project Journal on completion.
- Phase 6 completes the Proactive Analyst roadmap. After merge, revisit the
  open "what next" question (now answered as: real tool — so depth/validation
  work rather than more breadth).
