import sqlite3
con = sqlite3.connect('backend/data/taqueria.db')
for row in con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name LIKE '%recipe%';"):
    print(row[0])
