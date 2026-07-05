import sqlite3
import os
import re

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    psycopg2 = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, "learn2master.db")

class PostgresCursorWrapper:
    def __init__(self, cursor):
        self.cursor = cursor

    def execute(self, sql, parameters=None):
        # Convert ? to %s
        sql = sql.replace('?', '%s')
        # Convert last_insert_rowid() to lastval()
        sql = sql.replace('last_insert_rowid()', 'lastval()')

        # Filter out PRAGMA
        if sql.strip().upper().startswith("PRAGMA"):
            return self

        if parameters:
            self.cursor.execute(sql, parameters)
        else:
            self.cursor.execute(sql)
        return self

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()

    def __iter__(self):
        return iter(self.cursor)

    @property
    def rowcount(self):
        return self.cursor.rowcount

class PostgresConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, parameters=None):
        cursor = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        wrapper = PostgresCursorWrapper(cursor)
        return wrapper.execute(sql, parameters)

    def commit(self):
        self.conn.commit()

    def close(self):
        self.conn.close()

    def cursor(self):
        cursor = self.conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        return PostgresCursorWrapper(cursor)

def get_db():
    db_url = os.environ.get("DATABASE_URL")
    if db_url and (db_url.startswith("postgres://") or db_url.startswith("postgresql://")):
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        if psycopg2:
            conn = psycopg2.connect(db_url)
            return PostgresConnectionWrapper(conn)

    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
