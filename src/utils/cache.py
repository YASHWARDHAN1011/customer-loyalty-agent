"""
Cache Helpers
"""
import streamlit as st

def clear_all_caches():
    st.cache_data.clear()
    st.cache_resource.clear()
