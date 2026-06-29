import os
import sqlite3

DB_NAME = "learn2master.db"

if os.path.exists(DB_NAME):
    os.remove(DB_NAME)

with open("database_v2.sql", "r", encoding="utf-8") as f:
    sql_script = f.read()

conn = sqlite3.connect(DB_NAME)
try:
    conn.executescript(sql_script)
    conn.commit()
    print("Learn2Master research-grade database created successfully!")
except Exception as e:
    print("Error:", e)
finally:
    conn.close()
