import sqlite3

con = sqlite3.connect('taqueria.db')
cur = con.cursor()
cur.execute("SELECT sql FROM sqlite_master WHERE type='table'")
rows = cur.fetchall()

for row in rows:
    if row[0]:
        print(row[0])

con.close()
