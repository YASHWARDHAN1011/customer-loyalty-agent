# CLAUDE.md

This file has two jobs:

1. **A project journal** (below) — a plain-language log you can read to see what
   was changed, when, and why. Newest entries first.
2. **Technical guidance** for Claude Code / contributors — how the app is wired.

---

## 📓 Project Journal

### 2026-06-04 — Published to GitHub + doc cleanup
- Created public repo **github.com/YASHWARDHAN1011/customer-loyalty-agent** and pushed everything.
- Removed stray `Tempsl` junk files from tracking and gitignored them.
- Fixed `tests/test_data.py` (it pointed at a nonexistent `data/raw/`; now checks
  the real `data/instacart/` and samples big files so it runs fast).
- Rewrote this file to be readable and to carry this journal.

### 2026-06-04 — Four "ship-ready" features
Goal: make the app demo-ready and deployable. Built in this order:

1. **Cloud deploy readiness.** The raw CSVs are ~690MB and can't go to the cloud,
   so `scripts/build_artifacts.py` precomputes three small parquet files into
   `data/artifacts/` (~25MB total, committed). The app now calls
   `get_app_data()`, which loads those parquets when present and falls back to the
   raw CSVs locally. Secrets read from `st.secrets` (cloud) then `.env` (local).
   `requirements.txt` was replaced with a clean minimal list. Added
   `.streamlit/config.toml` + `secrets.toml.example`.
2. **Staged loading.** "Run Full Analysis" now shows a step-by-step status log
   (scoring → top % → thresholds) instead of one vague spinner.
3. **Onboarding wizard.** First-time visitors get a 3-step welcome dialog that
   ends by running an initial analysis. A "Replay tour" button lives in the sidebar.
4. **Persistent chat memory.** The AI chat now survives a restart (saved to
   `.app_state/chat_session.json`); a "New conversation" button clears it.

Specs for the above live in `docs/superpowers/specs/`.

### 2026-06-04 — UI polish ("calm, seamless glass")
- Removed the animated WebGL shader background → a still aurora gradient.
- Stopped entrance animations from replaying on every Streamlit rerun (the page
  no longer "jumps" when you click).
- Slimmed the heavy glass shadows, calmed hover effects, and re-tinted the icon
  chips so they match the background.

---

## Running the app

The venv lives in the **outer** directory; launch from **this (inner)** directory
because data paths are resolved relative to it.

```powershell
# From customer-loyalty-agent/customer-loyalty-agent/
..\venv\Scripts\python.exe -m streamlit run app.py
```

On first run the app reads `data/artifacts/*.parquet` if present (fast). To
(re)build those artifacts from the raw CSVs:

```powershell
..\venv\Scripts\python.exe scripts/build_artifacts.py
```

## Running tests

Standalone scripts (not pytest); each exits non-zero on failure:

```powershell
..\venv\Scripts\python.exe tests/test_data.py         # raw CSVs present & parse
..\venv\Scripts\python.exe tests/test_artifacts.py    # parquet artifacts + get_app_data()
..\venv\Scripts\python.exe tests/test_persistence.py  # chat save/load/clear round-trip
..\venv\Scripts\python.exe tests/test_gemini.py       # smoke-tests Gemini API
..\venv\Scripts\python.exe tests/test_streamlit.py    # Streamlit session state
```

## Environment

API keys live in **`.env` in this directory** as `GEMINI_KEY_1` … `GEMINI_KEY_N`
(up to 10). `src/config.py` reads each via `_get_secret()` — which checks
`st.secrets` first (Streamlit Cloud) then `os.getenv` (local `.env`) — and builds
`MODEL_ARSENAL`, every key × model combination, for automatic failover.

Core dependencies (see `requirements.txt`): `streamlit`, `pandas`, `numpy`,
`altair`, `google-generativeai`, `python-dotenv`, `pyarrow`.

Runtime state (gitignored) lives in `.app_state/`: `onboarding.json` (first-run
flag) and `chat_session.json` (saved chat).

## Deployment (Streamlit Community Cloud)

1. Push to GitHub (already done).
2. New app → point at this repo, main file `app.py`.
3. In the app's **Secrets**, add `GEMINI_KEY_1 = "..."`.
The committed parquet artifacts supply the data, so no CSV upload is needed.

## Architecture

**Entry point:** `app.py` — calls `get_app_data()`, initialises `st.session_state`,
restores any saved chat, shows onboarding, then renders the sidebar and 6 tabs.

### Data pipeline (`src/data/loader.py`)

Pure functions hold the pandas logic (no Streamlit) so the artifact builder can
reuse them; `@st.cache_data` wrappers are thin shells:

