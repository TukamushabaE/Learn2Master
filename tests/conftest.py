import os
import shutil
import sqlite3

import pytest

import database
from app import app as flask_app


PROJECT_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "learn2master.db")


@pytest.fixture()
def app(tmp_path):
    db_path = tmp_path / "learn2master_test.db"
    shutil.copyfile(PROJECT_DB, db_path)
    database.DATABASE = str(db_path)
    flask_app.config.update(
        TESTING=True,
        SECRET_KEY="test-secret",
        CSRF_ENABLED=True,
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
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
    with client.session_transaction() as sess:
        token = sess.get("_csrf_token")
        if not token:
            token = "test-csrf-token"
            sess["_csrf_token"] = token
        return token


def login(client, username="elijah", password="12345"):
    client.get("/")
    return client.post(
        "/login",
        data={"username": username, "password": password, "csrf_token": csrf_token(client)},
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
