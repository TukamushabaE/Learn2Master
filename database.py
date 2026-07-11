import os
import re
import sqlite3
from collections.abc import Mapping
from datetime import date, datetime

try:
    import psycopg2
    import psycopg2.errors
except ImportError:  # pragma: no cover - local SQLite development can run without psycopg2.
    psycopg2 = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.environ.get("LEARN2MASTER_SQLITE_PATH") or os.path.join(BASE_DIR, "learn2master.db")

# Routes import this instead of binding themselves to sqlite3-specific errors.
DatabaseIntegrityError = sqlite3.IntegrityError

PRIMARY_KEYS = {
    "roles": "role_id",
    "schools": "school_id",
    "users": "user_id",
    "classes": "class_id",
    "terms": "term_id",
    "enrollments": "enrollment_id",
    "teacher_subject_assignments": "assignment_id",
    "subjects": "subject_id",
    "topics": "topic_id",
    "strands": "strand_id",
    "sub_strands": "sub_strand_id",
    "competencies": "competency_id",
    "learning_outcomes": "outcome_id",
    "performance_indicators": "indicator_id",
    "success_criteria": "criteria_id",
    "generic_skills": "skill_id",
    "curriculum_values": "value_id",
    "cross_cutting_issues": "issue_id",
    "courses": "course_id",
    "concepts": "concept_id",
    "lessons": "lesson_id",
    "learning_activities": "activity_id",
    "adaptive_notes": "note_id",
    "adaptive_videos": "video_id",
    "learning_resources": "resource_id",
    "assessments": "assessment_id",
    "questions": "question_id",
    "question_options": "option_id",
    "assessment_attempts": "attempt_id",
    "attempt_answers": "answer_id",
    "concept_mastery": "concept_mastery_id",
    "mastery_records": "mastery_id",
    "recommendations": "recommendation_id",
    "activity_logs": "log_id",
    "activity_submissions": "submission_id",
    "activity_feedback": "feedback_id",
    "learner_profiles": "profile_id",
    "learning_reflections": "reflection_id",
    "teacher_interventions": "intervention_id",
    "teacher_feedback": "feedback_id",
    "evidence_portfolio": "evidence_id",
    "ai_explanations": "explanation_id",
    "research_participants": "id",
    "research_questionnaires": "id",
    "research_questionnaire_items": "id",
    "research_questionnaire_responses": "id",
    "research_questionnaire_answers": "id",
    "offline_sync_queue": "sync_id",
    "sync_queue": "queue_id",
    "offline_activity_logs": "offline_log_id",
    "sync_events": "sync_event_id",
    "cached_resources": "cached_id",
    "worked_examples": "example_id",
    "practical_evidence": "practical_id",
    "bkt_mastery": "bkt_id",
    "system_settings": "setting_id",
    "rubric_criteria": "rubric_id",
    "rubric_assessments": "assessment_id",
    "teacher_mastery_reviews": "review_id",
    "backups": "backup_id",
    "student_subject_assignments": "assignment_id",
    "teacher_kb_uploads": "upload_id",
    "audit_logs": "audit_id",
}


def normalize_database_url(url=None):
    url = url or os.environ.get("DATABASE_URL")
    if url and url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql://", 1)
    return url


def is_postgres_url(url=None):
    url = normalize_database_url(url)
    return bool(url and url.startswith("postgresql://"))


def sqlite_path_from_url(url=None):
    url = url or os.environ.get("DATABASE_URL")
    if not url or not url.startswith("sqlite:///"):
        return os.environ.get("LEARN2MASTER_SQLITE_PATH") or DATABASE
    path = url.replace("sqlite:///", "", 1)
    if path == ":memory:":
        return path
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    return path


def is_postgres_connection(conn):
    return isinstance(conn, PostgresConnectionWrapper)


def _normalize_value(value):
    if isinstance(value, datetime):
        return value.isoformat(sep=" ", timespec="seconds")
    if isinstance(value, date):
        return value.isoformat()
    return value


