import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'backend', 'data', 'taqueria.db')

conn = sqlite3.connect(db_path)
cur = conn.cursor()

# 1. Create loyalty_customers table
try:
    cur.execute("""
        CREATE TABLE IF NOT EXISTS loyalty_customers (
            cedula TEXT PRIMARY KEY,
            name TEXT,
            points INTEGER DEFAULT 0
        )
    """)
    print("Table loyalty_customers created or already exists.")
except Exception as e:
    print("Error creating loyalty_customers:", e)

# 2. Add is_reward column to products
try:
    cur.execute("ALTER TABLE products ADD COLUMN is_reward INTEGER DEFAULT 0")
    print("Added is_reward column to products.")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("Column is_reward already exists in products.")
    else:
        print("Error adding is_reward:", e)

conn.commit()
conn.close()
print("Database patch complete.")
