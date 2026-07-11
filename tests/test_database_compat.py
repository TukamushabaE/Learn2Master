import sqlite3

import init_db
from database import translate_sql_for_postgres


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
