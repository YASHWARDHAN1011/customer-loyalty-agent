# /run — Launch the Streamlit App

Launch the Customer Loyalty Intelligence app and verify it's running.

## What to do

1. Check if a Streamlit process is already running on port 8501:
   ```powershell
   netstat -ano | findstr :8501
   ```
   If one is already running, tell the user and give them the URL.

2. If not running, start the app in the background from the inner project directory:
   ```powershell
   cd "c:\Users\yashw\Desktop\customer-loyalty-agent\customer-loyalty-agent"
   ..\venv\Scripts\python.exe -m streamlit run app.py
   ```

3. Wait a moment, then confirm it's up by checking port 8501 is now listening.

4. Tell the user: the app is running at **http://localhost:8501**

## Key facts

- The venv lives in the **outer** directory (`customer-loyalty-agent/venv`), not the inner one. Always use `..\venv\Scripts\python.exe` when running from the inner directory.
- The app loads parquet artifacts from `data/artifacts/` on startup (fast, ~2s). If those don't exist it falls back to raw CSVs (~30s).
- The Streamlit toolbar is hidden by CSS — that's intentional.
- If you see a port conflict, tell the user to stop the existing process first.
