import os
import sqlite3
import psycopg2

DATABASE_URL = os.environ.get("DATABASE_URL")

def run_sqlite():
    DB_NAME = "learn2master.db"
    if os.path.exists(DB_NAME):
        os.remove(DB_NAME)

    with open("database_v2.sql", "r", encoding="utf-8") as f:
        sql_script = f.read()

    conn = sqlite3.connect(DB_NAME)
    try:
        conn.executescript(sql_script)
        conn.commit()
        print("Learn2Master research-grade SQLite database created successfully!")
    except Exception as e:
        print("Error:", e)
    finally:
        conn.close()

def run_postgres(url):
    print("Initializing Supabase/PostgreSQL database...")
    try:
        conn = psycopg2.connect(url)
        conn.autocommit = True
        cur = conn.cursor()

        with open("database_v2.sql", "r", encoding="utf-8") as f:
            sql_script = f.read()

        commands = sql_script.split(';')
        for cmd in commands:
            cmd = cmd.strip()
            if not cmd or cmd.startswith('PRAGMA'):
                continue
            try:
                # Basic SQLite to Postgres conversion for simple cases
                cmd = cmd.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
                cmd = cmd.replace("DATETIME DEFAULT CURRENT_TIMESTAMP", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
                cur.execute(cmd)
            except Exception as cmd_e:
                if "DROP TABLE" not in cmd:
                    print(f"Warning on command: {cmd[:50]}... -> {cmd_e}")

        print("Learn2Master research-grade PostgreSQL database initialized!")
        conn.close()
    except Exception as e:
        print("PostgreSQL Error:", e)

if __name__ == "__main__":
    if DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")):
        run_postgres(DATABASE_URL)
    else:
        run_sqlite()
