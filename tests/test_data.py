import pandas as pd
import os

# Check files exist
files = [
    'data/raw/orders.csv',
    'data/raw/order_products__prior.csv', 
    'data/raw/products.csv',
    'data/raw/departments.csv',
]

print("=== Checking files ===")
for f in files:
    if os.path.exists(f):
        print(f"✅ Found: {f}")
    else:
        print(f"❌ Missing: {f}")

print("\n=== Loading and checking data ===")

# Orders
orders = pd.read_csv('data/raw/orders.csv')
print(f"\norders.csv:")
print(f"  Rows: {len(orders):,}")
print(f"  Columns: {orders.columns.tolist()}")
print(f"  Unique users: {orders['user_id'].nunique():,}")
print(orders.head(3))

# Products prior
prior = pd.read_csv('data/raw/order_products__prior.csv')
print(f"\norder_products__prior.csv:")
print(f"  Rows: {len(prior):,}")
print(f"  Columns: {prior.columns.tolist()}")
print(prior.head(3))

# Products
products = pd.read_csv('data/raw/products.csv')
print(f"\nproducts.csv:")
print(f"  Rows: {len(products):,}")
print(f"  Columns: {products.columns.tolist()}")
print(products.head(3))

# Departments
departments = pd.read_csv('data/raw/departments.csv')
print(f"\ndepartments.csv:")
print(departments)