import pandas as pd
import numpy as np

print("Loading data...")

orders = pd.read_csv('data/raw/orders.csv')
prior = pd.read_csv('data/raw/order_products__prior.csv')
products = pd.read_csv('data/raw/products.csv')
departments = pd.read_csv('data/raw/departments.csv')

print("Data loaded.\n")

# ─────────────────────────────────────────
# SECTION 1: UNDERSTAND ORDERS
# ─────────────────────────────────────────
print("=" * 50)
print("SECTION 1: ORDERS")
print("=" * 50)

print(f"Total rows: {len(orders):,}")
print(f"Unique users: {orders['user_id'].nunique():,}")
print(f"Unique orders: {orders['order_id'].nunique():,}")
print(f"\nColumns:\n{orders.dtypes}")
print(f"\nSample:\n{orders.head()}")

# How many orders does a typical user make?
orders_per_user = orders.groupby('user_id')['order_number'].max()
print(f"\n--- Orders per user ---")
print(orders_per_user.describe())
print(f"\nTop 10% users have {orders_per_user.quantile(0.9):.0f}+ orders")
print(f"Top 5% users have {orders_per_user.quantile(0.95):.0f}+ orders")
print(f"Median user has {orders_per_user.median():.0f} orders")

# Days between orders
print(f"\n--- Days between orders ---")
print(orders['days_since_prior_order'].describe())
print(f"Most common gap: {orders['days_since_prior_order'].mode()[0]} days")

# ─────────────────────────────────────────
# SECTION 2: UNDERSTAND PRODUCTS
# ─────────────────────────────────────────
print("\n" + "=" * 50)
print("SECTION 2: PRODUCTS & DEPARTMENTS")
print("=" * 50)

# Merge products with departments
products_full = products.merge(departments, on='department_id')
print(f"Total products: {len(products_full):,}")
print(f"Departments:\n{departments}")

# ─────────────────────────────────────────
# SECTION 3: UNDERSTAND PURCHASE BEHAVIOR
# ─────────────────────────────────────────
print("\n" + "=" * 50)
print("SECTION 3: PURCHASE BEHAVIOR")
print("=" * 50)

# Merge prior orders with order info to get user_id
prior_with_user = prior.merge(
    orders[['order_id', 'user_id', 'order_number']],
    on='order_id'
)

print(f"Total purchase line items: {len(prior_with_user):,}")
print(f"\nReorder rate overall: {prior_with_user['reordered'].mean():.2%}")

# Department popularity
prior_with_dept = prior_with_user.merge(
    products_full[['product_id', 'department']],
    on='product_id'
)

dept_counts = prior_with_dept['department'].value_counts()
print(f"\nTop 10 departments by purchase volume:")
print(dept_counts.head(10))

# ─────────────────────────────────────────
# SECTION 4: WHAT DOES A POWER USER LOOK LIKE?
# ─────────────────────────────────────────
print("\n" + "=" * 50)
print("SECTION 4: POWER USER PROFILE")
print("=" * 50)

# Orders per user
total_orders = orders.groupby('user_id')['order_number'].max()

# Reorder rate per user
reorder_rate = prior_with_user.groupby('user_id')['reordered'].mean()

# Department diversity per user
dept_div = prior_with_dept.groupby('user_id')['department'].nunique()

# Avg basket size per user
basket = prior_with_user.groupby(
    ['user_id', 'order_id']
).size().groupby('user_id').mean()

# Combine into user profile
user_profile = pd.DataFrame({
    'total_orders': total_orders,
    'reorder_rate': reorder_rate,
    'dept_diversity': dept_div,
    'avg_basket_size': basket
}).fillna(0)

print(f"\nAll users profile:")
print(user_profile.describe())

# Top 10% vs bottom 90%
threshold = user_profile['total_orders'].quantile(0.9)
power = user_profile[user_profile['total_orders'] >= threshold]
regular = user_profile[user_profile['total_orders'] < threshold]

print(f"\n--- Power Users (top 10% by orders) ---")
print(f"Count: {len(power):,}")
print(power.mean().round(2))

print(f"\n--- Regular Users (bottom 90%) ---")
print(f"Count: {len(regular):,}")
print(regular.mean().round(2))

print(f"\n--- How much more engaged are power users? ---")
for col in ['total_orders', 'reorder_rate', 'dept_diversity', 'avg_basket_size']:
    ratio = power[col].mean() / max(regular[col].mean(), 0.01)
    print(f"{col}: Power users have {ratio:.1f}x more")

# ─────────────────────────────────────────
# SECTION 5: HAPPY PATH HYPOTHESIS
# ─────────────────────────────────────────
print("\n" + "=" * 50)
print("SECTION 5: EARLY JOURNEY BEHAVIOR")
print("=" * 50)

# What departments do users buy in their first order?
first_orders = prior_with_dept[prior_with_dept['order_number'] == 1]
print("Most common departments in FIRST order:")
print(first_orders['department'].value_counts().head(10))

# What about second order?
second_orders = prior_with_dept[prior_with_dept['order_number'] == 2]
print("\nMost common departments in SECOND order:")
print(second_orders['department'].value_counts().head(10))

# Do power users start differently?
power_user_ids = set(power.index)
regular_user_ids = set(regular.index)

power_first = first_orders[
    first_orders['user_id'].isin(power_user_ids)
]['department'].value_counts().head(5)

regular_first = first_orders[
    first_orders['user_id'].isin(regular_user_ids)
]['department'].value_counts().head(5)

print("\nPower users' first order departments:")
print(power_first)
print("\nRegular users' first order departments:")
print(regular_first)

print("\n" + "=" * 50)
print("EXPLORATION COMPLETE")
print("=" * 50)
print("\nKey findings to remember:")
print(f"1. Total users: {orders['user_id'].nunique():,}")
print(f"2. Median orders per user: {orders_per_user.median():.0f}")
print(f"3. Power user threshold (top 10%): {threshold:.0f}+ orders")
print(f"4. Overall reorder rate: {prior_with_user['reordered'].mean():.2%}")