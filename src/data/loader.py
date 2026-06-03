"""
Data Loading

Loads and merges all Instacart CSV files.
Uses @st.cache_data for instant reloads after first load.
"""

import streamlit as st
import pandas as pd


@st.cache_data
def load_data():
    """Load and merge all Instacart CSV files."""
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
"""
Feature Engineering

Builds user-level behavioral feature matrix from raw transaction data.
One row per user, 6 behavioral features.
Uses @st.cache_data for instant reloads after first build.
"""

import streamlit as st
import pandas as pd


@st.cache_data
def build_features(_orders, _full_data):
    """
    Build user-level behavioral feature matrix.
    One row per user, 6 behavioral features.
    Underscore prefix tells Streamlit not to hash
    these large DataFrames for cache key computation.
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
