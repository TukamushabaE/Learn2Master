"""Read-only integrity and data-collection readiness checks.

The checks deliberately report problems instead of changing research records.  This
keeps an audit review separate from any later, explicitly approved data correction.
"""

from datetime import datetime, timezone

from database import is_postgres_connection


REQUIRED_TABLES = {
    "research_participants": ("participant_code", "consent_status", "study_phase"),
    "assessment_attempts": ("learner_id", "assessment_id", "score", "attempted_at"),
    "mastery_records": ("learner_id", "outcome_id", "mastery_status"),
    "recommendations": ("learner_id", "outcome_id", "viewed_at", "followed_at"),
    "research_questionnaire_responses": ("questionnaire_id", "respondent_user_id"),
    "research_events": ("event_type", "event_status", "response_time_ms"),
    "schema_migrations": ("version", "applied_at"),
}


def _one(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return int(row[0] or 0) if row else 0


def _tables(conn):
    if is_postgres_connection(conn):
        return {row[0] for row in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
        ).fetchall()}
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}


def _columns(conn, table):
    if is_postgres_connection(conn):
        return {row[0] for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name=?", (table,)
        ).fetchall()}
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def integrity_report(conn):
    """Return categorized findings; never repair or delete data."""
    tables = _tables(conn)
    findings = []

    def add(category, severity, issue, count=0, action="Review the affected records before any correction."):
        findings.append({
            "category": category,
            "severity": severity,
            "issue": issue,
            "count": int(count or 0),
            "recommended_action": action,
        })

    for table, required_columns in REQUIRED_TABLES.items():
        if table not in tables:
            add("Schema", "Blocked", f"Required table is missing: {table}", 1,
                "Run the tracked additive database migration; do not recreate the production database.")
            continue
        missing = set(required_columns) - _columns(conn, table)
        if missing:
            add("Schema", "Blocked", f"{table} is missing columns: {', '.join(sorted(missing))}", len(missing),
                "Run the tracked additive database migration.")

    checks = [
        ("Participants", "Blocked", "Duplicate participant codes", """
            SELECT COUNT(*) FROM (
              SELECT participant_code FROM research_participants
              GROUP BY participant_code HAVING COUNT(*) > 1
            ) duplicates
        """),
        ("Participants", "Blocked", "Participant records without a user", """
            SELECT COUNT(*) FROM research_participants rp
            LEFT JOIN users u ON u.user_id=rp.user_id WHERE u.user_id IS NULL
        """),
        ("Assessment", "Blocked", "Assessment attempts without an assessment", """
            SELECT COUNT(*) FROM assessment_attempts aa
            LEFT JOIN assessments a ON a.assessment_id=aa.assessment_id WHERE a.assessment_id IS NULL
        """),
        ("Assessment", "Warning", "Assessment percentages outside 0–100", """
            SELECT COUNT(*) FROM assessment_attempts WHERE score < 0 OR score > 100
        """),
        ("Assessment", "Warning", "Negative recorded assessment duration", """
            SELECT COUNT(*) FROM assessment_attempts WHERE time_spent_seconds < 0
        """),
        ("Assessment", "Warning", "Post-tests without an earlier matching pre-test", """
            SELECT COUNT(*) FROM assessment_attempts post
            JOIN assessments pa ON pa.assessment_id=post.assessment_id AND pa.assessment_type='posttest'
            JOIN lessons pl ON pl.lesson_id=pa.lesson_id
            WHERE NOT EXISTS (
              SELECT 1 FROM assessment_attempts pre
              JOIN assessments pra ON pra.assessment_id=pre.assessment_id AND pra.assessment_type='pretest'
              JOIN lessons prl ON prl.lesson_id=pra.lesson_id
              WHERE pre.learner_id=post.learner_id AND prl.outcome_id=pl.outcome_id
                AND COALESCE(pre.completed_at,pre.attempted_at) <= COALESCE(post.completed_at,post.attempted_at)
            )
        """),
        ("Curriculum", "Blocked", "Assessments not connected to a learning outcome", """
            SELECT COUNT(*) FROM assessments a LEFT JOIN lessons l ON l.lesson_id=a.lesson_id
            LEFT JOIN learning_outcomes lo ON lo.outcome_id=l.outcome_id WHERE lo.outcome_id IS NULL
        """),
        ("Mastery", "Blocked", "Mastery records without a learner", """
            SELECT COUNT(*) FROM mastery_records mr LEFT JOIN users u ON u.user_id=mr.learner_id
            WHERE u.user_id IS NULL
        """),
        ("Mastery", "Warning", "Mastered records below the configured 80% evidence threshold", """
            SELECT COUNT(*) FROM mastery_records
            WHERE mastery_status='Mastered' AND COALESCE(mastery_score,0) < 80
        """),
        ("Questionnaire", "Blocked", "Questionnaire answers without a response", """
            SELECT COUNT(*) FROM research_questionnaire_answers a
            LEFT JOIN research_questionnaire_responses r ON r.id=a.response_id WHERE r.id IS NULL
        """),
    ]
    for category, severity, issue, sql in checks:
        required = {
            "Participants": "research_participants",
            "Assessment": "assessment_attempts",
            "Curriculum": "assessments",
            "Mastery": "mastery_records",
            "Questionnaire": "research_questionnaire_answers",
        }[category]
        if required not in tables:
            continue
        try:
            count = _one(conn, sql)
        except Exception as exc:
            add(category, "Blocked", f"Check could not run: {issue} ({type(exc).__name__})", 1)
        else:
            add(category, severity if count else "Ready", issue, count,
                "No action required." if not count else "Inspect the listed category; preserve an audit trail for approved corrections.")

    counts = {
        "blocked": sum(1 for item in findings if item["severity"] == "Blocked"),
        "warnings": sum(1 for item in findings if item["severity"] == "Warning"),
        "passed": sum(1 for item in findings if item["severity"] == "Ready"),
    }
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "findings": findings,
        "summary": counts,
        "overall_status": "Blocked" if counts["blocked"] else ("Warning" if counts["warnings"] else "Ready"),
    }


