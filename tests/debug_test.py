import database
import sqlite3
import os

def test_db_path():
    print(f"\nDATABASE path in test: {database.DATABASE}")
    if os.path.exists(database.DATABASE):
        conn = sqlite3.connect(database.DATABASE)
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]
        print(f"Tables in test DB: {tables}")
        conn.close()
    else:
        print("Test DB file does not exist!")

def test_user_count(db):
    cursor = db.execute("SELECT COUNT(*) FROM users")
    count = cursor.fetchone()[0]
    print(f"User count in test DB: {count}")
