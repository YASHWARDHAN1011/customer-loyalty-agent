# What-If Simulation — Design

**Date:** 2026-06-19
**Phase:** Proactive Analyst roadmap, Phase 4 (What-If Simulation)
**Status:** Approved design, pre-implementation

## Goal

Let the operator ask the agent to simulate a campaign's behavioral lift and get a
grounded projection back — e.g. *"If a campaign lifted regular users' reorder rate
by 15%, how many would clear the loyalty bar and become power users?"* The agent
answers with deterministic numbers (re-scoring), never estimates. This extends the
agent from describing the present to projecting a hypothetical future, in the same
never-invent-numbers spirit as Phases 1–3.

## Decisions locked during brainstorming

- **What-if type:** behavioral-lift **campaign simulation** (not threshold sweeps
  or weight rebalancing — those may come later).
- **Lift definition:** a campaign adjusts a **single feature lever**.
- **Target & magnitude:** applied to **regular (non-power) users**, expressed as a
  **percentage lift** of that feature.
- **Output:** **conversions + key deltas** — how many regulars clear the power-user
  bar, the new power count/%, and the lifted feature's before→after average. No
  churn modelling, no score-distribution dashboard.
- **Surface:** an **agent tool** callable from chat (function-calling) and Autopilot
  (`TOOL_REGISTRY`). No new tab.
- **Conversion semantics:** **Approach A — fixed loyalty bar.** Freeze the baseline
  scoring scaler + cutoff score; re-score lifted regulars with the frozen scaler;
  count those who now clear the original cutoff. Keeps scores directly comparable
  and lets the converted count genuinely grow.
- **Provider:** Gemini-only. Provider abstraction remains Phase 5.

## Architecture

The deterministic engine is pure (Streamlit-free, independently testable, per the
`src/analysis` convention). The tool is a thin session-state wrapper, consistent
with every existing tool in `src/agent/tools.py`.

### Files

- **Modify `src/analysis/scoring.py`** — split the scaler out so it can be frozen:
  - `compute_scaler(features, weights) -> dict` returns
    `{"caps": {col: 95th_pctile}, "max_raw": float}`.
  - `apply_scoring(features, weights, scaler) -> pd.DataFrame` — the existing
    scoring math, but using the *provided* caps and `max_raw` instead of computing
    them from the data. Returns the same columns as today (`raw_score`,
    `loyalty_score`), sorted by `loyalty_score` descending.
  - `score_users(features, weights)` becomes
    `apply_scoring(features, weights, compute_scaler(features, weights))` — its
    observable behavior is **identical** (backward-compatible; `get_power_users`
    and `get_thresholds` are untouched).
- **Create `src/analysis/simulation.py`** (pure) — `simulate_campaign(...)`.
- **Modify `src/agent/tools.py`** — `simulate_campaign(feature, lift_pct)` tool;
  add to `ALL_TOOLS`.
- **Modify `src/agent/orchestrator.py`** — register `simulate_campaign` in
  `TOOL_REGISTRY` so Autopilot can plan/execute it.
- **Create `tests/test_simulation.py`** (standalone, no-network).
- **Modify `CLAUDE.md`** — dated Project Journal entry.

### The lever set

The feature must be one of the **5 weighted scoring features**, exposed as a pure
constant `LEVERS` in `simulation.py` (so validity is testable without Streamlit):
`total_orders`, `reorder_rate`, `dept_diversity`, `avg_basket_size`, `total_items`.

`avg_days_between_orders` is deliberately excluded: it carries no scoring weight,
so lifting it would not change conversions (a misleading "no effect" result), and
it is the only "lower = better" feature (direction confusion). It belongs to churn,
which is out of scope here.

## The engine (`src/analysis/simulation.py`)

`simulate_campaign(features, weights, top_pct, feature, lift_pct) -> dict`

Steps:
1. `scaler = compute_scaler(features, weights)`;
   `baseline = apply_scoring(features, weights, scaler)`;
   `power, regular, cutoff = get_power_users(baseline, top_pct)`.
   This yields the frozen scaler and the baseline cutoff score.
2. Build lifted features: copy `features`; for **regular users only**, set
   `feature = feature * (1 + lift_pct/100)`. If `feature == "reorder_rate"`, clip
   the lifted column to a max of `1.0` (it is a 0–1 rate).
3. Re-score the lifted population with the **frozen scaler**:
   `lifted = apply_scoring(lifted_features, weights, scaler)`. Because the scaler is
   frozen, unlifted (power) users keep identical scores and all scores stay
   comparable to baseline.