def readiness_report(conn):
    integrity = integrity_report(conn)
    tables = _tables(conn)

    def count(sql):
        try:
            return _one(conn, sql)
        except Exception:
            return 0

    participant_count = count("""
        SELECT COUNT(*) FROM research_participants
        WHERE active_status='Active' AND consent_status='Granted'
          AND assent_status IN ('Granted','Not Applicable')
          AND parent_consent_status IN ('Granted','Not Applicable')
    """)
    checks = [
        ("Tracked schema migrations", "schema_migrations" in tables and count("SELECT COUNT(*) FROM schema_migrations") > 0,
         "At least one additive migration must be recorded."),
        ("Consented participant register", participant_count > 0,
         f"{participant_count} eligible participant(s) are recorded."),
        ("Physics and ICT curriculum", count("SELECT COUNT(DISTINCT subject_name) FROM subjects WHERE LOWER(subject_name) IN ('physics','ict')") >= 2,
         "Both research subjects must be configured."),
        ("Pre/practice/post assessment sequence", count("SELECT COUNT(DISTINCT assessment_type) FROM assessments WHERE assessment_type IN ('pretest','practice','posttest')") >= 3,
         "All three assessment stages must be configured."),
        ("Assessment items", count("SELECT COUNT(*) FROM questions") > 0,
         "Assessments require scored items."),
        ("AI recommendation evidence", "recommendations" in tables,
         "Recommendation generation, viewing and follow-through fields must exist."),
        ("Mastery evidence", "mastery_records" in tables,
         "Mastery records must be available."),
        ("Teacher oversight evidence", count("SELECT COUNT(*) FROM teacher_interventions") > 0,
         "Collect at least one teacher intervention during the study."),
        ("Questionnaire instruments", count("SELECT COUNT(*) FROM research_questionnaires WHERE active_status='Active'") > 0,
         "At least one active instrument must be available."),
        ("Operational event logging", "research_events" in tables,
         "Request success/failure and timing events must be logged."),
        ("Data integrity", integrity["overall_status"] != "Blocked",
         f"Integrity status is {integrity['overall_status']}."),
    ]
    items = [{
        "item": name,
        "status": "Ready" if ready else "Blocked",
        "evidence": evidence,
    } for name, ready, evidence in checks]
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "items": items,
        "summary": {
            "ready": sum(1 for item in items if item["status"] == "Ready"),
            "blocked": sum(1 for item in items if item["status"] == "Blocked"),
        },
        "overall_status": "Ready" if all(item["status"] == "Ready" for item in items) else "Blocked",
        "integrity": integrity,
    }
