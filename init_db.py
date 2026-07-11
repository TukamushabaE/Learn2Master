import argparse
import os
import re
import sqlite3

try:
    import psycopg2
except ImportError:  # pragma: no cover - SQLite-only environments do not need psycopg2.
    psycopg2 = None

from database import normalize_database_url, is_postgres_url, sqlite_path_from_url

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SCHEMA_PATH = os.path.join(BASE_DIR, "database_v2.sql")
DEFAULT_SQLITE_DB = os.path.join(BASE_DIR, "learn2master.db")


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
