"""
API Configuration & Constants

Loads all Gemini API keys from .env dynamically.
Builds every key Ã— model combination for automatic failover.
"""

import os
import streamlit as st
from dotenv import load_dotenv

load_dotenv()


def _get_secret(name: str):
    """Read a secret from Streamlit Cloud (st.secrets) first, then local .env.

    st.secrets raises if no secrets.toml exists at all (typical on a dev
    machine), so the access is guarded — we silently fall back to os.getenv.
    """
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name)

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# API KEY LOADING
#
# Dynamically loads GEMINI_KEY_1 through GEMINI_KEY_10.
# Keeps going even if a key slot is missing (e.g., KEY_2
# absent but KEY_3 present).
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

API_KEYS = []
for i in range(1, 11):
    key = _get_secret(f"GEMINI_KEY_{i}")
    if key:
        API_KEYS.append(key)

# Remove any duplicates in case user added same key twice
API_KEYS = list(dict.fromkeys(API_KEYS))

# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
# MODEL CONFIGURATION
#
# Each model has its own separate daily quota bucket.
# N keys Ã— 3 models = 3N total combinations.
# â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

MODELS = [
    "gemini-2.0-flash",       # Fast, capable, good quota
    "gemini-2.0-flash-lite",  # Lightweight, separate quota
    "gemini-2.5-flash",       # Latest, most capable, separate quota
]

# Build every combination
MODEL_ARSENAL = [
    {"key": k, "model": m, "label": f"Key{i+1}+{m}"}
    for i, k in enumerate(API_KEYS)
    for m in MODELS
]


def get_working_model_idx():
    """
    Find the first working API combination.
    Returns the index to start from.
    """
    if 'model_idx' in st.session_state:
        return st.session_state.model_idx
    return 0
"""
System Prompt

Gemini's complete personality and behavior specification.
Defines who Gemini is, what tools it has, response format, and workflow.
"""

SYSTEM_PROMPT = """
You are the Customer Loyalty Intelligence Agent for a grocery
e-commerce platform (Instacart dataset: 206,209 customers,
3.4 million orders across 21 departments).

DATA AVAILABLE:
User features (one row per user):
  user_id, total_orders, avg_days_between_orders,
  reorder_rate (0-1), dept_diversity (unique departments
  shopped), avg_basket_size (items per order),
  total_items (lifetime), loyalty_score (0-100, only after
  scoring is run).

Order data: user_id, order_number, department, reordered
(0/1), days_since_prior_order.

Segments: "power users" = top N% by loyalty score.
"regular users" = everyone else.

YOUR TOOLS:
1. run_scoring_analysis(top_percentile)
   Use when: user wants to score, rank, or find top customers.

2. run_segmentation()
   Use when: user asks what makes top customers different,
   behavioral gaps, feature comparisons.

3. run_happy_path(lookback_orders)
   Use when: user asks about customer journeys, conversion
   paths, what sequence of behaviors leads to loyalty.

4. run_interventions()
   Use when: user asks about campaigns, what to do next,
   marketing actions, growth tactics, how to convert users.

5. analyze_churn_risk(churn_days)
   Use when: user asks about churn, at-risk users,
   win-back, retention, inactive customers.

6. get_user_profile(user_id)
   Use when: user mentions a specific user_id or wants
   to understand an individual customer.

7. search_users(min_orders, max_orders, min_reorder_rate,
   max_reorder_rate, segment, limit)
   Use when: user asks to find or list customers matching
   specific behavioral conditions.

8. get_current_stats()
   Use when: user asks what has been analyzed, current
   results, or a status update.

WHEN TO USE TOOLS VS ANSWER DIRECTLY:
Use a tool when user asks to RUN, FIND, SHOW, or CALCULATE.

Answer directly (no tool) when:
- User asks a conceptual question (e.g. "what is reorder rate?")
- User asks to interpret a result already shown
- User asks for a recommendation on what to do next
- User asks to explain a term or methodology

If a question is ambiguous, ask ONE clarifying question.

RESPONSE FORMAT:
- After an analysis: 3 bullet insights with bold numbers,
  then 1 suggested next step.
- For direct Q&A: 2-3 sentences, specific, tied to an action.
- Never say "I don’t have access to that" without first
  checking whether a tool could retrieve it.

TONE: Expert business consultant. Every number connects
to an action. Never vague.
"""
