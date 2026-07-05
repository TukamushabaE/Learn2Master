import os
import sqlite3
import logging
from werkzeug.security import generate_password_hash

try:
    import psycopg2
except ImportError:
    psycopg2 = None

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_connection():
    if DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")):
        if not psycopg2:
            raise ImportError("psycopg2 is required for PostgreSQL support")
        url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
        conn = psycopg2.connect(url)
        return conn, conn.cursor(), "%s"
    else:
        conn = sqlite3.connect("learn2master.db")
        conn.row_factory = sqlite3.Row
        return conn, conn.cursor(), "?"

conn, cur, p = get_connection()

def get_id(query, params=()):
    q = query.replace("?", p)
    cur.execute(q, params)
    row = cur.fetchone()
    return row[0] if row else None

def execute(query, params=()):
    q = query.replace("?", p)
    cur.execute(q, params)

# --- Start Seeding ---
logger.info("Starting seed process...")

# Roles
roles = [
    ('super_admin', 'Super Administrator'),
    ('school_admin', 'School Administrator'),
    ('teacher', 'Teacher'),
    ('learner', 'Learner'),
]

for name, display in roles:
    execute("INSERT INTO roles (role_name, display_name) SELECT ?, ? WHERE NOT EXISTS (SELECT 1 FROM roles WHERE role_name=?)", (name, display, name))

# School
execute("INSERT INTO schools (school_name) SELECT ? WHERE NOT EXISTS (SELECT 1 FROM schools WHERE school_name=?)", ('Kigezi High School', 'Kigezi High School'))
school_id = get_id("SELECT school_id FROM schools WHERE school_name='Kigezi High School'")

# Users
pwd_hash = generate_password_hash('12345')
users = [
    ('admin', 'Admin User', 'super_admin'),
    ('teacher', 'Main Teacher', 'teacher'),
    ('elijah', 'Elijah Learner', 'learner'),
]

for username, full_name, role_name in users:
    role_id = get_id("SELECT role_id FROM roles WHERE role_name=?", (role_name,))
    execute("""
        INSERT INTO users (username, full_name, password_hash, role_id, school_id, account_status, must_change_password)
        SELECT ?, ?, ?, ?, ?, 'Active', 0
        WHERE NOT EXISTS (SELECT 1 FROM users WHERE username=?)
    """, (username, full_name, pwd_hash, role_id, school_id, username))

conn.commit()

# Subjects
execute("INSERT INTO subjects (subject_name) SELECT ? WHERE NOT EXISTS (SELECT 1 FROM subjects WHERE subject_name=?)", ('ICT', 'ICT'))
ict_id = get_id("SELECT subject_id FROM subjects WHERE subject_name='ICT'")

execute("INSERT INTO subjects (subject_name) SELECT ? WHERE NOT EXISTS (SELECT 1 FROM subjects WHERE subject_name=?)", ('Physics', 'Physics'))
physics_id = get_id("SELECT subject_id FROM subjects WHERE subject_name='Physics'")

# Topics
topics = [
    (ict_id, 'Introduction to ICT'),
    (physics_id, 'Introduction to Physics'),
]

for sub_id, name in topics:
    execute("INSERT INTO topics (subject_id, topic_title) SELECT ?, ? WHERE NOT EXISTS (SELECT 1 FROM topics WHERE topic_title=? AND subject_id=?)", (sub_id, name, name, sub_id))

conn.commit()
logger.info("Seed process completed successfully!")
conn.close()
