import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), 'backend', 'data', 'taqueria.db')

conn = sqlite3.connect(db_path)
cur = conn.cursor()

try:
    cur.execute("ALTER TABLE settings ADD COLUMN loyalty_enabled INTEGER DEFAULT 1")
    print("Added loyalty_enabled column to settings.")
except sqlite3.OperationalError as e:
    if "duplicate column name" in str(e).lower():
        print("Column loyalty_enabled already exists in settings.")
    else:
        print("Error adding loyalty_enabled:", e)

# Ensure there's at least one row in settings
cur.execute("INSERT OR IGNORE INTO settings (id) VALUES (1)")
conn.commit()
conn.close()
print("Database patch 2 complete.")
