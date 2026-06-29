import os
import sqlite3
import psycopg2
from werkzeug.security import generate_password_hash

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_connection():
    if DATABASE_URL and (DATABASE_URL.startswith("postgres://") or DATABASE_URL.startswith("postgresql://")):
        conn = psycopg2.connect(DATABASE_URL)
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

# Roles
for role in ['learner', 'teacher', 'school_admin', 'super_admin', 'researcher', 'parent']:
    execute("INSERT INTO roles (role_name, display_name) SELECT ?, ? WHERE NOT EXISTS (SELECT 1 FROM roles WHERE role_name=?)", (role, role.replace('_', ' ').title(), role))

# School
execute("INSERT INTO schools (school_name) SELECT ? WHERE NOT EXISTS (SELECT 1 FROM schools WHERE school_name=?)", ('Kigezi High School', 'Kigezi High School'))

conn.commit()

learner_role = get_id("SELECT role_id FROM roles WHERE role_name='learner'")
teacher_role = get_id("SELECT role_id FROM roles WHERE role_name='teacher'")
school_admin_role = get_id("SELECT role_id FROM roles WHERE role_name='school_admin'")
super_admin_role = get_id("SELECT role_id FROM roles WHERE role_name='super_admin'")
school_id = get_id("SELECT school_id FROM schools WHERE school_name='Kigezi High School'")

# Users
users = [
    ('elijah', 'Elijah Tukamushaba', 'elijah@example.com', '12345', learner_role, school_id, 'Learner', 1),
    ('teacher', 'Master Teacher', 'teacher@example.com', '12345', teacher_role, school_id, 'Physics Teacher', 3),
    ('admin', 'School Admin', 'admin@example.com', '12345', school_admin_role, school_id, 'Administrator', 5),
    ('superadmin', 'System Super Admin', 'super@example.com', '12345', super_admin_role, None, 'Super Admin', 10),
]

for username, full_name, email, password, role_id, sid, title, security_level in users:
    execute("""
        INSERT INTO users (username, full_name, email, password_hash, role_id, school_id, security_level, account_status, approved_at)
        SELECT ?, ?, ?, ?, ?, ?, ?, 'Active', CURRENT_TIMESTAMP
        WHERE NOT EXISTS (SELECT 1 FROM users WHERE username=?)
    """, (username, full_name, email, generate_password_hash(password), role_id, sid, security_level, username))

# Subjects
execute("INSERT INTO subjects (subject_name) SELECT ? WHERE NOT EXISTS (SELECT 1 FROM subjects WHERE subject_name=?)", ('Physics', 'Physics'))
execute("INSERT INTO subjects (subject_name) SELECT ? WHERE NOT EXISTS (SELECT 1 FROM subjects WHERE subject_name=?)", ('ICT', 'ICT'))
conn.commit()

phy_id = get_id("SELECT subject_id FROM subjects WHERE subject_name='Physics'")
ict_id = get_id("SELECT subject_id FROM subjects WHERE subject_name='ICT'")

# Competencies
execute("INSERT INTO competencies (subject_id, competency_code, competency_name) SELECT ?, 'ICT-C1', 'Basic ICT Operations' WHERE NOT EXISTS (SELECT 1 FROM competencies WHERE competency_code='ICT-C1')", (ict_id,))
ict_c1 = get_id("SELECT competency_id FROM competencies WHERE competency_code='ICT-C1'")

# Learning Outcomes
execute("INSERT INTO learning_outcomes (competency_id, outcome_code, outcome_name, sequence_order, mastery_threshold) SELECT ?, 'ICT-LO1', 'Understanding Computer Systems', 1, 80 WHERE NOT EXISTS (SELECT 1 FROM learning_outcomes WHERE outcome_code='ICT-LO1')", (ict_c1,))
execute("INSERT INTO learning_outcomes (competency_id, outcome_code, outcome_name, sequence_order, mastery_threshold) SELECT ?, 'ICT-LO2', 'Operating Systems', 2, 80 WHERE NOT EXISTS (SELECT 1 FROM learning_outcomes WHERE outcome_code='ICT-LO2')", (ict_c1,))
ict_lo1 = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code='ICT-LO1'")
ict_lo2 = get_id("SELECT outcome_id FROM learning_outcomes WHERE outcome_code='ICT-LO2'")

# Lessons
execute("INSERT INTO lessons (course_id, outcome_id, lesson_title, sequence_order) SELECT 1, ?, 'Intro to Computers', 1 WHERE NOT EXISTS (SELECT 1 FROM lessons WHERE lesson_title='Intro to Computers')", (ict_lo1,))
lesson1 = get_id("SELECT lesson_id FROM lessons WHERE lesson_title='Intro to Computers'")

# Assessments
for atype in ['pretest', 'practice', 'posttest']:
    execute("INSERT INTO assessments (lesson_id, assessment_type, assessment_title) SELECT ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM assessments WHERE lesson_id=? AND assessment_type=?)", (lesson1, atype, atype.title(), lesson1, atype))

# Mastery Record
elijah_id = get_id("SELECT user_id FROM users WHERE username='elijah'")
execute("INSERT INTO mastery_records (learner_id, outcome_id, mastery_level, mastery_status, is_unlocked) SELECT ?, ?, 'Beginning', 'Not Started', 1 WHERE NOT EXISTS (SELECT 1 FROM mastery_records WHERE learner_id=? AND outcome_id=?)", (elijah_id, ict_lo1, elijah_id, ict_lo1))

# System Settings
settings = [
    ("ai_adaptivity_level", "balanced", "AI & Personalization Settings", "select"),
    ("at_risk_threshold", "60", "Notifications & Interventions", "number"),
]
for k, v, category, stype in settings:
    execute("INSERT INTO system_settings (setting_key, setting_value, setting_category, setting_type) SELECT ?, ?, ?, ? WHERE NOT EXISTS (SELECT 1 FROM system_settings WHERE setting_key=?)", (k, v, category, stype, k))

conn.commit()
print("Cloud-ready seed completed.")
conn.close()
