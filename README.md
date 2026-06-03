# Customer Loyalty Agent

An AI-powered customer loyalty intelligence agent for the Instacart dataset.

## Setup

1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Set up your `.env` file with Gemini API keys:
   ```
   GEMINI_KEY_1=your_key_here
   GEMINI_KEY_2=your_second_key_here
   ```
3. Run the app:
   ```bash
   streamlit run app.py
   ```

## Folder Structure

- `app.py`: Main entry point
- `data/instacart/`: Raw CSV data files
- `src/`: Modular application code
  - `agent/`: Gemini agent logic, prompts, and tools
  - `analysis/`: Loyalty scoring, segmentation, and happy path logic
  - `config/`: Environment and model configurations
  - `data/`: Data loading and feature engineering
  - `exports/`: CSV and markdown report generation
  - `ui/`: Streamlit components, layouts, pages, and themes
  - `utils/`: Helpers and utilities
