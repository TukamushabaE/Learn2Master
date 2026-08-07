import sqlite3

import init_db
from database import PostgresConnectionWrapper, translate_sql_for_postgres
from services.evaluation_dataset import ensure_evaluation_dataset_schema


def test_postgres_query_translation_handles_sqlite_patterns():
    sql, pk = translate_sql_for_postgres(
        "INSERT OR IGNORE INTO schools (school_name) VALUES (?)"
    )
    assert "INSERT INTO schools" in sql
    assert "%s" in sql
    assert "ON CONFLICT DO NOTHING" in sql
    assert "RETURNING school_id" in sql
    assert pk == "school_id"

    sql, pk = translate_sql_for_postgres(
        "UPDATE users SET locked_until = datetime('now', '+1 day') WHERE user_id = ?"
    )
    assert "CURRENT_TIMESTAMP + INTERVAL '1 day'" in sql
    assert "%s" in sql
    assert pk is None

    sql, _ = translate_sql_for_postgres("SELECT last_insert_rowid()")
    assert sql == "SELECT lastval()"


def test_postgres_schema_statements_are_idempotent_and_safe():
    statements = init_db.schema_statements("postgres", reset=False)
    joined = "\n".join(statements).upper()

    assert "DROP TABLE" not in joined
    assert "PRAGMA" not in joined
    assert "AUTOINCREMENT" not in joined
    assert "CREATE TABLE IF NOT EXISTS USERS" in joined
    assert "SERIAL PRIMARY KEY" in joined
    assert "ON CONFLICT DO NOTHING" in joined

    subject_index = next(i for i, stmt in enumerate(statements) if "CREATE TABLE IF NOT EXISTS subjects" in stmt)
    assignment_index = next(i for i, stmt in enumerate(statements) if "CREATE TABLE IF NOT EXISTS teacher_subject_assignments" in stmt)
    assert assignment_index > subject_index


def test_evaluation_source_normalization_parameterizes_postgres_wildcard():
    class RecordingCursor:
        description = [("total", None, None, None, None, None, None)]
        rowcount = 0

        def __init__(self, raw_connection):
            self.raw_connection = raw_connection

        def execute(self, sql, parameters):
            self.raw_connection.executions.append((sql, parameters))
            return self

        def fetchone(self):
            return (0,)

        def close(self):
            return None

    class RecordingConnection:
        def __init__(self):
            self.executions = []
            self.committed = False

        def cursor(self):
            return RecordingCursor(self)

        def commit(self):
            self.committed = True

    raw_connection = RecordingConnection()
    connection = PostgresConnectionWrapper(raw_connection)

    ensure_evaluation_dataset_schema(connection)

    updates = [
        (sql, parameters)
        for sql, parameters in raw_connection.executions
        if sql.startswith("UPDATE ")
    ]
    assert len(updates) == 3
    assert raw_connection.committed is True
    for sql, parameters in updates:
        assert "LIKE %s" in sql
        assert "Dataset%.xlsx" not in sql
        assert parameters == (
            "Learn2Master_Evaluation_Register",
            "Learn2Master_Dataset%.xlsx",
        )


def test_sqlite_initialization_is_repeatable_without_deleting_data(tmp_path):
    db_path = tmp_path / "compat.db"
    init_db.run_sqlite(db_path=str(db_path), reset=True)

    conn = sqlite3.connect(db_path)
    conn.execute("INSERT INTO schools (school_name) VALUES (?)", ("Do Not Delete School",))
    conn.commit()
    conn.close()

    init_db.run_sqlite(db_path=str(db_path), reset=False)

    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM schools WHERE school_name=?",
            ("Do Not Delete School",),
        ).fetchone()
        assert row[0] == 1
        role_count = conn.execute("SELECT COUNT(*) FROM roles").fetchone()[0]
        assert role_count >= 4
    finally:
        conn.close()


def test_teacher_upload_schema_extensions_are_added_non_destructively(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE assessment_attempts (attempt_id INTEGER PRIMARY KEY)")
    conn.execute("""
        CREATE TABLE teacher_kb_uploads (
            upload_id INTEGER PRIMARY KEY,
            teacher_id INTEGER,
            filename TEXT,
            original_size_bytes INTEGER,
            summary_size_bytes INTEGER,
            created_at TEXT
        )
    """)
    init_db.ensure_sqlite_schema_extensions(conn)
    conn.commit()

    columns = {row[1] for row in conn.execute("PRAGMA table_info(teacher_kb_uploads)")}
    conn.close()
    assert {
        "processed_text", "content_hash", "mime_type", "storage_provider",
        "storage_bucket", "storage_path", "storage_status",
    } <= columns