4. `conversions` = regular users whose lifted `loyalty_score >= cutoff`.
5. Return a deterministic dict:
   ```
   {
     "feature": feature,
     "lift_pct": lift_pct,
     "target_count": <# regular users>,
     "conversions": <# regulars now >= cutoff>,
     "baseline_power_count": <# baseline power users>,
     "projected_power_count": baseline_power_count + conversions,
     "projected_power_pct": round(projected_power_count / total_users * 100, 1),
     "feature_avg_before": <mean of feature among regulars, baseline>,
     "feature_avg_after": <mean of lifted feature among regulars, post-clip>,
     "cutoff": <baseline cutoff score>,
   }
   ```
   `projected_power_count` is baseline power + conversions because only regulars are
   lifted, so existing power users' scores are unchanged and they remain above the
   bar.

Edge handling (pure, never raises on normal inputs): empty `features` or empty
`regular` set → `conversions = 0` with counts reflecting reality; `lift_pct = 0`
→ `0` conversions (identical scores). Invalid `feature` is rejected at the tool
layer (see below), but the engine may also assume `feature` is a valid weighted
column (caller-guaranteed).

## The tool (`src/agent/tools.py`)

`simulate_campaign(feature: str, lift_pct: float) -> dict` — Gemini function-calling
tool following the existing pattern (type hints, descriptive docstring, reads/writes
`st.session_state`, returns a JSON-serializable dict, never raises).

- Reads `features`, `weights`, `top_pct` from session_state; returns an error dict
  if data/scoring isn't ready.
- **Validates** `feature in simulation.LEVERS` (else returns an error dict that
  names the valid options) and `lift_pct` is within `0`–`200` — out-of-range
  values are **rejected** with a clear error message (not silently clamped, to keep
  the projection honest).
- Calls `simulation.simulate_campaign(...)`.
- Appends a markdown results **card** to `ui_history` (like `run_interventions`),
  e.g. headline conversions + before→after + projected power %.
- Returns the structured result dict plus an `instruction` field telling the model
  to narrate **using only these numbers** — the same grounding contract every
  existing tool uses (engine computes; LLM only narrates).
- Added to `ALL_TOOLS`.

Registered in `orchestrator.TOOL_REGISTRY` as:
```
"simulate_campaign": {
    "func": T.simulate_campaign,
    "desc": "Project a campaign: lift one feature for regular users and count how many become power users (needs scoring first).",
    "args": {"feature": "str", "lift_pct": "float"},
}
```

## Grounding

Every projected number is produced by the deterministic engine before the LLM sees
it. The tool's `instruction` constrains the model to restate those numbers, exactly
as the other tools do. No new system prompt is needed.

## Testing

`tests/test_simulation.py` — standalone script (not pytest), exits non-zero on
failure, no network, `test_insights.py` style. Covers:

- **Scaler comparability:** scoring an unchanged population with a frozen scaler
  reproduces the same scores as the baseline (and `score_users` == `apply_scoring`
  with a computed scaler).
- **Refactor safety:** a small hand-computed case confirms `score_users` output is
  unchanged after the refactor.
- **Known conversion:** a fixture where a specific lift moves a known number of
  regulars across the cutoff.
- **reorder_rate clip:** lifting `reorder_rate` never produces a value > 1.0.
- **Monotonicity:** larger `lift_pct` ⇒ `conversions` never decreases.
- **Zero lift:** `lift_pct = 0` ⇒ `0` conversions, `projected_power_count ==
  baseline_power_count`.
- **Lever validity:** `LEVERS` contains exactly the 5 weighted features and
  excludes `avg_days_between_orders` (pure, testable without Streamlit). The tool
  itself is syntax-checked + registration-verified, since it needs the Streamlit
  runtime, mirroring how Phase 3 handled `tools.py`.

Existing suites must stay green; app boots headless HTTP 200. A dated entry is added
to the top of the CLAUDE.md Project Journal.

## Scope guardrails (YAGNI)

Explicitly **out of scope** for Phase 4:

- churn-impact modelling, score-distribution histograms, segment-gap deltas;
- multi-feature bundles or per-segment targeting beyond "regular users";
- threshold sweeps and scoring-weight rebalancing (other what-if types);
- any new UI tab or interactive panel (the surface is the agent tool);
- provider abstraction (stays Phase 5).
