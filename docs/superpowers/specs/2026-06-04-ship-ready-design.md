# Ship-Ready Design — 4 Features

**Date:** 2026-06-04
**Goal:** Make the customer-loyalty-agent app demo-ready and deployable: first-run
onboarding, cloud deployment, clearer loading, and chat that survives restarts.
**Build order:** 2 → 3 → 1 → 4 (deploy foundation first; persistence last).

Cross-cutting conventions:
- `analysis/` modules stay Streamlit-free (already true). New persistence/artifact
  helpers live under `src/utils/` and `scripts/`.
- New runtime state dir `.app_state/` (gitignored) holds onboarding flag + saved chat.
- `.gitignore` gains `.app_state/` and `.streamlit/secrets.toml`.

---

## Feature 2 — Streamlit Cloud deploy readiness (foundation)

**Problem.** Raw CSVs are ~690MB (`order_products__prior.csv` 577MB, `orders.csv` 109MB),
gitignored by `*.csv`, so the cloud has no data. Also `requirements.txt` is a 109-line
UTF-16 `pip freeze` (torch, datasets, fastapi…) that will not install on Streamlit Cloud.
Secrets currently come only from `.env` (which lives in the inner dir, not the outer dir
as CLAUDE.md states).

**Design.**
1. **Secrets.** Add `_get_secret(name)` in `src/config.py`: read `st.secrets[name]` first
   (cloud), fall back to `os.getenv(name)` (local `.env`). API-key loading uses it so the
   same code path works locally and on cloud. No auth/login — secrets only.
2. **Clean requirements.** Replace `requirements.txt` with a minimal UTF-8 list:
   `streamlit, pandas, numpy, altair, google-generativeai, python-dotenv, pyarrow`.
   (Pin loosely; `pyarrow` is new — needed to read/write parquet.)
3. **Artifact pipeline.** `scripts/build_artifacts.py` reads the raw CSVs locally and writes
   3 small parquet files to `data/artifacts/`:
   - `features.parquet` — output of `build_features` (one row/user, 6 cols).
   - `orders_slim.parquet` — `orders` minus heavy unused columns, enough for the app.
   - `happy_path.parquet` — `full_data` reduced to `user_id, order_number, department`
     (the only columns `get_happy_paths` consumes), to keep size small.
4. **Dual loader.** `src/data/loader.py` gains `get_app_data()`:
   - If `data/artifacts/*.parquet` exist → load them (cloud + fast local path).
   - Else → fall back to current raw-CSV `load_data()` + `build_features()` (dev machine
     before artifacts are built).
   Returns the same `(orders, full_data, features)` shape the app expects. `app.py` calls
   `get_app_data()` instead of `load_data` + `build_features` directly.
5. **Un-ignore artifacts.** `.gitignore` adds `!data/artifacts/` + `!data/artifacts/*.parquet`
   so the small parquets are committed and reach the cloud.
6. **`.streamlit/config.toml`** committed (theme base=dark, headless server) and
   `.streamlit/secrets.toml` gitignored with a `secrets.toml.example` template.

**Tests.** `tests/test_artifacts.py` (standalone script, matching repo convention): if
artifacts exist, assert the 3 parquets load and have expected columns; assert
`get_app_data()` returns 3 DataFrames with the required columns.

**Risk / tradeoff.** `happy_path.parquet` drops columns some future tool might want; accepted
— current code only needs those 3. Building artifacts requires the raw CSVs present locally
(one-time dev step).

---

## Feature 3 — Staged loading status log

**Problem.** `run_analysis()` shows one opaque `st.spinner("Scoring all users...")`.

**Design.** Replace with `st.status("Running analysis…", expanded=True)` that logs discrete
steps via `st.write`: "Scoring users" → "Selecting top N%" → "Computing thresholds" →
"Done", then `status.update(label="Analysis complete", state="complete")`. Same underlying
calls (`score_users`, `get_power_users`, `get_thresholds`); only the UX wrapper changes.
Keep the final `st.success` summary. No new files.

---

## Feature 1 — Onboarding wizard

**Problem.** First-time users land on an empty dashboard with no guidance.

**Design.**
- New `src/ui/onboarding.py` exposing `maybe_show_onboarding(run_analysis)`.
- Uses `@st.dialog("Welcome")` to show a 3-step wizard (Welcome/what this is → how scoring
  works → pick a starting top-% ). Final step calls `run_analysis(top_pct=10)` then closes.
- First-run flag persisted to `.app_state/onboarding.json` (`{"seen": true}`). Helper
  reads/writes it. Dialog only auto-opens when flag absent.
- Sidebar gains a **"Replay tour"** button that clears the flag / re-opens the dialog.
- `app.py` calls `maybe_show_onboarding(run_analysis)` after session-state init.

**Tradeoff.** `@st.dialog` requires a recent Streamlit; already used elsewhere is not
assumed — verify version at implementation time, fall back to an inline expander if missing.

---

## Feature 4 — Persistent chat memory

**Problem.** Chat (`chat_history` + `ui_history`) is lost on restart. Within-session memory
already works (`caller.py` restores Gemini `chat_history` each call); only cross-restart
persistence is missing.

**Design.**
- New `src/utils/persistence.py` with `save_session()`, `load_session()`, `clear_session()`
  over `.app_state/chat_session.json`.
- **Serialize `ui_history`:** convert any DataFrame chart `data` to records; store
  role/type/content/chart fields. **Serialize `chat_history`:** extract text parts into
  `{role, text}`. Gemini tool-call protobufs are NOT round-tripped (accepted tradeoff — on
  reload the conversation is text + charts, no replayable tool state).
- Single auto-restored conversation: `app.py` calls `load_session()` on startup to seed
  `ui_history`/`chat_history` if present. `chat.py` calls `save_session()` after each
  assistant turn. Sidebar/chat gains a **"New conversation"** button → `clear_session()` +
  reset state.

**Tests.** `tests/test_persistence.py` (standalone): round-trip a sample `ui_history` with a
DataFrame chart and a `chat_history`; assert save→load preserves text + chart records and
that `clear_session()` removes the file.

---

## Out of scope
Auth/multi-user, real DB, replayable tool-call state across restart, analysis-algorithm
changes.
