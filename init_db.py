import argparse
import os
import re
import sqlite3

from env_loader import load_local_env

load_local_env()

try:
    import psycopg2
except ImportError:  # pragma: no cover - SQLite-only environments do not need psycopg2.
    psycopg2 = None

from database import normalize_database_url, is_postgres_url, sqlite_path_from_url

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(BASE_DIR, "database_v2.sql")
DEFAULT_SQLITE_DB = os.path.join(BASE_DIR, "learn2master.db")

ASSESSMENT_ATTEMPT_TIMING_COLUMNS = {
    "started_at": "TEXT",
    "completed_at": "TEXT",
    "time_spent_seconds": "INTEGER",
}

TEACHER_KB_UPLOAD_COLUMNS = {
    "processed_text": "TEXT",
    "content_hash": "TEXT",
    "mime_type": "TEXT",
    "storage_provider": "TEXT DEFAULT 'database_summary'",
    "storage_bucket": "TEXT",
    "storage_path": "TEXT",
    "storage_status": "TEXT DEFAULT 'Processed summary persisted; original not cloud-stored'",
}

TABLE_COLUMN_EXTENSIONS = {
    "assessment_attempts": ASSESSMENT_ATTEMPT_TIMING_COLUMNS,
    "teacher_kb_uploads": TEACHER_KB_UPLOAD_COLUMNS,
    "research_participants": {
        "enrolled_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
        "withdrawn_at": "TEXT",
        "updated_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
    },
    "research_questionnaires": {
        "study_phase": "TEXT DEFAULT 'Pilot'",
    },
    "research_questionnaire_items": {
        "required": "INTEGER DEFAULT 1",
    },
    "research_questionnaire_responses": {
        "started_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
        "completion_status": "TEXT DEFAULT 'Submitted'",
    },
    "recommendations": {
        "viewed_at": "TEXT",
        "first_response_at": "TEXT",
        "followed_at": "TEXT",
        "response_evidence": "TEXT",
    },
    "teacher_interventions": {
        "intervention_reason": "TEXT",
        "responded_at": "TEXT",
        "updated_at": "TEXT DEFAULT CURRENT_TIMESTAMP",
    },
    "teacher_feedback": {
        "responded_at": "TEXT",
    },
}

SCHEMA_MIGRATIONS = (
    (
        "20260715_01_additive_current_schema",
        "Create missing current application and research tables without dropping data",
    ),
    (
        "20260715_02_research_evaluation_columns",
        "Add timing, consent lifecycle, feedback responsiveness, storage and evaluation columns",
    ),
    (
        "20260715_03_research_indexes",
        "Add indexes used by assessment pairing, mastery, questionnaires and reliability reports",
    ),
)


def split_sql_statements(sql_script):
    statements = []
    current = []
    in_single = False
    in_double = False
    previous = ""
    for char in sql_script:
        if char == "'" and not in_double and previous != "\\":
            in_single = not in_single
        elif char == '"' and not in_single and previous != "\\":
            in_double = not in_double

        if char == ";" and not in_single and not in_double:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
        else:
            current.append(char)
        previous = char

    trailing = "".join(current).strip()
    if trailing:
        statements.append(trailing)
    return statements


def _table_name_from_create(statement):
    match = re.match(
        r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([a-zA-Z_][\w]*)",
        statement,
        flags=re.IGNORECASE,
    )
    return match.group(1) if match else None


def _strip_comment_lines(statement):
    return "\n".join(
        line for line in statement.splitlines()
        if not line.strip().startswith("--")
    ).strip()


def _make_create_idempotent(statement):
    return re.sub(
        r"^CREATE\s+TABLE\s+(?!IF\s+NOT\s+EXISTS)",
        "CREATE TABLE IF NOT EXISTS ",
        statement,
        flags=re.IGNORECASE,
    )


def _make_seed_insert_idempotent(statement):
    if not re.match(r"\s*INSERT\s+INTO\s+(roles|schools|subjects)\b", statement, flags=re.IGNORECASE):
        return statement
    if " ON CONFLICT" in statement.upper():
        return statement
    return f"{statement.rstrip()} ON CONFLICT DO NOTHING"


def _sqlite_statement(statement, reset=False):
    cleaned = _strip_comment_lines(statement)
    upper = cleaned.upper()
    if upper.startswith("PRAGMA"):
        return cleaned
    if upper.startswith("DROP TABLE"):
        return cleaned if reset else None
    if upper.startswith("CREATE TABLE"):
        cleaned = _make_create_idempotent(cleaned)
    cleaned = _make_seed_insert_idempotent(cleaned)
    return cleaned