class CrossDbRow(Mapping):
    """Small row object that supports both row[0] and row["column"] access."""

    def __init__(self, columns, values):
        self._columns = list(columns)
        self._values = [_normalize_value(value) for value in values]
        self._index = {column: pos for pos, column in enumerate(self._columns)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._values[self._index[key]]

    def __iter__(self):
        return iter(self._columns)

    def __len__(self):
        return len(self._columns)

    def keys(self):
        return self._columns

    def get(self, key, default=None):
        return self[key] if key in self._index else default

    def as_dict(self):
        return {column: self[column] for column in self._columns}


def _append_returning_if_needed(sql):
    lowered = sql.lower()
    if not lowered.lstrip().startswith("insert into ") or " returning " in lowered:
        return sql, None

    match = re.match(r"\s*insert\s+into\s+([a-zA-Z_][\w]*)", sql, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return sql, None

    table = match.group(1)
    pk = PRIMARY_KEYS.get(table)
    if not pk:
        return sql, None

    stripped = sql.rstrip()
    semicolon = ";" if stripped.endswith(";") else ""
    if semicolon:
        stripped = stripped[:-1].rstrip()
    return f"{stripped} RETURNING {pk}{semicolon}", pk


def translate_sql_for_postgres(sql):
    translated = sql.strip() if sql.strip().upper().startswith("PRAGMA") else sql
    if translated.strip().upper().startswith("PRAGMA"):
        return None, None

    translated = re.sub(
        r"\bINSERT\s+OR\s+IGNORE\s+INTO\b",
        "INSERT INTO",
        translated,
        flags=re.IGNORECASE,
    )
    inserted_ignore = translated != sql

    translated = translated.replace("?", "%s")
    translated = re.sub(r"last_insert_rowid\s*\(\s*\)", "lastval()", translated, flags=re.IGNORECASE)
    translated = re.sub(
        r"datetime\s*\(\s*'now'\s*,\s*'\+1 day'\s*\)",
        "(CURRENT_TIMESTAMP + INTERVAL '1 day')",
        translated,
        flags=re.IGNORECASE,
    )

    if inserted_ignore and " on conflict" not in translated.lower():
        stripped = translated.rstrip()
        semicolon = ";" if stripped.endswith(";") else ""
        if semicolon:
            stripped = stripped[:-1].rstrip()
        translated = f"{stripped} ON CONFLICT DO NOTHING{semicolon}"

    return _append_returning_if_needed(translated)


class PostgresCursorWrapper:
    def __init__(self, conn, cursor=None):
        self.conn = conn
        self.cursor = cursor or conn.cursor()
        self.lastrowid = None
        self._buffered_rows = None
        self._buffered_index = 0

    def execute(self, sql, parameters=None):
        translated, returning_pk = translate_sql_for_postgres(sql)
        if translated is None:
            self._buffered_rows = []
            return self

        self._buffered_rows = None
        self._buffered_index = 0
        self.lastrowid = None

        try:
            self.cursor.execute(translated, parameters or ())
            if returning_pk:
                row = self.cursor.fetchone()
                if row is not None:
                    self.lastrowid = row[0]
        except psycopg2.IntegrityError as exc:
            raise DatabaseIntegrityError(str(exc)) from exc

        return self

    def _row_from_values(self, values):
        if values is None:
            return None
        columns = [description[0] for description in self.cursor.description or []]
        return CrossDbRow(columns, values)

    def fetchone(self):
        if self._buffered_rows is not None:
            if self._buffered_index >= len(self._buffered_rows):
                return None
            row = self._buffered_rows[self._buffered_index]
            self._buffered_index += 1
            return row
        return self._row_from_values(self.cursor.fetchone())

    def fetchall(self):
        if self._buffered_rows is not None:
            rows = self._buffered_rows[self._buffered_index:]
            self._buffered_index = len(self._buffered_rows)
            return rows
        return [self._row_from_values(row) for row in self.cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def close(self):
        self.cursor.close()


class PostgresConnectionWrapper:
    def __init__(self, conn):
        self.conn = conn

    def execute(self, sql, parameters=None):
        cursor = PostgresCursorWrapper(self.conn)
        return cursor.execute(sql, parameters)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

    def cursor(self):
        return PostgresCursorWrapper(self.conn)


def get_db():
    db_url = normalize_database_url()
    if is_postgres_url(db_url):
        if not psycopg2:
            raise RuntimeError("DATABASE_URL is PostgreSQL, but psycopg2 is not installed.")
        conn = psycopg2.connect(db_url)
        return PostgresConnectionWrapper(conn)

    sqlite_path = sqlite_path_from_url(db_url)
    conn = sqlite3.connect(sqlite_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
