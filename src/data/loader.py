"""
Data Loading

Loads and merges all Instacart CSV files, or loads precomputed parquet
artifacts when present (the cloud / fast-start path).

Pure functions (`_merge_raw`, `_compute_features`) hold the pandas logic with
NO Streamlit dependency so the offline `scripts/build_artifacts.py` can reuse
them. The `@st.cache_data` wrappers are thin shells over the pure functions.
"""

import os
import streamlit as st
import pandas as pd

# Directory holding precomputed parquet artifacts (committed, used on cloud).
ARTIFACT_DIR = 'data/artifacts'
ARTIFACT_FEATURES = os.path.join(ARTIFACT_DIR, 'features.parquet')
ARTIFACT_ORDERS = os.path.join(ARTIFACT_DIR, 'orders_slim.parquet')
ARTIFACT_HAPPY = os.path.join(ARTIFACT_DIR, 'happy_path.parquet')

# Happy-path analysis never traces past this order number (sidebar caps
# lookback at 5), so the happy_path artifact only stores early orders.
MAX_LOOKBACK = 5


def _merge_raw():
    """Pure: load and merge the 5 raw Instacart CSVs into (orders, full_data)."""
    orders = pd.read_csv('data/instacart/orders.csv')
    prior = pd.read_csv('data/instacart/order_products__prior.csv')
    products = pd.read_csv('data/instacart/products.csv')
    departments = pd.read_csv('data/instacart/departments.csv')

    products_full = products.merge(departments, on='department_id')

    prior_with_dept = prior.merge(
        products_full[['product_id', 'department']],
        on='product_id', how='left'
    )

    full_data = prior_with_dept.merge(
        orders[['order_id', 'user_id', 'order_number',
                'days_since_prior_order', 'order_dow',
                'order_hour_of_day']],
        on='order_id', how='left'
    )

    return orders, full_data


@st.cache_data
def load_data():
    """Cached wrapper over `_merge_raw` (raw-CSV path)."""
    return _merge_raw()


def artifacts_exist():
    """True when all three parquet artifacts are present on disk."""
    return (
        os.path.exists(ARTIFACT_FEATURES)
        and os.path.exists(ARTIFACT_ORDERS)
        and os.path.exists(ARTIFACT_HAPPY)
    )


@st.cache_data
def get_app_data():
    """Return (orders, full_data, features) for the app.

    Prefers the small precomputed parquets (cloud + fast local start). Falls
    back to reading the ~690MB raw CSVs and computing features on the fly when
    artifacts have not been built yet.

    In the artifact path `full_data` is the slimmed early-orders table — the
    only consumer (happy-path analysis) filters by order_number anyway — and
    `orders` carries just the columns the app reads.
    """
    if artifacts_exist():
        features = pd.read_parquet(ARTIFACT_FEATURES)
        orders = pd.read_parquet(ARTIFACT_ORDERS)
        full_data = pd.read_parquet(ARTIFACT_HAPPY)
        return orders, full_data, features

    orders, full_data = _merge_raw()
    features = _compute_features(orders, full_data)
    return orders, full_data, features
"""
Feature Engineering

Builds user-level behavioral feature matrix from raw transaction data.
One row per user, 6 behavioral features.
Uses @st.cache_data for instant reloads after first build.
"""

import streamlit as st
import pandas as pd


def _compute_features(_orders, _full_data):
    """
    Pure: build the user-level behavioral feature matrix.
    One row per user, 6 behavioral features. No Streamlit dependency so the
    offline artifact builder can reuse it.
    """
    users = pd.DataFrame({
        'user_id': _orders['user_id'].unique()
    })

    # Total orders â€” max order_number = count of orders
    total_orders = (
        _orders.groupby('user_id')['order_number']
        .max().rename('total_orders')
    )
    users = users.merge(total_orders, on='user_id', how='left')

    # Avg days between orders â€” lower = more frequent
    avg_gap = (
        _orders.groupby('user_id')['days_since_prior_order']
        .mean().rename('avg_days_between_orders')
    )
    users = users.merge(avg_gap, on='user_id', how='left')

    # Reorder rate â€” % of items bought repeatedly
    reorder = (
        _full_data.groupby('user_id')['reordered']
        .mean().rename('reorder_rate')
    )
    users = users.merge(reorder, on='user_id', how='left')

    # Department diversity â€” unique departments shopped
    dept_div = (
        _full_data.groupby('user_id')['department']
        .nunique().rename('dept_diversity')
    )
    users = users.merge(dept_div, on='user_id', how='left')

    # Avg basket size â€” items per order
    basket = (
        _full_data.groupby(['user_id', 'order_id'])
        .size().groupby('user_id').mean()
        .rename('avg_basket_size')
    )
    users = users.merge(basket, on='user_id', how='left')

    # Total items lifetime
    total_items = (
        _full_data.groupby('user_id')
        .size().rename('total_items')
    )
    users = users.merge(total_items, on='user_id', how='left')

    return users.fillna(0).round(4)


@st.cache_data
def build_features(_orders, _full_data):
    """Cached wrapper over `_compute_features`.

    Underscore-prefixed args tell Streamlit not to hash these large DataFrames
    when computing the cache key.
    """
    return _compute_features(_orders, _full_data)
"""
Data Preprocessing

Utilities for data cleaning and validation.
Reserved for future preprocessing steps.
"""


def clean_missing_values(df, strategy='fill_zero'):
    """
    Handle missing values in a DataFrame.

    Args:
        df: Input DataFrame.
        strategy: 'fill_zero', 'drop', or 'fill_median'.

    Returns:
        Cleaned DataFrame.
    """
    if strategy == 'fill_zero':
        return df.fillna(0)
    elif strategy == 'drop':
        return df.dropna()
    elif strategy == 'fill_median':
        numeric_cols = df.select_dtypes(include='number').columns
        df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].median())
        return df
    else:
        raise ValueError(f"Unknown strategy: {strategy}")
