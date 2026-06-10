# /test — Run All Tests

Run the project's 5 test scripts in order and report results.

## What to do

Run each script sequentially from the inner project directory. Each script exits non-zero on failure.

```powershell
cd "c:\Users\yashw\Desktop\customer-loyalty-agent\customer-loyalty-agent"

..\venv\Scripts\python.exe tests/test_data.py
..\venv\Scripts\python.exe tests/test_artifacts.py
..\venv\Scripts\python.exe tests/test_persistence.py
..\venv\Scripts\python.exe tests/test_gemini.py
..\venv\Scripts\python.exe tests/test_streamlit.py
```

## What each test checks

| Script | What it verifies |
|--------|-----------------|
| `test_data.py` | Raw CSVs in `data/instacart/` exist and parse correctly |
| `test_artifacts.py` | Parquet artifacts in `data/artifacts/` exist and `get_app_data()` returns correct types |
| `test_persistence.py` | Chat save / load / clear round-trip works on `.app_state/chat_session.json` |
| `test_gemini.py` | Gemini API responds with a real key from `.env` |
| `test_streamlit.py` | Streamlit session state behaves correctly |

## Reporting

After all 5 run, give a summary table showing PASS / FAIL for each. If any fail, show the error output and suggest a fix.

## Notes

- `test_gemini.py` requires at least one valid `GEMINI_KEY_1` in the `.env` file. If no key is set, report it as skipped rather than failed.
- `test_data.py` samples large files (doesn't read all 3.4M rows) so it runs fast.
- If `data/artifacts/` doesn't exist, `test_artifacts.py` will fail — tell the user to run `/build` first.