- `_merge_raw()` / `load_data()` → merge the 5 Instacart CSVs into `orders` and
  `full_data` (line items with department labels).
- `_compute_features(...)` / `build_features(...)` → one-row-per-user matrix:
  `total_orders, avg_days_between_orders, reorder_rate, dept_diversity,
  avg_basket_size, total_items`.
- `get_app_data()` → returns `(orders, full_data, features)`. Prefers
  `data/artifacts/*.parquet`; falls back to raw CSVs + feature computation.
  In the artifact path `full_data` holds only early orders (`order_number <= 5`,
  the max sidebar lookback) to keep the parquet small.

### Analysis layer (`src/analysis/`)

No Streamlit imports — pure Python, independently testable.

| Module | Key exports |
|--------|-------------|
| `scoring.py` | `score_users(features, weights)`; `get_power_users(scored_df, top_pct)` → `(power, regular, cutoff)`; `get_thresholds(power, regular)` |
| `segmentation.py` | `compute_segment_gaps(power, regular)`; `build_comparison_data(gaps)` |
| `happy_path.py` | `get_happy_paths(full_data, power_user_ids, lookback, top_n)` |
| `interventions.py` | `INTERVENTION_TEMPLATES`; `compute_intervention_gaps(power, regular)` |
| `metrics.py` | `calculate_churn_risk(features, power_user_ids, churn_days)` |

### AI agent (`src/agent/`)

- **`caller.py`** — `call_agent(prompt)` iterates `MODEL_ARSENAL` via
  `model_idx % len(MODEL_ARSENAL)`, advances `model_idx` on quota/permission/not-found
  errors, and snapshots/rolls back `ui_history` on failure.
- **`tools.py`** — functions in `ALL_TOOLS` that Gemini calls via function calling;
  each reads/writes `st.session_state` and appends to `ui_history`.

### UI layer (`src/ui/`)

- **`renderer.py`** — `apply_theme()` (CSS + static aurora background);
  `render_message(msg)` renders `ui_history` entries (text / table / Altair chart);
  `render_intervention_card(...)`; `color_ratio(val)`.
- **`sidebar.py`** — `render_sidebar(features, orders, run_btn_callback)`: weight
  sliders, `top_pct`/`lookback` dropdowns, "Run Full Analysis", exports,
  "Replay tour", and Reset.
- **`onboarding.py`** — `maybe_show_onboarding(run_analysis)` (3-step `@st.dialog`
  first-run tour) and `start_tour()`.
- **`tabs/`** — one module per tab (`overview`, `scoring`, `segments`, `happy_path`,
  `interventions`, `chat`). Tabs read only from `st.session_state`.

### Persistence & Export

- **`src/utils/persistence.py`** — `save_session()` / `load_session()` /
  `clear_session()` over `.app_state/chat_session.json`. Serializes chart
  DataFrames to records and Gemini history to `{role, text}` (tool-call protobufs
  are not round-tripped).
- **`src/export/generator.py`** — `generate_csv_export()` (adds a `loyalty_tier`
  column); `generate_summary_report()` (markdown).

## Key session state variables

| Key | Type | Set by |
|-----|------|--------|
| `features` / `full_data` | DataFrame | `app.py` (`get_app_data`) at startup |
| `scored_df` | DataFrame | scoring / tools |
| `power` / `regular` | DataFrame | scoring |
| `cutoff` | float | scoring |
| `thresholds_df` | DataFrame | scoring |
| `power_user_ids` | set | scoring |
| `top_pct` / `lookback` | int | sidebar / tools |
| `weights` | dict | sidebar (5 keys summing to 1.0) |
| `model_idx` | int | `caller.py` (failover counter) |
| `chat_history` | list | `caller.py` (Gemini history) |
| `ui_history` | list[dict] | chat tab (rendered messages + inline charts) |
| `session_loaded` | bool | `app.py` (restore-once guard) |
| `show_onboarding` / `onboarding_step` / `onboarding_run` | various | onboarding flow |

A `ui_history` entry has `role`, `type` (`"text"`, `"table"`, or `"chart"`), plus
`content` (text) or `data`/`chart_type`/`x`/`y`/`color` (table/chart).

## Conventions

- Keep `src/analysis/` Streamlit-free.
- `@st.cache_data` functions prefix large DataFrame args with `_` to skip hashing.
- `MODEL_ARSENAL` entries are `{"key", "model", "label"}`; `model_idx` wraps with
  `% len(MODEL_ARSENAL)`.
- Persistence and onboarding state are best-effort and must never crash the app.
- **Keep this journal updated**: when you make a notable change, add a dated entry
  at the top of the Project Journal.
