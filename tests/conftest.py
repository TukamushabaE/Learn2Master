import os
import shutil
import sqlite3
import subprocess
import sys
import pytest

# Pre-config
os.environ["TESTING"] = "1"
os.environ["FLASK_DEBUG"] = "1" # Disable HTTPS in Talisman

import database
import init_db

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DB = os.path.join(BASE_DIR, "learn2master.db")
MASTER_DB_DIR = os.path.join(BASE_DIR, ".tmp_test_data")
MASTER_DB = os.path.join(MASTER_DB_DIR, "learn2master.db")

@pytest.fixture(scope="session", autouse=True)
def master_db():
    env = os.environ.copy()
    os.makedirs(MASTER_DB_DIR, exist_ok=True)
    init_db.run_sqlite(db_path=MASTER_DB, reset=True)

    env.pop("DATABASE_URL", None)
    env["LEARN2MASTER_SQLITE_PATH"] = MASTER_DB
    env["LEARN2MASTER_SEED_LEARNER_PASSWORD"] = "12345"
    env["LEARN2MASTER_SEED_TEACHER_PASSWORD"] = "12345"
    env["LEARN2MASTER_SEED_SCHOOL_ADMIN_PASSWORD"] = "12345"
    env["LEARN2MASTER_SEED_SUPER_ADMIN_PASSWORD"] = "12345"
    subprocess.run([sys.executable, os.path.join(BASE_DIR, "seed_data.py")], cwd=MASTER_DB_DIR, env=env, check=True, capture_output=True)

@pytest.fixture()
def app(tmp_path):
    db_path = tmp_path / "test.db"
    shutil.copyfile(MASTER_DB, str(db_path))

    # Update globals
    database.DATABASE = str(db_path)
    os.environ["LEARN2MASTER_SQLITE_PATH"] = str(db_path)

    from app import app as flask_app
    from models import db as sqlalchemy_db

    flask_app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        TESTING=True,
        SECRET_KEY="test-secret",
        CSRF_ENABLED=False,
    )

    with flask_app.app_context():
        sqlalchemy_db.session.remove()
        sqlalchemy_db.engine.dispose()
        # Verify
        conn = sqlite3.connect(str(db_path))
        c = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        if not c.fetchone():
            raise RuntimeError("Users table missing after copy!")
        conn.close()

    yield flask_app

@pytest.fixture()
def client(app):
    return app.test_client()

@pytest.fixture()
def db(app):
    conn = sqlite3.connect(database.DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()

def csrf_token(client):
    return "test-csrf-token"

def login(client, username="elijah", password="12345"):
    return client.post(
        "/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )

def correct_answers(conn, assessment_id):
    rows = conn.execute("""
        SELECT q.question_id, qo.option_id
        FROM questions q
        JOIN question_options qo ON qo.question_id = q.question_id AND qo.is_correct = 1
        WHERE q.assessment_id = ?
    """, (assessment_id,)).fetchall()
    return {f"question_{row['question_id']}": str(row["option_id"]) for row in rows}

def assessment_id(conn, outcome_code, assessment_type):
    row = conn.execute("""
        SELECT a.assessment_id
        FROM assessments a
        JOIN lessons l ON a.lesson_id = l.lesson_id
        JOIN learning_outcomes lo ON l.outcome_id = lo.outcome_id
        WHERE lo.outcome_code = ? AND a.assessment_type = ?
    """, (outcome_code, assessment_type)).fetchone()
    assert row is not None
    return row["assessment_id"]

def outcome_id(conn, outcome_code):
    row = conn.execute("SELECT outcome_id FROM learning_outcomes WHERE outcome_code = ?", (outcome_code,)).fetchone()
    assert row is not None
    return row["outcome_id"]