def _postgres_statement(statement, reset=False):
    cleaned = _strip_comment_lines(statement)
    upper = cleaned.upper()
    if not cleaned or upper.startswith("PRAGMA"):
        return None
    if upper.startswith("DROP TABLE"):
        if not reset:
            return None
        match = re.match(r"DROP\s+TABLE\s+IF\s+EXISTS\s+([a-zA-Z_][\w]*)", cleaned, flags=re.IGNORECASE)
        return f"DROP TABLE IF EXISTS {match.group(1)} CASCADE" if match else cleaned

    if upper.startswith("CREATE TABLE"):
        cleaned = _make_create_idempotent(cleaned)
        cleaned = cleaned.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
        cleaned = re.sub(
            r"\b([a-zA-Z_]\w*(?:_at|_until))\s+TEXT\b",
            r"\1 TIMESTAMP",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = cleaned.replace("CHECK (resource_type IN", "CHECK (resource_type IN")

    cleaned = _make_seed_insert_idempotent(cleaned)
    return cleaned


def schema_statements(dialect, reset=False):
    with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
        raw_statements = split_sql_statements(schema_file.read())

    converter = _postgres_statement if dialect == "postgres" else _sqlite_statement
    statements = [converter(statement, reset=reset) for statement in raw_statements]
    statements = [statement for statement in statements if statement]

    if dialect == "postgres":
        # PostgreSQL requires referenced tables to exist before foreign keys are declared.
        deferred_tables = {"teacher_subject_assignments"}
        immediate = []
        deferred = []
        for statement in statements:
            table_name = _table_name_from_create(statement)
            if table_name in deferred_tables:
                deferred.append(statement)
            else:
                immediate.append(statement)
        statements = immediate + deferred

    return statements


def ensure_sqlite_schema_extensions(conn):
    """Add non-destructive columns needed by newer research releases."""
    for table_name, columns in TABLE_COLUMN_EXTENSIONS.items():
        table = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        if not table:
            continue
        existing = {
            row[1]
            for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, column_type in columns.items():
            if column_name not in existing:
                conn.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                )


def ensure_postgres_schema_extensions(cur):
    for table_name, columns in TABLE_COLUMN_EXTENSIONS.items():
        for column_name, column_type in columns.items():
            postgres_type = column_type
            if column_name.endswith(("_at", "_until")) and column_type.upper().startswith("TEXT"):
                postgres_type = re.sub(r"^TEXT", "TIMESTAMP", column_type, flags=re.IGNORECASE)
            cur.execute(
                f"ALTER TABLE {table_name} ADD COLUMN IF NOT EXISTS {column_name} {postgres_type}"
            )


def _additive_schema_statements(dialect):
    return [
        statement
        for statement in schema_statements(dialect, reset=False)
        if statement.lstrip().upper().startswith(("CREATE TABLE", "CREATE INDEX"))
    ]


def _record_sqlite_migrations(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for version, description in SCHEMA_MIGRATIONS:
        conn.execute("""
            INSERT OR IGNORE INTO schema_migrations (version, description)
            VALUES (?, ?)
        """, (version, description))


def _record_postgres_migrations(cur):
    cur.execute("""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    for version, description in SCHEMA_MIGRATIONS:
        cur.execute("""
            INSERT INTO schema_migrations (version, description)
            VALUES (%s, %s)
            ON CONFLICT (version) DO NOTHING
        """, (version, description))


def latest_schema_version(conn):
    try:
        row = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else "unversioned"
    except Exception:
        return "unversioned"


def ensure_current_schema(url=None):
    """Apply idempotent additive migrations to an existing database."""
    normalized_url = normalize_database_url(url)
    if is_postgres_url(normalized_url):
        if not psycopg2:
            raise RuntimeError("psycopg2-binary is required for PostgreSQL schema upgrades.")
        conn = psycopg2.connect(normalized_url)
        try:
            with conn.cursor() as cur:
                statements = _additive_schema_statements("postgres")
                for statement in statements:
                    if statement.lstrip().upper().startswith("CREATE TABLE"):
                        cur.execute(statement)
                ensure_postgres_schema_extensions(cur)
                for statement in statements:
                    if statement.lstrip().upper().startswith("CREATE INDEX"):
                        cur.execute(statement)
                _record_postgres_migrations(cur)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        return

    db_path = sqlite_path_from_url(normalized_url)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        statements = _additive_schema_statements("sqlite")
        for statement in statements:
            if statement.lstrip().upper().startswith("CREATE TABLE"):
                conn.execute(statement)
        ensure_sqlite_schema_extensions(conn)
        for statement in statements:
            if statement.lstrip().upper().startswith("CREATE INDEX"):
                conn.execute(statement)
        _record_sqlite_migrations(conn)
        conn.commit()
    finally:
        conn.close()


def run_sqlite(db_path=None, reset=False):
    db_path = db_path or DEFAULT_SQLITE_DB
    if reset and os.path.exists(db_path):
        os.remove(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        for statement in schema_statements("sqlite", reset=reset):
            conn.execute(statement)
        ensure_sqlite_schema_extensions(conn)
        _record_sqlite_migrations(conn)
        conn.commit()
        print(f"Learn2Master SQLite database initialized at {db_path}.")
    finally:
        conn.close()


def run_postgres(url=None, reset=False):
    url = normalize_database_url(url)
    if not url:
        raise RuntimeError("DATABASE_URL is required for PostgreSQL initialization.")
    if not psycopg2:
        raise RuntimeError("psycopg2-binary is required for PostgreSQL initialization.")

    print("Initializing Learn2Master PostgreSQL database...")
    conn = psycopg2.connect(url)
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            for statement in schema_statements("postgres", reset=reset):
                cur.execute(statement)
            ensure_postgres_schema_extensions(cur)
            _record_postgres_migrations(cur)
        conn.commit()
        print("Learn2Master PostgreSQL database initialized safely.")
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Initialize the Learn2Master database.")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate tables. Use only for local/dev test databases.")
    parser.add_argument("--sqlite-path", help="Override the local SQLite database path.")
    args = parser.parse_args()

    db_url = normalize_database_url()
    if is_postgres_url(db_url):
        run_postgres(db_url, reset=args.reset)
    else:
        run_sqlite(db_path=args.sqlite_path or sqlite_path_from_url(db_url), reset=args.reset)


if __name__ == "__main__":
    main()
