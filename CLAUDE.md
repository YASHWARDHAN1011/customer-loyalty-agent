# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

The venv lives in the **outer** directory but the app must launch from the **inner** directory (this one) because `src/data/loader.py` resolves CSVs via relative paths (`data/instacart/*.csv`).

```powershell
# From this directory (customer-loyalty-agent/customer-loyalty-agent/)
..\venv\Scripts\python.exe -m streamlit run app.py
```

## Running tests

Tests are standalone scripts, not pytest-based:

```powershell
..\venv\Scripts\python.exe tests/test_data.py       # validates all 5 CSVs are present and loadable
..\venv\Scripts\python.exe tests/test_gemini.py     # smoke-tests Gemini API with GEMINI_KEY_1
..\venv\Scripts\python.exe tests/test_streamlit.py  # verifies Streamlit session state works
```

## Environment

API keys go in `.env` (sibling of this directory) as `GEMINI_KEY_1` through `GEMINI_KEY_N` (up to 10). `src/config.py` dynamically loads them and builds a `MODEL_ARSENAL` list of every key × model combination used for automatic failover.

Core dependencies: `google-generativeai`, `streamlit`, `pandas`, `numpy`, `python-dotenv`.

## Architecture

**Entry point:** `app.py` — loads data, builds features, initialises `st.session_state`, then renders the sidebar and 6 tabs.

### Data pipeline (`src/data/loader.py`)

Both functions are cached with `@st.cache_data` and use underscore-prefixed DataFrame args to skip hashing:

- `load_data()` → merges 5 Instacart CSVs into `orders` (transaction headers) and `full_data` (order line items with department labels)
- `build_features(_orders, _full_data)` → produces a one-row-per-user feature matrix with 6 columns: `total_orders`, `avg_days_between_orders`, `reorder_rate`, `dept_diversity`, `avg_basket_size`, `total_items`

### Analysis layer (`src/analysis/`)

These modules have **no Streamlit imports** — keep them pure Python so they are independently testable.

| Module | Key exports |
|--------|-------------|
| `scoring.py` | `score_users(features, weights)` — caps at 95th pct, normalises per-feature to 0–100, applies weighted sum → `loyalty_score`; `get_power_users(scored_df, top_pct)` → `(power, regular, cutoff)`; `get_thresholds(power, regular)` → ratio table |
| `segmentation.py` | `compute_segment_gaps(power, regular)` → sorted list of ratio dicts; `build_comparison_data(gaps)` → DataFrame for grouped bar charts |
| `happy_path.py` | `get_happy_paths(full_data, power_user_ids, lookback, top_n)` → list of funnel dicts showing which department sequences lead to power-user conversion |
| `interventions.py` | `INTERVENTION_TEMPLATES` dict keyed by feature name; `compute_intervention_gaps(power, regular)` → sorted `(gap_pct, col, ru_avg, pu_avg)` tuples |
| `metrics.py` | `calculate_churn_risk(features, power_user_ids, churn_days)` → `(at_risk_df, at_risk_power_df)` |

### AI agent (`src/agent/`)

- **`caller.py`** — `call_agent(prompt)` iterates through `MODEL_ARSENAL` using `model_idx % len(MODEL_ARSENAL)`, increments `model_idx` on `ResourceExhausted`, `NotFound`, or `PermissionDenied`, and snapshots/rolls back `ui_history` on failure.
- **`tools.py`** — 4 functions registered in `ALL_TOOLS` that Gemini calls autonomously via function calling: `run_scoring_analysis`, `run_segmentation`, `run_happy_path`, `get_current_stats`. Each reads/writes `st.session_state` and appends entries to `ui_history` for inline chat rendering.

### UI layer (`src/ui/`)

- **`renderer.py`** — `apply_theme()` injects dark-mode CSS; `render_message(msg)` renders `ui_history` entries (text or Altair charts); `render_intervention_card(...)` renders HTML campaign cards; `color_ratio(val)` styles ratio columns.
- **`sidebar.py`** — `render_sidebar(features, orders, run_btn_callback)` manages weight sliders, `top_pct`/`lookback` dropdowns, the "Run Full Analysis" button (calls `run_btn_callback(top_pct)`), and export/reset buttons.
- **`tabs/`** — one module per tab (`overview`, `scoring`, `segments`, `happy_path`, `interventions`, `chat`). Tabs read exclusively from `st.session_state` — no direct file or DB calls.

### Export (`src/export/generator.py`)

- `generate_csv_export()` → UTF-8 CSV bytes with a `loyalty_tier` column (Casual/Active/Engaged/Loyal/Power User)
- `generate_summary_report()` → markdown string for download

## Key session state variables

| Key | Type | Set by |
|-----|------|--------|
| `features` | DataFrame | `app.py` at startup |
| `full_data` | DataFrame | `app.py` at startup |
| `scored_df` | DataFrame | `scoring.py` / `tools.py` |
| `power` / `regular` | DataFrame | scoring |
| `cutoff` | float | scoring |
| `thresholds_df` | DataFrame | scoring |
| `power_user_ids` | set | scoring |
| `top_pct` | int | sidebar / tools |
| `weights` | dict | sidebar (5-key dict summing to 1.0) |
| `paths` | list[dict] | happy path tool |
| `model_idx` | int | `caller.py` (failover counter) |
| `chat_history` | list | `caller.py` (Gemini conversation history) |
| `ui_history` | list[dict] | chat tab (rendered messages + inline charts) |

Each `ui_history` entry has `role`, `type` (`"text"` or `"chart"`), and for charts: `chart_type`, `data`, `x`, `y`, and optionally `color`.

## Conventions

- Altair charts use a dark theme: backgrounds `#111111`/`#1e293b`, bar gradient `#ff8800` → `#ff4400`.
- `@st.cache_data` functions prefix large DataFrame args with `_` to skip hashing (`_orders`, `_full_data`).
- `MODEL_ARSENAL` entries are `{"key": ..., "model": ..., "label": ...}`; `model_idx` wraps with `% len(MODEL_ARSENAL)` so the index never goes out of bounds.
