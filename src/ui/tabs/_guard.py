# src/ui/tabs/_guard.py
import streamlit as st


def needs_columns(features, cols, tab_name):
    """Return True (and render an info card) if any required column is missing.

    Used by the legacy dashboard tabs to degrade instead of crashing on
    canonical data. These tabs are superseded by the chat-first shell (Phase 7).
    """
    missing = [c for c in cols if features is None or c not in features.columns]
    if missing:
        st.info(
            f"**{tab_name}** isn't available for this dataset "
            f"(missing: {', '.join(missing)}). Use the AI Chat to analyze "
            f"this data instead."
        )
        return True
    return False
