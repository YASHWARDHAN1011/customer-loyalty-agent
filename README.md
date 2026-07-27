# Customer Loyalty Intelligence Agent

A chat-first analytics agent for e-commerce customer loyalty. Ask questions in
plain language; every number you see is computed deterministically from real
data — the LLM chooses the analysis and narrates the result, it never invents a
figure.

## What it does

- **Chat-first.** One conversation is the whole app. Ask it to score customers,
  compare power users vs. regulars, find the "happy path" to loyalty, flag churn
  risk, simulate a campaign, or draft target lists / emails / action plans.
- **Grounded data queries.** For novel questions no built-in analysis covers
  ("average order value by category", "how many customers have recency over 90
  days", "is frequency correlated with spend?"), a constrained query tool computes
  the real answer over your data.
- **Recipes.** Save a good query as a named, one-click action; it recomputes on
  current data every time — and works even if the LLM is rate-limited.
- **Bring your own data.** Upload your own CSV/Excel; the app proposes a column
  mapping, you confirm it, and it runs the full analysis on your dataset. A
  built-in Instacart demo flows through the same pipeline.
- **Trust by construction.** All analysis is deterministic Python over a canonical
  data model; the app degrades with a clear message (never a crash or a made-up
  number) when a feature isn't available for a dataset.

## Run locally

Requires Python 3.11+. From a fresh clone (repo root, where `app.py` lives):

```powershell
# Windows (PowerShell)
python -m venv venv
venv\Scripts\python.exe -m pip install -r requirements.txt
venv\Scripts\python.exe -m streamlit run app.py
```

```bash
# macOS / Linux
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python -m streamlit run app.py
```

The app opens at http://localhost:8501. On first run it reads the committed
canonical demo artifacts under `data/artifacts/canonical/` (fast) — it runs on the
demo dataset even before you add any API keys (the chat agent needs a key; the
dashboards and upload flow do not).

Add API keys in a `.env` file in the repo root to enable the chat agent:

```
GEMINI_KEY_1=your_key           # up to GEMINI_KEY_10
ANTHROPIC_API_KEY=your_key      # optional: enables Gemini→Claude failover
```

Get a free Gemini key at https://aistudio.google.com/apikey.

## Deploy (Streamlit Community Cloud)

1. Push to GitHub.
2. New app → point at this repo, main file `app.py`.
3. In the app's **Secrets**, add `GEMINI_KEY_1 = "..."` (and optionally
   `ANTHROPIC_API_KEY`). The committed parquet artifacts supply the demo data —
   no raw CSV upload needed.

## How it works

- **Canonical data model** (`src/data/`): every dataset — the demo or an upload —
  becomes one `orders` + optional `order_items` shape and a per-customer feature
  matrix, with each feature tagged available/unavailable so nothing downstream
  breaks on a missing column.
- **Analysis** (`src/analysis/`): pure, Streamlit-free scoring / segmentation /
  churn / simulation / grounded query — independently testable.
- **Agent** (`src/agent/`): a provider-agnostic tool loop (Gemini, failing over to
  Claude) drives typed tools; a dispatch ladder routes each message to a saved
  recipe, a known tool, or a multi-step goal.
- **LLM backends**: `GEMINI_KEY_*` rotate across model buckets; an optional
  `ANTHROPIC_API_KEY` adds a Claude failover tier for text/reasoning calls.

## Tests

Standalone scripts (no network), each exits non-zero on failure, e.g.:

```powershell
venv\Scripts\python.exe tests/test_query.py
venv\Scripts\python.exe tests/test_recipes.py
venv\Scripts\python.exe tests/test_tools_canonical.py
```

`tests/test_gemini.py` is the only one that needs a live API key.

See `CLAUDE.md` for the full architecture reference and project journal.
