import os
import shutil
import sqlite3
import pytest
from app import app as flask_app
import database

PROJECT_DB = os.path.join(os.path.dirname(os.path.dirname(__file__)), "learn2master.db")

@pytest.fixture()
def app(tmp_path):
    db_path = tmp_path / "learn2master_test.db"
    if os.path.exists(PROJECT_DB):
        shutil.copyfile(PROJECT_DB, db_path)

    database.DATABASE = str(db_path)
    flask_app.config.update(
        SQLALCHEMY_DATABASE_URI=f"sqlite:///{db_path}",
        TESTING=True,
        SECRET_KEY="test-secret",
        CSRF_ENABLED=False, # Disable CSRF for testing convenience
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
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
