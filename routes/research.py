import csv
import io
import math
import re
from datetime import datetime, timezone
from statistics import stdev

from flask import Blueprint, Response, flash, redirect, render_template, request, session, url_for

from database import DatabaseIntegrityError, get_db
from routes.guards import role_required
from security import csrf_protect
from services.research_analytics import (
    learning_gain_summary as centralized_learning_gain_summary,
    paired_learning_gain_rows,
)
from services.research_integrity import integrity_report, readiness_report
from services.research_reporting import (
    feedback_responsiveness_rows,
    feedback_responsiveness_summary,
    reliability_rows as operational_reliability_rows,
    reliability_summary as operational_reliability_summary,
    traceability_rows,
)

research_bp = Blueprint("research", __name__)

RESEARCH_ROLES = ("school_admin", "super_admin", "teacher")
NO_DATA = "No data yet."
ELIGIBLE_PARTICIPANT_SQL = """
    rp.active_status='Active'
    AND rp.consent_status='Granted'
    AND rp.assent_status IN ('Granted', 'Not Applicable')
    AND rp.parent_consent_status IN ('Granted', 'Not Applicable')
"""


def one(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row and row[0] is not None else 0


def row_dict(row):
    return {key: row[key] for key in row.keys()} if row else {}


def parse_db_datetime(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).replace("T", " ").split("+")[0]
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def fmt_datetime(value):
    parsed = parse_db_datetime(value)
    return parsed.strftime("%Y-%m-%d %H:%M") if parsed else (value or "")


def fmt_duration(seconds):
    if seconds is None or seconds == "":
        return "Not recorded"
    try:
        total = max(0, int(seconds))
    except (TypeError, ValueError):
        return "Not recorded"
    minutes, remaining_seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {remaining_seconds}s"
    if minutes:
        return f"{minutes}m {remaining_seconds}s"
    return f"{remaining_seconds}s"


def average_hours_between(rows, start_key, end_key):
    hours = []
    for row in rows:
        start = parse_db_datetime(row[start_key])
        end = parse_db_datetime(row[end_key])
        if start and end and end >= start:
            hours.append((end - start).total_seconds() / 3600)
    return round(sum(hours) / len(hours), 1) if hours else 0


def safe_round(value, digits=1):
    if value is None:
        return 0
    try:
        return round(float(value), digits)
    except (TypeError, ValueError):
        return 0


def population_variance(values):
    values = [float(v) for v in values if v is not None]
    if not values:
        return 0
    mean = sum(values) / len(values)
    return round(sum((value - mean) ** 2 for value in values) / len(values), 2)


def population_stddev(values):
    return round(math.sqrt(population_variance(values)), 2)


def percentage(numerator, denominator):
    return round((numerator / denominator) * 100, 1) if denominator else 0


def audit_research_event(conn, action, entity_type, entity_id, details):
    actor_id = session.get("user_id")
    if not actor_id:
        return
    conn.execute("""
        INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, details)
        VALUES (?, ?, ?, ?, ?)
    """, (actor_id, action, entity_type, str(entity_id), details))


def csv_response(filename, columns, rows, export_name=None):
    conn = get_db()
    if export_name:
        audit_research_event(conn, "EXPORT_GENERATED", "research_export", export_name, f"Generated {export_name} export")
        conn.commit()
    conn.close()

    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    export_timestamp = datetime.now(timezone.utc).isoformat()
    writer.writerow([label for _, label in columns])
    for row in rows:
        values = []
        for key, _ in columns:
            value = row.get(key, "")
            # Prevent spreadsheet applications interpreting exported research text
            # as a formula. The apostrophe remains visible in the raw CSV audit.
            if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
                value = "'" + value
            values.append(value)
        writer.writerow(values)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={
            "Content-Disposition": f"attachment; filename={filename}",
            "X-Export-Timestamp": export_timestamp,
            "X-Dataset-Version": "research-readiness-v1",
        },
    )


def research_filter_values():
    filters = {
        "study_phase": (request.args.get("study_phase") or "").strip(),
        "date_from": (request.args.get("date_from") or "").strip(),
        "date_to": (request.args.get("date_to") or "").strip(),
    }
    for key in ("school_id", "class_id", "subject_id", "topic_id", "outcome_id"):
        raw = request.args.get(key)
        filters[key] = int(raw) if raw and raw.isdigit() else ""
    return filters


def research_filter_options(conn):
    return {
        "study_phases": ("Pilot", "Baseline", "Intervention", "Follow-up", "Actual"),
        "schools": conn.execute("SELECT school_id, school_name FROM schools ORDER BY school_name").fetchall(),
        "classes": conn.execute("SELECT class_id, class_name FROM classes ORDER BY class_name").fetchall(),
        "subjects": conn.execute("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name").fetchall(),
        "topics": conn.execute("SELECT topic_id, topic_title FROM topics ORDER BY topic_title").fetchall(),
        "outcomes": conn.execute("SELECT outcome_id, outcome_code, outcome_name FROM learning_outcomes ORDER BY outcome_code").fetchall(),
    }


def _filter_clause(filters, mapping):
    clauses = []
    params = []
    for key, column in mapping.items():
        value = (filters or {}).get(key)
        if value not in (None, ""):
            clauses.append(f"{column} = ?")
            params.append(value)
    return clauses, params


def participant_rows(conn, filters=None):
    clauses, params = _filter_clause(filters, {
        "study_phase": "rp.study_phase",
        "school_id": "rp.school_id",
        "class_id": "rp.class_id",
        "subject_id": "rp.subject_id",
    })
    if (filters or {}).get("active_status"):
        clauses.append("rp.active_status = ?")
        params.append(filters["active_status"])
    if (filters or {}).get("consent_status"):
        clauses.append("rp.consent_status = ?")
        params.append(filters["consent_status"])
    if (filters or {}).get("role"):
        clauses.append("roles.role_name = ?")
        params.append(filters["role"])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return [row_dict(row) for row in conn.execute(f"""
        SELECT rp.id, rp.participant_code, rp.user_id, roles.role_name,
               rp.study_phase, rp.consent_status, rp.assent_status,
               rp.parent_consent_status, rp.active_status, rp.enrolled_at,
               rp.withdrawn_at, rp.created_at, rp.updated_at,
               schools.school_name, classes.class_name, subjects.subject_name
        FROM research_participants rp
        LEFT JOIN users ON users.user_id=rp.user_id
        LEFT JOIN roles ON roles.role_id=users.role_id
        LEFT JOIN schools ON schools.school_id=rp.school_id
        LEFT JOIN classes ON classes.class_id=rp.class_id
        LEFT JOIN subjects ON subjects.subject_id=rp.subject_id
        {where}
        ORDER BY rp.participant_code
    """, params).fetchall()]


def participant_summary(conn, filters=None):
    rows = participant_rows(conn, filters=filters)
    eligible = [
        row for row in rows
        if row.get("active_status") == "Active"
        and row.get("consent_status") == "Granted"
        and row.get("assent_status") in {"Granted", "Not Applicable"}
        and row.get("parent_consent_status") in {"Granted", "Not Applicable"}
    ]
    return {
        "total_participants": len(rows),
        "active_participants": sum(1 for row in rows if row.get("active_status") == "Active"),
        "learners": sum(1 for row in rows if row.get("role_name") == "learner"),
        "teachers": sum(1 for row in rows if row.get("role_name") == "teacher"),
        "eligible_participants": len(eligible),
        "eligible_learners": sum(1 for row in eligible if row.get("role_name") == "learner"),
        "eligible_teachers": sum(1 for row in eligible if row.get("role_name") == "teacher"),
    }


def next_participant_code(conn, role_name):
    prefix = {
        "learner": "L",
        "teacher": "T",
        "school_admin": "A",
        "super_admin": "S",
    }.get(role_name or "", "P")
    rows = conn.execute(
        "SELECT participant_code FROM research_participants WHERE participant_code LIKE ?",
        (f"{prefix}%",),
    ).fetchall()
    numbers = []
    for row in rows:
        suffix = str(row["participant_code"])[1:]
        if suffix.isdigit():
            numbers.append(int(suffix))
    return f"{prefix}{(max(numbers) + 1 if numbers else 1):03d}"


def participant_form_options(conn):
    return {
        "users": conn.execute("""
            SELECT users.user_id, users.full_name, users.username, roles.role_name, schools.school_id
            FROM users
            JOIN roles ON roles.role_id=users.role_id
            LEFT JOIN schools ON schools.school_id=users.school_id
            WHERE roles.role_name IN ('learner','teacher','school_admin','super_admin')
            ORDER BY roles.role_name, users.full_name
        """).fetchall(),
        "schools": conn.execute("SELECT school_id, school_name FROM schools ORDER BY school_name").fetchall(),
        "classes": conn.execute("SELECT class_id, class_name, school_id FROM classes ORDER BY class_name").fetchall(),
        "subjects": conn.execute("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name").fetchall(),
        "study_phases": ("Pilot", "Baseline", "Intervention", "Follow-up"),
        "statuses": ("Pending", "Granted", "Declined", "Not Applicable"),
        "active_statuses": ("Active", "Inactive", "Withdrawn"),
    }


def assessment_result_rows(conn, assessment_type=None, filters=None):
    params = []
    clauses = ["assessments.assessment_type IN ('pretest','posttest')"]
    if assessment_type:
        clauses = ["assessments.assessment_type = ?"]
        params.append(assessment_type)
    filter_clauses, filter_params = _filter_clause(filters, {
        "study_phase": "rp.study_phase",
        "school_id": "rp.school_id",
        "class_id": "rp.class_id",
        "subject_id": "subjects.subject_id",
        "topic_id": "topics.topic_id",
        "outcome_id": "lo.outcome_id",
    })
    clauses.extend(filter_clauses)
    params.extend(filter_params)
    if (filters or {}).get("date_from"):
        clauses.append("COALESCE(assessment_attempts.completed_at, assessment_attempts.attempted_at) >= ?")
        params.append(filters["date_from"])
    if (filters or {}).get("date_to"):
        clauses.append("COALESCE(assessment_attempts.completed_at, assessment_attempts.attempted_at) < ?")
        params.append(filters["date_to"] + " 23:59:59")
    where = "WHERE " + " AND ".join(clauses)

    rows = conn.execute(f"""
        SELECT rp.participant_code, rp.study_phase,
               users.user_id AS learner_id,
               subjects.subject_id, topics.topic_id, lo.outcome_id,
               subjects.subject_name AS subject,
               topics.topic_title AS topic,
               lo.outcome_name AS learning_outcome,
               assessments.assessment_type,
               assessment_attempts.score AS percentage,
               assessments.total_marks,
               assessment_attempts.attempted_at AS date_taken,
               assessment_attempts.started_at,
               assessment_attempts.completed_at,
               assessment_attempts.time_spent_seconds,
               assessment_attempts.weak_concepts AS concepts_weak,
               recommendations.recommendation_reason AS ai_diagnosis,
               (
                    SELECT COUNT(*)
                    FROM attempt_answers ans
                    WHERE ans.attempt_id=assessment_attempts.attempt_id AND ans.is_correct=1
               ) AS concepts_correct,
               (
                    SELECT COUNT(*)
                    FROM attempt_answers ans
                    WHERE ans.attempt_id=assessment_attempts.attempt_id
               ) AS answered_items
        FROM assessment_attempts
        JOIN users ON users.user_id=assessment_attempts.learner_id
        JOIN research_participants rp ON rp.user_id=users.user_id
             AND {ELIGIBLE_PARTICIPANT_SQL}
        JOIN assessments ON assessments.assessment_id=assessment_attempts.assessment_id
        JOIN lessons ON lessons.lesson_id=assessments.lesson_id
        JOIN learning_outcomes lo ON lo.outcome_id=lessons.outcome_id
        JOIN competencies ON competencies.competency_id=lo.competency_id
        JOIN subjects ON subjects.subject_id=competencies.subject_id
        LEFT JOIN topics ON topics.topic_id=lo.topic_id
        LEFT JOIN recommendations ON recommendations.recommendation_id = (
            SELECT MAX(r2.recommendation_id)
            FROM recommendations r2
            WHERE r2.learner_id=assessment_attempts.learner_id
              AND r2.outcome_id=lo.outcome_id
        )
        {where}
        ORDER BY assessment_attempts.attempted_at DESC, participant_code
    """, params).fetchall()

    results = []
    for row in rows:
        answered_items = row["answered_items"] or 0
        total_marks = row["total_marks"] or answered_items
        results.append({
            "participant_code": row["participant_code"],
            "study_phase": row["study_phase"],
            "learner_id": row["learner_id"],
            "subject": row["subject"],
            "topic": row["topic"] or "",
            "learning_outcome": row["learning_outcome"],
            "assessment_type": "pre_test" if row["assessment_type"] == "pretest" else "post_test",
            "score": row["concepts_correct"] or 0,
            "total_marks": total_marks,
            "percentage": safe_round(row["percentage"]),
            "date_taken": fmt_datetime(row["completed_at"] or row["date_taken"]),
            "start_time": fmt_datetime(row["started_at"]) or "Not recorded",
            "end_time": fmt_datetime(row["completed_at"] or row["date_taken"]),
            "time_spent": fmt_duration(row["time_spent_seconds"]),
            "time_spent_seconds": row["time_spent_seconds"] if row["time_spent_seconds"] is not None else "",
            "concepts_correct": row["concepts_correct"] or 0,
            "concepts_weak": row["concepts_weak"] or "",
            "ai_diagnosis": row["ai_diagnosis"] or "",
        })
    return results


def learning_gain_rows(conn, filters=None):
    return paired_learning_gain_rows(conn, filters=filters)


def learning_gain_stats(rows):
    return centralized_learning_gain_summary(rows)


def time_to_mastery_hours(conn):
    rows = conn.execute("""
        SELECT mr.updated_at AS mastered_at, first_attempt.first_attempt_at
        FROM mastery_records mr
        JOIN (
            SELECT aa.learner_id, l.outcome_id, MIN(aa.attempted_at) AS first_attempt_at
            FROM assessment_attempts aa
            JOIN assessments a ON a.assessment_id=aa.assessment_id
            JOIN lessons l ON l.lesson_id=a.lesson_id
            GROUP BY aa.learner_id, l.outcome_id
        ) first_attempt
          ON first_attempt.learner_id=mr.learner_id
         AND first_attempt.outcome_id=mr.outcome_id
        WHERE mr.mastery_status='Mastered'
    """).fetchall()
    return average_hours_between(rows, "first_attempt_at", "mastered_at")


def feedback_response_hours(conn):
    rows = conn.execute("""
        SELECT created_at, reviewed_at
        FROM practical_evidence
        WHERE reviewed_at IS NOT NULL
    """).fetchall()
    return average_hours_between(rows, "created_at", "reviewed_at")


def mastery_rows(conn, filters=None):
    clauses, params = _filter_clause(filters, {
        "study_phase": "rp.study_phase",
        "school_id": "rp.school_id",
        "class_id": "rp.class_id",
        "subject_id": "subjects.subject_id",
        "topic_id": "topics.topic_id",
        "outcome_id": "lo.outcome_id",
    })
    if (filters or {}).get("date_from"):
        clauses.append("mastery_records.updated_at >= ?")
        params.append(filters["date_from"])
    if (filters or {}).get("date_to"):
        clauses.append("mastery_records.updated_at < ?")
        params.append(filters["date_to"] + " 23:59:59")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(f"""
        SELECT rp.participant_code,
               subjects.subject_name AS subject,
               topics.topic_title AS topic,
               lo.outcome_name AS learning_outcome,
               mastery_records.mastery_status,
               mastery_records.mastery_score,
               mastery_records.mastery_level,
               mastery_records.updated_at,
               first_attempt.first_attempt_at,
               (
                    SELECT COUNT(*)
                    FROM assessment_attempts aa
                    JOIN assessments a ON a.assessment_id=aa.assessment_id
                    JOIN lessons l ON l.lesson_id=a.lesson_id
                    WHERE aa.learner_id=mastery_records.learner_id
                      AND l.outcome_id=mastery_records.outcome_id
               ) AS attempts
        FROM mastery_records
        JOIN users ON users.user_id=mastery_records.learner_id
        JOIN research_participants rp ON rp.user_id=users.user_id
             AND {ELIGIBLE_PARTICIPANT_SQL}
        JOIN learning_outcomes lo ON lo.outcome_id=mastery_records.outcome_id
        JOIN competencies ON competencies.competency_id=lo.competency_id
        JOIN subjects ON subjects.subject_id=competencies.subject_id
        LEFT JOIN topics ON topics.topic_id=lo.topic_id
        LEFT JOIN (
            SELECT aa.learner_id, l.outcome_id, MIN(aa.attempted_at) AS first_attempt_at
            FROM assessment_attempts aa
            JOIN assessments a ON a.assessment_id=aa.assessment_id
            JOIN lessons l ON l.lesson_id=a.lesson_id
            GROUP BY aa.learner_id, l.outcome_id
        ) first_attempt
          ON first_attempt.learner_id=mastery_records.learner_id
         AND first_attempt.outcome_id=mastery_records.outcome_id
        {where}
        ORDER BY participant_code, subjects.subject_name, lo.sequence_order
    """, params).fetchall()

    results = []
    for row in rows:
        time_hours = ""
        if row["mastery_status"] == "Mastered":
            start = parse_db_datetime(row["first_attempt_at"])
            end = parse_db_datetime(row["updated_at"])
            if start and end and end >= start:
                time_hours = round((end - start).total_seconds() / 3600, 1)
        results.append({
            "participant_code": row["participant_code"],
            "subject": row["subject"],
            "topic": row["topic"] or "",
            "learning_outcome": row["learning_outcome"],
            "mastery_status": row["mastery_status"],
            "mastery_level": row["mastery_level"],
            "mastery_score": safe_round(row["mastery_score"]),
            "attempts": row["attempts"] or 0,
            "time_to_mastery": time_hours if time_hours != "" else "Not yet mastered",
            "updated_at": fmt_datetime(row["updated_at"]),
        })
    return results


def mastery_summary(rows, total_learners=0):
    total = len(rows)
    mastered = sum(1 for row in rows if row["mastery_status"] == "Mastered")
    not_mastered = sum(1 for row in rows if row["mastery_status"] in {"Not Started", "Practice Required"})
    in_progress = sum(1 for row in rows if row["mastery_status"] in {"In Progress", "Ready for Post-test", "Awaiting Teacher Review"})
    remediation = sum(1 for row in rows if row["mastery_status"] == "Remediation Required")
    mastered_attempts = [row["attempts"] for row in rows if row["mastery_status"] == "Mastered"]
    mastered_times = [row["time_to_mastery"] for row in rows if isinstance(row["time_to_mastery"], (int, float))]
    return {
        "total_learners": total_learners,
        "mastered": mastered,
        "not_mastered": not_mastered,
        "in_progress": in_progress,
        "remediation_required": remediation,
        "mastery_attainment_rate": percentage(mastered, total),
        "average_attempts_to_mastery": safe_round(sum(mastered_attempts) / len(mastered_attempts) if mastered_attempts else 0),
        "average_time_to_mastery": safe_round(sum(mastered_times) / len(mastered_times) if mastered_times else 0),
    }


def teacher_oversight_data(conn):
    reviews = [row_dict(row) for row in conn.execute(f"""
        SELECT 'Mastery Review' AS record_type,
               rp.participant_code,
               lo.outcome_name AS learning_outcome,
               tr.decision AS action,
               tr.teacher_comment AS comment,
               tr.reason AS details,
               tr.created_at
        FROM teacher_mastery_reviews tr
        JOIN users learner ON learner.user_id=tr.learner_id
        JOIN research_participants rp ON rp.user_id=learner.user_id
             AND {ELIGIBLE_PARTICIPANT_SQL}
        JOIN learning_outcomes lo ON lo.outcome_id=tr.outcome_id
        ORDER BY tr.created_at DESC
    """).fetchall()]
    feedback = [row_dict(row) for row in conn.execute(f"""
        SELECT 'Teacher Feedback' AS record_type,
               rp.participant_code,
               lo.outcome_name AS learning_outcome,
               tf.mastery_approval AS action,
               tf.feedback_text AS comment,
               tf.remediation_assigned AS details,
               tf.created_at
        FROM teacher_feedback tf
        JOIN users learner ON learner.user_id=tf.learner_id
        JOIN research_participants rp ON rp.user_id=learner.user_id
             AND {ELIGIBLE_PARTICIPANT_SQL}
        JOIN learning_outcomes lo ON lo.outcome_id=tf.outcome_id
        ORDER BY tf.created_at DESC
    """).fetchall()]
    interventions = [row_dict(row) for row in conn.execute(f"""
        SELECT 'Teacher Intervention' AS record_type,
               rp.participant_code,
               lo.outcome_name AS learning_outcome,
               ti.intervention_type AS action,
               ti.intervention_note AS comment,
               ti.status AS details,
               ti.created_at
        FROM teacher_interventions ti
        JOIN users learner ON learner.user_id=ti.learner_id
        JOIN research_participants rp ON rp.user_id=learner.user_id
             AND {ELIGIBLE_PARTICIPANT_SQL}
        JOIN learning_outcomes lo ON lo.outcome_id=ti.outcome_id
        ORDER BY ti.created_at DESC
    """).fetchall()]
    practical = [row_dict(row) for row in conn.execute(f"""
        SELECT 'Practical Evidence Review' AS record_type,
               rp.participant_code,
               lo.outcome_name AS learning_outcome,
               pe.teacher_status AS action,
               pe.teacher_comment AS comment,
               pe.rubric_level AS details,
               COALESCE(pe.reviewed_at, pe.created_at) AS created_at
        FROM practical_evidence pe
        JOIN users learner ON learner.user_id=pe.learner_id
        JOIN research_participants rp ON rp.user_id=learner.user_id
             AND {ELIGIBLE_PARTICIPANT_SQL}
        JOIN learning_outcomes lo ON lo.outcome_id=pe.outcome_id
        WHERE pe.reviewed_at IS NOT NULL OR pe.teacher_status != 'Pending Review'
        ORDER BY COALESCE(pe.reviewed_at, pe.created_at) DESC
    """).fetchall()]
    details = reviews + feedback + interventions + practical
    details.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)

    review_count = len(reviews)
    approvals = sum(1 for row in reviews if row.get("action") == "Teacher Approved")
    overrides = sum(1 for row in reviews if row.get("action") == "Teacher Override")
    reopened = sum(1 for row in reviews if row.get("action") == "Reopened")
    learners_supported = len({row.get("participant_code") for row in details if row.get("participant_code")})
    summary = {
        "number_of_interventions": len(interventions),
        "approval_rate": percentage(approvals, review_count),
        "override_rate": percentage(overrides, review_count),
        "teacher_approvals": approvals,
        "teacher_overrides": overrides,
        "learners_reopened_for_practice": reopened,
        "practical_evidence_reviewed": len(practical),
        "average_feedback_response_time": feedback_response_hours(conn),
        "learners_supported_by_teacher": learners_supported,
    }
    for row in details:
        row["created_at"] = fmt_datetime(row.get("created_at"))
    return summary, details


def questionnaire_rows(conn):
    return [row_dict(row) for row in conn.execute("""
        SELECT q.id, q.questionnaire_title, q.respondent_role, q.active_status,
               q.questionnaire_description, q.study_phase, q.created_at,
               COUNT(DISTINCT qi.id) AS item_count,
               COUNT(DISTINCT qr.id) AS response_count
        FROM research_questionnaires q
        LEFT JOIN research_questionnaire_items qi ON qi.questionnaire_id=q.id
        LEFT JOIN research_questionnaire_responses qr ON qr.questionnaire_id=q.id
        GROUP BY q.id, q.questionnaire_title, q.respondent_role, q.active_status,
                 q.questionnaire_description, q.study_phase, q.created_at
        ORDER BY q.respondent_role, q.questionnaire_title
    """).fetchall()]


def questionnaire_result_rows(conn):
    raw_rows = conn.execute(f"""
        SELECT q.questionnaire_title, q.respondent_role, qi.construct_name,
               a.score, r.id AS response_id
        FROM research_questionnaire_answers a
        JOIN research_questionnaire_responses r ON r.id=a.response_id
        JOIN research_participants rp ON (rp.id=r.participant_id OR (r.participant_id IS NULL AND rp.user_id=r.respondent_user_id))
             AND {ELIGIBLE_PARTICIPANT_SQL}
        JOIN research_questionnaire_items qi ON qi.id=a.item_id
        JOIN research_questionnaires q ON q.id=qi.questionnaire_id
        WHERE COALESCE(r.completion_status,'Submitted')='Submitted'
        ORDER BY q.respondent_role, q.questionnaire_title, qi.construct_name
    """).fetchall()
    grouped = {}
    for row in raw_rows:
        key = (row["questionnaire_title"], row["respondent_role"], row["construct_name"])
        group = grouped.setdefault(key, {"scores": [], "responses": set()})
        group["scores"].append(int(row["score"]))
        group["responses"].add(row["response_id"])
    results = []
    for key, group in grouped.items():
        scores = group["scores"]
        results.append({
            "questionnaire_title": key[0], "respondent_role": key[1], "construct_name": key[2],
            "average_score": round(sum(scores) / len(scores), 2),
            "sample_standard_deviation": round(stdev(scores), 2) if len(scores) > 1 else 0,
            "responses": len(group["responses"]), "answers": len(scores),
            **{f"score_{score}_frequency": scores.count(score) for score in range(1, 6)},
        })
    return results


def average_questionnaire_score(conn, role=None, construct=None):
    where = [" ".join(ELIGIBLE_PARTICIPANT_SQL.split())]
    params = []
    if role:
        where.append("q.respondent_role = ?")
        params.append(role)
    if construct:
        where.append("qi.construct_name = ?")
        params.append(construct)
    clause = "WHERE " + " AND ".join(where)
    return one(conn, f"""
        SELECT ROUND(CAST(AVG(a.score) AS NUMERIC), 2)
        FROM research_questionnaire_answers a
        JOIN research_questionnaire_responses r ON r.id=a.response_id
        JOIN research_participants rp ON (rp.id=r.participant_id OR (r.participant_id IS NULL AND rp.user_id=r.respondent_user_id))
        JOIN research_questionnaire_items qi ON qi.id=a.item_id
        JOIN research_questionnaires q ON q.id=qi.questionnaire_id
        {clause}
    """, params)


def system_log_rows(conn, limit=120):
    audit_rows = [row_dict(row) for row in conn.execute(f"""
        SELECT 'Audit Log' AS source, audit_logs.action, audit_logs.entity_type,
               audit_logs.entity_id, audit_logs.details, audit_logs.created_at,
               COALESCE(rp.participant_code, 'System/Unlinked') AS participant_code
        FROM audit_logs
        LEFT JOIN users ON users.user_id=audit_logs.actor_id
        LEFT JOIN research_participants rp ON rp.user_id=users.user_id
             AND {ELIGIBLE_PARTICIPANT_SQL}
        ORDER BY audit_logs.created_at DESC
        LIMIT 120
    """).fetchall()]
    activity_rows = [row_dict(row) for row in conn.execute(f"""
        SELECT 'Activity Log' AS source, activity_logs.activity_type AS action,
               'learner_activity' AS entity_type,
               activity_logs.log_id AS entity_id,
               activity_logs.activity_description AS details,
               activity_logs.created_at,
               COALESCE(rp.participant_code, 'System/Unlinked') AS participant_code
        FROM activity_logs
        LEFT JOIN users ON users.user_id=activity_logs.learner_id
        LEFT JOIN research_participants rp ON rp.user_id=users.user_id
             AND {ELIGIBLE_PARTICIPANT_SQL}
        ORDER BY activity_logs.created_at DESC
        LIMIT 120
    """).fetchall()]
    event_rows = [row_dict(row) for row in conn.execute("""
        SELECT 'Research Event' AS source, event_type AS action,
               entity_type, entity_id,
               CASE WHEN event_status='failure'
                    THEN COALESCE(error_category,'failure')
                    ELSE event_status END AS details,
               occurred_at AS created_at,
               'System/Anonymized' AS participant_code
        FROM research_events
        ORDER BY occurred_at DESC
        LIMIT 120
    """).fetchall()]
    rows = audit_rows + activity_rows + event_rows
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    for row in rows[:limit]:
        row["created_at"] = fmt_datetime(row.get("created_at"))
    return rows[:limit]


def reliability_summary(conn):
    synced_items = one(conn, "SELECT COALESCE(SUM(synced_count), 0) FROM sync_events")
    event_failures = one(conn, "SELECT COALESCE(SUM(failed_count), 0) FROM sync_events")
    queue_failures = one(conn, """
        SELECT
            (SELECT COUNT(*) FROM offline_sync_queue
             WHERE LOWER(COALESCE(sync_status,'')) IN ('failed','error') OR last_error IS NOT NULL) +
            (SELECT COUNT(*) FROM sync_queue
             WHERE LOWER(COALESCE(sync_status,'')) IN ('failed','error') OR error_message IS NOT NULL)
    """)
    observed_results = synced_items + event_failures
    return {
        "sync_events": one(conn, "SELECT COUNT(*) FROM sync_events"),
        "synced_items": synced_items,
        "failed_items": event_failures,
        "recorded_system_incidents": event_failures + queue_failures,
        "sync_success_rate": percentage(synced_items, observed_results) if observed_results else NO_DATA,
        "pending_sync_items": one(conn, """
            SELECT
                (SELECT COUNT(*) FROM offline_sync_queue WHERE sync_status='Pending') +
                (SELECT COUNT(*) FROM sync_queue WHERE sync_status='Pending')
        """),
    }


def research_metrics(conn):
    participants = participant_summary(conn)
    mastery = mastery_rows(conn)
    total_learners = participants["eligible_learners"]
    mastery_totals = mastery_summary(mastery, total_learners)
    gains = learning_gain_rows(conn)
    gain_stats = learning_gain_stats(gains)
    oversight_summary, _ = teacher_oversight_data(conn)
    logs = system_log_rows(conn, limit=1)
    reliability = reliability_summary(conn)
    feedback = feedback_responsiveness_summary(feedback_responsiveness_rows(conn))
    operational = operational_reliability_summary(operational_reliability_rows(conn))
    questionnaire_response_count = one(conn, f"""
        SELECT COUNT(DISTINCT r.id)
        FROM research_questionnaire_responses r
        JOIN research_participants rp ON (rp.id=r.participant_id OR (r.participant_id IS NULL AND rp.user_id=r.respondent_user_id))
             AND {ELIGIBLE_PARTICIPANT_SQL}
    """)
    metrics = {
        "total_participants": participants["total_participants"],
        "eligible_participants": participants["eligible_participants"],
        "learners": participants["eligible_learners"],
        "teachers": participants["eligible_teachers"],
        "attempts": one(conn, f"""
            SELECT COUNT(*)
            FROM assessment_attempts aa
            JOIN research_participants rp ON rp.user_id=aa.learner_id
                 AND {ELIGIBLE_PARTICIPANT_SQL}
        """),
        "average_pre_test": gain_stats["average_pre_test"],
        "average_post_test": gain_stats["average_post_test"],
        "average_learning_gain": gain_stats["average_gain"],
        "mastery_attainment_rate": mastery_totals["mastery_attainment_rate"],
        "average_time_to_mastery": mastery_totals["average_time_to_mastery"],
        "teacher_intervention_count": oversight_summary["number_of_interventions"],
        "questionnaire_response_count": questionnaire_response_count,
        "average_learner_satisfaction": average_questionnaire_score(conn, role="learner", construct="satisfaction"),
        "average_teacher_satisfaction": average_questionnaire_score(conn, role="teacher"),
        "system_usage_count": one(conn, f"""
            SELECT
                (SELECT COUNT(*) FROM activity_logs al
                 JOIN research_participants rp ON rp.user_id=al.learner_id AND {ELIGIBLE_PARTICIPANT_SQL}) +
                (SELECT COUNT(*) FROM assessment_attempts aa
                 JOIN research_participants rp ON rp.user_id=aa.learner_id AND {ELIGIBLE_PARTICIPANT_SQL}) +
                (SELECT COUNT(*) FROM recommendations rec
                 JOIN research_participants rp ON rp.user_id=rec.learner_id AND {ELIGIBLE_PARTICIPANT_SQL}) +
                (SELECT COUNT(*) FROM practical_evidence pe
                 JOIN research_participants rp ON rp.user_id=pe.learner_id AND {ELIGIBLE_PARTICIPANT_SQL}) +
                (SELECT COUNT(*) FROM activity_submissions sub
                 JOIN research_participants rp ON rp.user_id=sub.learner_id AND {ELIGIBLE_PARTICIPANT_SQL}) +
                (SELECT COUNT(*) FROM audit_logs audit
                 JOIN research_participants rp ON rp.user_id=audit.actor_id AND {ELIGIBLE_PARTICIPANT_SQL})
        """),
        "latest_data_collection_activity": f"{logs[0]['action']} - {logs[0]['created_at']}" if logs else NO_DATA,
        "ai_recommendations": one(conn, f"""
            SELECT COUNT(*) FROM recommendations rec
            JOIN research_participants rp ON rp.user_id=rec.learner_id
                 AND {ELIGIBLE_PARTICIPANT_SQL}
        """),
        "avg_ai_confidence": one(conn, f"""
            SELECT ROUND(CAST(AVG(ax.confidence_score) AS NUMERIC),1) FROM ai_explanations ax
            JOIN research_participants rp ON rp.user_id=ax.learner_id
                 AND {ELIGIBLE_PARTICIPANT_SQL}
        """),
        "offline_pending": one(conn, "SELECT COUNT(*) FROM offline_sync_queue WHERE sync_status='Pending'"),
        "cached_resources": one(conn, "SELECT COUNT(*) FROM cached_resources WHERE cache_status='Cached'"),
        "sync_success_rate": reliability["sync_success_rate"],
        "recorded_system_incidents": reliability["recorded_system_incidents"],
        "reliability_evidence_count": reliability["sync_events"],
        "recommendation_follow_through_rate": feedback["follow_through_rate"],
        "unresolved_recommendations": feedback["unresolved_recommendations"],
        "recorded_event_success_rate": operational["recorded_success_rate"],
        "median_response_time_ms": operational["median_response_time_ms"],
    }
    metrics["avg_pretest"] = metrics["average_pre_test"]
    metrics["avg_posttest"] = metrics["average_post_test"]
    metrics["learning_gain"] = metrics["average_learning_gain"]
    metrics["mastery_rate"] = metrics["mastery_attainment_rate"]
    metrics["time_to_mastery_hours"] = metrics["average_time_to_mastery"]
    metrics["teacher_interventions"] = metrics["teacher_intervention_count"]
    return metrics


def chapter_evidence_readiness(conn):
    """Report whether each proposal-defined evidence stream has begun.

    This is deliberately a presence check, not a claim that the sample is
    complete or that the dissertation findings have been validated.
    """
    participants = participant_summary(conn)
    gains = learning_gain_rows(conn)
    mastery = mastery_rows(conn)
    oversight, _ = teacher_oversight_data(conn)
    questionnaire_responses = one(conn, f"""
        SELECT COUNT(DISTINCT r.id)
        FROM research_questionnaire_responses r
        JOIN research_participants rp
          ON (rp.id=r.participant_id OR (r.participant_id IS NULL AND rp.user_id=r.respondent_user_id))
         AND {ELIGIBLE_PARTICIPANT_SQL}
    """)
    logs = system_log_rows(conn, limit=1)
    items = [
        {
            "label": "Eligible participants",
            "present": participants["eligible_participants"] > 0,
            "evidence": f"{participants['eligible_participants']} consented and active participant(s)",
            "route": "research.participants",
        },
        {
            "label": "Paired pre/post evidence",
            "present": bool(gains),
            "evidence": f"{len(gains)} paired learning-outcome result(s)",
            "route": "research.pre_post_results",
        },
        {
            "label": "Mastery evidence",
            "present": bool(mastery),
            "evidence": f"{len(mastery)} mastery record(s)",
            "route": "research.mastery_attainment",
        },
        {
            "label": "Teacher oversight evidence",
            "present": oversight["number_of_interventions"] > 0,
            "evidence": f"{oversight['number_of_interventions']} intervention(s)",
            "route": "research.teacher_oversight",
        },
        {
            "label": "User acceptance evidence",
            "present": questionnaire_responses > 0,
            "evidence": f"{questionnaire_responses} eligible questionnaire response(s)",
            "route": "research.questionnaire_results",
        },
        {
            "label": "System-use evidence",
            "present": bool(logs),
            "evidence": "At least one eligible research event" if logs else NO_DATA,
            "route": "research.system_logs",
        },
    ]
    return {
        "items": items,
        "present_count": sum(1 for item in items if item["present"]),
        "total_count": len(items),
    }


def weak_concept_rows(conn, limit=8):
    return [row_dict(row) for row in conn.execute(f"""
        SELECT concept_tag, ROUND(CAST(AVG(latest_score) AS NUMERIC),1) AS avg_score, COUNT(*) AS evidence
        FROM concept_mastery
        GROUP BY concept_tag
        ORDER BY avg_score ASC
        LIMIT {int(limit)}
    """).fetchall()]


def full_dataset_rows(conn):
    gains = learning_gain_rows(conn)
    mastery_times = {
        (row["participant_code"], row["subject"], row["topic"], row["learning_outcome"]): row["time_to_mastery"]
        for row in mastery_rows(conn)
    }
    questionnaire_scores = {}
    for row in conn.execute(f"""
        SELECT rp.participant_code,
               ROUND(CAST(AVG(a.score) AS NUMERIC),2) AS questionnaire_score
        FROM research_questionnaire_answers a
        JOIN research_questionnaire_responses r ON r.id=a.response_id
        LEFT JOIN users ON users.user_id=r.respondent_user_id
        JOIN research_participants rp ON (rp.id=r.participant_id OR (r.participant_id IS NULL AND rp.user_id=users.user_id))
             AND {ELIGIBLE_PARTICIPANT_SQL}
        GROUP BY rp.participant_code
    """).fetchall():
        questionnaire_scores[row["participant_code"]] = row["questionnaire_score"]
    for row in gains:
        row["questionnaire_score"] = questionnaire_scores.get(row["participant_code"], "")
        row["time_to_mastery"] = mastery_times.get(
            (row["participant_code"], row["subject"], row["topic"], row["learning_outcome"]),
            "Not yet mastered",
        )
    return gains


def render_table(
    title,
    subtitle,
    columns,
    rows,
    summary=None,
    actions=None,
    chart=None,
    filters=None,
    filter_options=None,
    empty_message=None,
):
    return render_template(
        "research/table.html",
        title=title,
        subtitle=subtitle,
        columns=columns,
        rows=rows,
        summary=summary or {},
        actions=actions or [],
        chart=chart,
        no_data=NO_DATA,
        filters=filters or {},
        filter_options=filter_options,
        empty_message=empty_message or NO_DATA,
    )


@research_bp.route("/research-dashboard")
@research_bp.route("/research/dashboard")
@role_required(*RESEARCH_ROLES)
def research_dashboard():
    conn = get_db()
    metrics = research_metrics(conn)
    weak_concepts = weak_concept_rows(conn)
    chart_data = {
        "pre_post": [
            {"label": "Average Pre-test", "value": metrics["average_pre_test"]},
            {"label": "Average Post-test", "value": metrics["average_post_test"]},
        ],
        "mastery": [
            {"label": "Mastery Attainment", "value": metrics["mastery_attainment_rate"]},
            {"label": "Not Mastered/In Progress", "value": max(0, 100 - metrics["mastery_attainment_rate"])},
        ],
        "learning_gain": [{"label": "Average Gain", "value": metrics["average_learning_gain"]}],
        "teacher": [{"label": "Interventions", "value": metrics["teacher_intervention_count"]}],
    }
    conn.close()
    return render_template("research/dashboard.html", metrics=metrics, weak_concepts=weak_concepts, chart_data=chart_data)


@research_bp.route("/research/chapter-guide")
@role_required(*RESEARCH_ROLES)
def chapter_guide():
    conn = get_db()
    readiness = chapter_evidence_readiness(conn)
    conn.close()
    return render_template(
        "research/chapter_guide.html",
        readiness=readiness,
        no_data=NO_DATA,
    )


@research_bp.route("/research/participants")
@role_required(*RESEARCH_ROLES)
def participants():
    conn = get_db()
    filters = research_filter_values()
    filters.update({
        "role": (request.args.get("role") or "").strip(),
        "consent_status": (request.args.get("consent_status") or "").strip(),
        "active_status": (request.args.get("active_status") or "").strip(),
    })
    rows = participant_rows(conn, filters)
    for row in rows:
        row["_view_url"] = url_for("research.view_participant", participant_id=row["id"])
    summary = participant_summary(conn, filters)
    options = research_filter_options(conn)
    conn.close()
    return render_table(
        "Research Participants",
        "Participant codes protect unnecessary personal data while connecting dissertation evidence to users, schools, classes and subjects.",
        [
            ("participant_code", "Participant Code"),
            ("role_name", "Role"),
            ("school_name", "School"),
            ("class_name", "Class"),
            ("subject_name", "Subject"),
            ("study_phase", "Study Phase"),
            ("consent_status", "Consent"),
            ("assent_status", "Assent"),
            ("parent_consent_status", "Parent Consent"),
            ("active_status", "Status"),
            ("_view_url", "Record"),
        ],
        rows,
        summary,
        [{"label": "Create Participant", "url": url_for("research.create_participant")}],
        filters=filters,
        filter_options=options,
    )


@research_bp.route("/research/participants/create", methods=["GET", "POST"])
@role_required(*RESEARCH_ROLES)
@csrf_protect
def create_participant():
    conn = get_db()
    options = participant_form_options(conn)
    if request.method == "POST":
        user_id = int(request.form.get("user_id") or 0) or None
        user_role = None
        user_row = None
        if user_id:
            user_row = conn.execute("""
                SELECT users.*, roles.role_name
                FROM users
                JOIN roles ON roles.role_id=users.role_id
                WHERE users.user_id=?
            """, (user_id,)).fetchone()
            user_role = user_row["role_name"] if user_row else None
        participant_code = (request.form.get("participant_code") or "").strip() or next_participant_code(conn, user_role)
        if not re.fullmatch(r"[LTASP]\d{3,}", participant_code):
            conn.close()
            flash("Participant code must use L/T/A/S/P followed by at least three digits.", "danger")
            return redirect(url_for("research.create_participant"))
        parent_consent = request.form.get("parent_consent_status") or "Pending"
        if user_role != "learner":
            parent_consent = "Not Applicable"
        try:
            conn.execute("""
                INSERT INTO research_participants
                (participant_code, user_id, school_id, class_id, subject_id, study_phase,
                 consent_status, assent_status, parent_consent_status, active_status)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                participant_code,
                user_id,
                int(request.form.get("school_id") or 0) or (user_row["school_id"] if user_row else None),
                int(request.form.get("class_id") or 0) or None,
                int(request.form.get("subject_id") or 0) or None,
                request.form.get("study_phase") or "Pilot",
                request.form.get("consent_status") or "Pending",
                request.form.get("assent_status") or "Pending",
                parent_consent,
                request.form.get("active_status") or "Active",
            ))
            audit_research_event(conn, "CREATE_RESEARCH_PARTICIPANT", "research_participant", participant_code, "Created research participant code")
            conn.commit()
            flash("Research participant saved.", "success")
            conn.close()
            return redirect(url_for("research.participants"))
        except DatabaseIntegrityError:
            conn.rollback()
            flash("Participant code or user/study phase already exists.", "danger")
    conn.close()
    return render_template("research/participant_form.html", participant=None, **options)


@research_bp.route("/research/participants/<int:participant_id>")
@role_required(*RESEARCH_ROLES)
def view_participant(participant_id):
    conn = get_db()
    participant = conn.execute("""
        SELECT rp.*, u.full_name, roles.role_name, s.school_name, c.class_name,
               sub.subject_name
        FROM research_participants rp
        LEFT JOIN users u ON u.user_id=rp.user_id
        LEFT JOIN roles ON roles.role_id=u.role_id
        LEFT JOIN schools s ON s.school_id=rp.school_id
        LEFT JOIN classes c ON c.class_id=rp.class_id
        LEFT JOIN subjects sub ON sub.subject_id=rp.subject_id
        WHERE rp.id=?
    """, (participant_id,)).fetchone()
    if not participant:
        conn.close()
        return "Participant not found", 404
    history = conn.execute("""
        SELECT action, details, created_at FROM audit_logs
        WHERE entity_type='research_participant' AND entity_id=?
        ORDER BY created_at DESC
    """, (str(participant_id),)).fetchall()
    conn.close()
    return render_template("research/participant_view.html", participant=participant, history=history)


@research_bp.route("/research/participants/<int:participant_id>/edit", methods=["GET", "POST"])
@role_required(*RESEARCH_ROLES)
@csrf_protect
def edit_participant(participant_id):
    conn = get_db()
    participant = conn.execute("SELECT * FROM research_participants WHERE id=?", (participant_id,)).fetchone()
    if not participant:
        conn.close()
        return "Participant not found", 404
    options = participant_form_options(conn)
    if request.method == "POST":
        code = (request.form.get("participant_code") or "").strip()
        if not re.fullmatch(r"[LTASP]\d{3,}", code):
            conn.close()
            flash("Participant code must use L/T/A/S/P followed by at least three digits.", "danger")
            return redirect(url_for("research.edit_participant", participant_id=participant_id))
        user_id = int(request.form.get("user_id") or 0) or None
        role_row = conn.execute("""
            SELECT roles.role_name FROM users JOIN roles ON roles.role_id=users.role_id
            WHERE users.user_id=?
        """, (user_id,)).fetchone() if user_id else None
        parent_consent = request.form.get("parent_consent_status") or "Pending"
        if role_row and role_row["role_name"] != "learner":
            parent_consent = "Not Applicable"
        new_values = {
            "consent_status": request.form.get("consent_status") or "Pending",
            "assent_status": request.form.get("assent_status") or "Pending",
            "parent_consent_status": parent_consent,
            "active_status": request.form.get("active_status") or "Active",
        }
        changes = []
        for key, value in new_values.items():
            if participant[key] != value:
                changes.append(f"{key}: {participant[key]} -> {value}")
        try:
            conn.execute("""
                UPDATE research_participants
                SET participant_code=?, user_id=?, school_id=?, class_id=?, subject_id=?,
                    study_phase=?, consent_status=?, assent_status=?, parent_consent_status=?,
                    active_status=?, withdrawn_at=CASE WHEN ?='Withdrawn' THEN CURRENT_TIMESTAMP ELSE NULL END,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (
                code, user_id, int(request.form.get("school_id") or 0) or None,
                int(request.form.get("class_id") or 0) or None,
                int(request.form.get("subject_id") or 0) or None,
                request.form.get("study_phase") or "Pilot", new_values["consent_status"],
                new_values["assent_status"], new_values["parent_consent_status"],
                new_values["active_status"], new_values["active_status"], participant_id,
            ))
            audit_research_event(conn, "UPDATE_RESEARCH_PARTICIPANT", "research_participant", participant_id,
                                 "; ".join(changes) or "Administrative fields updated; consent unchanged")
            conn.commit()
            conn.close()
            flash("Research participant updated with an audit record.", "success")
            return redirect(url_for("research.view_participant", participant_id=participant_id))
        except DatabaseIntegrityError:
            conn.rollback()
            flash("Participant code or linked user already exists for this phase.", "danger")
    conn.close()
    return render_template("research/participant_form.html", participant=participant, **options)


@research_bp.route("/research/pre-post-results")
@role_required(*RESEARCH_ROLES)
def pre_post_results():
    conn = get_db()
    filters = research_filter_values()
    rows = assessment_result_rows(conn, filters=filters)
    options = research_filter_options(conn)
    conn.close()
    return render_table(
        "Pre-test and Post-test Results",
        "Operational assessment attempts are reused; missing start time and time spent are shown as not recorded.",
        assessment_columns(),
        rows,
        actions=[{"label": "Export Pre/Post CSV", "url": url_for("research.export_pre_post", **filters)}],
        filters=filters, filter_options=options,
        empty_message="No eligible pre-test or post-test attempts match these filters.",
    )


@research_bp.route("/research/pre-test-results")
@role_required(*RESEARCH_ROLES)
def pre_test_results():
    conn = get_db()
    filters = research_filter_values()
    rows = assessment_result_rows(conn, "pretest", filters)
    options = research_filter_options(conn)
    conn.close()
    return render_table("Pre-test Results", "Diagnostic pre-test results by participant and learning outcome.", assessment_columns(), rows, filters=filters, filter_options=options)


@research_bp.route("/research/post-test-results")
@role_required(*RESEARCH_ROLES)
def post_test_results():
    conn = get_db()
    filters = research_filter_values()
    rows = assessment_result_rows(conn, "posttest", filters)
    options = research_filter_options(conn)
    conn.close()
    return render_table("Post-test Results", "Post-test mastery evidence by participant and learning outcome.", assessment_columns(), rows, filters=filters, filter_options=options)


def assessment_columns():
    return [
        ("participant_code", "Participant"),
        ("subject", "Subject"),
        ("topic", "Topic"),
        ("learning_outcome", "Learning Outcome"),
        ("assessment_type", "Type"),
        ("score", "Score"),
        ("total_marks", "Total"),
        ("percentage", "Percentage"),
        ("date_taken", "Date Taken"),
        ("start_time", "Start Time"),
        ("end_time", "End Time"),
        ("time_spent", "Time Spent"),
        ("concepts_correct", "Concepts Correct"),
        ("concepts_weak", "Weak Concepts"),
        ("ai_diagnosis", "AI Diagnosis"),
    ]


@research_bp.route("/research/learning-gain")
@role_required(*RESEARCH_ROLES)
def learning_gain():
    conn = get_db()
    filters = research_filter_values()
    rows = learning_gain_rows(conn, filters)
    summary = learning_gain_stats(rows)
    options = research_filter_options(conn)
    conn.close()
    return render_table(
        "Learning Gain Analysis",
        "Learning gain is computed as post-test percentage minus pre-test percentage. Normalized gain is computed only where pre-test is below 100.",
        [
            ("participant_code", "Participant"),
            ("subject", "Subject"),
            ("topic", "Topic"),
            ("learning_outcome", "Learning Outcome"),
            ("pre_test", "Pre-test"),
            ("post_test", "Post-test"),
            ("learning_gain", "Gain"),
            ("normalized_gain", "Normalized Gain"),
            ("percentage_improvement", "Improvement"),
            ("mastery_status", "Mastery Status"),
        ],
        rows,
        summary,
        [{"label": "Export Learning Gain", "url": url_for("research.export_learning_gain", **filters)}],
        chart={
            "title": "Participant Pre-test vs Post-test",
            "rows": [
                {
                    "label": f"{row['participant_code']} - {row['learning_outcome']}",
                    "pre": row["pre_test"],
                    "post": row["post_test"],
                }
                for row in rows
            ],
        },
        filters=filters, filter_options=options,
        empty_message="No valid paired pre-test/post-test cases match these filters. A post-test must occur after a pre-test for the same participant, outcome and study phase.",
    )


@research_bp.route("/research/mastery-attainment")
@role_required(*RESEARCH_ROLES)
def mastery_attainment():
    conn = get_db()
    filters = research_filter_values()
    rows = mastery_rows(conn, filters)
    summary = mastery_summary(rows, participant_summary(conn, filters)["eligible_learners"])
    options = research_filter_options(conn)
    conn.close()
    return render_table(
        "Mastery Attainment Report",
        "Evidence for Objective 3: mastery status, attempts and time-to-mastery by learning outcome.",
        [
            ("participant_code", "Participant"),
            ("subject", "Subject"),
            ("topic", "Topic"),
            ("learning_outcome", "Learning Outcome"),
            ("mastery_status", "Status"),
            ("mastery_level", "Level"),
            ("mastery_score", "Score"),
            ("attempts", "Attempts"),
            ("time_to_mastery", "Time to Mastery"),
            ("updated_at", "Updated"),
        ],
        rows,
        summary,
        [{"label": "Export Mastery", "url": url_for("research.export_mastery", **filters)}],
        filters=filters, filter_options=options,
    )


@research_bp.route("/research/teacher-oversight")
@role_required(*RESEARCH_ROLES)
def teacher_oversight():
    conn = get_db()
    summary, rows = teacher_oversight_data(conn)
    conn.close()
    return render_table(
        "Teacher Oversight Report",
        "Teacher approvals, overrides, comments, remediation, practical reviews and reopen decisions.",
        [
            ("record_type", "Record Type"),
            ("participant_code", "Participant"),
            ("learning_outcome", "Learning Outcome"),
            ("action", "Action"),
            ("comment", "Comment"),
            ("details", "Details"),
            ("created_at", "Date"),
        ],
        rows,
        summary,
        [{"label": "Export Teacher Oversight", "url": url_for("research.export_teacher_oversight")}],
    )


@research_bp.route("/research/feedback-responsiveness")
@role_required(*RESEARCH_ROLES)
def feedback_responsiveness():
    conn = get_db()
    filters = research_filter_values()
    rows = feedback_responsiveness_rows(conn, filters)
    summary = feedback_responsiveness_summary(rows)
    options = research_filter_options(conn)
    conn.close()
    return render_table(
        "AI Feedback Responsiveness",
        "A recommendation is followed only when the learner later submits practice or post-test evidence; merely opening a page is not counted.",
        [("participant_code", "Participant"), ("study_phase", "Phase"),
         ("subject", "Subject"), ("topic", "Topic"),
         ("learning_outcome", "Learning Outcome"), ("recommendation_type", "Type"),
         ("generated_at", "Generated"), ("viewed", "Viewed"),
         ("followed", "Followed"), ("response_delay_hours", "Response Delay (h)"),
         ("prior_score", "Prior Score"), ("next_score", "Next Score"),
         ("performance_change", "Performance Change"), ("response_evidence", "Follow-through Evidence")],
        rows, summary,
        [{"label": "Export Feedback Responsiveness", "url": url_for("research.export_feedback_responsiveness", **filters)}],
        filters=filters, filter_options=options,
        empty_message="No eligible AI recommendation records match these filters.",
    )


@research_bp.route("/research/system-reliability")
@role_required(*RESEARCH_ROLES)
def system_reliability():
    conn = get_db()
    filters = research_filter_values()
    rows = operational_reliability_rows(conn, filters)
    summary = operational_reliability_summary(rows)
    conn.close()
    return render_table(
        "Recorded System Reliability",
        "Application-event evidence only. This page does not present an external uptime percentage.",
        [("occurred_at", "Date"), ("event_type", "Event"), ("actor_role", "Role"),
         ("entity_type", "Entity"), ("event_status", "Status"),
         ("response_time_ms", "Response Time (ms)"), ("error_category", "Error Category"),
         ("offline_status", "Offline/Queue Status")],
        rows, summary,
        [{"label": "Export Reliability", "url": url_for("research.export_system_reliability", **filters)}],
        filters=filters,
        filter_options={"study_phases": (), "schools": (), "classes": (), "subjects": (), "topics": (), "outcomes": ()},
        empty_message="No application reliability events have been recorded yet.",
    )


@research_bp.route("/research/data-integrity")
@role_required(*RESEARCH_ROLES)
def data_integrity():
    conn = get_db()
    report = integrity_report(conn)
    conn.close()
    return render_table(
        "Research Data Integrity",
        "Read-only checks report inconsistencies. This tool never changes or deletes research data.",
        [("category", "Category"), ("severity", "Status"), ("issue", "Check"),
         ("count", "Affected"), ("recommended_action", "Recommended Action")],
        report["findings"], report["summary"],
    )


@research_bp.route("/research/data-collection-readiness")
@role_required(*RESEARCH_ROLES)
def data_collection_readiness():
    conn = get_db()
    report = readiness_report(conn)
    conn.close()
    return render_table(
        "Data Collection Readiness",
        f"Overall status: {report['overall_status']}. A blocked item must be resolved before claiming readiness for live dissertation data collection.",
        [("item", "Requirement"), ("status", "Status"), ("evidence", "Evidence / next action")],
        report["items"], report["summary"],
    )


@research_bp.route("/research/proposal-traceability")
@role_required(*RESEARCH_ROLES)
def proposal_traceability():
    rows = traceability_rows()
    return render_table(
        "Proposal Traceability Matrix",
        "Each research question and DSRM stage is connected to an operational measure, database evidence, application route, and Chapter 4–5 reporting location.",
        [("objective", "Objective"), ("research_question", "Research Question"),
         ("dsrm_stage", "DSRM Stage"), ("operational_measure", "Operational Measure"),
         ("database_evidence", "Database / Event Evidence"),
         ("application_route", "Application Route"), ("chapter_four", "Chapter 4"),
         ("chapter_five", "Chapter 5"), ("status", "Status")], rows,
        {"mapped_objectives": len(rows), "implemented": sum(1 for row in rows if row["status"] == "Implemented")},
    )


@research_bp.route("/research/questionnaires")
@role_required("learner", "teacher", "school_admin", "super_admin")
def questionnaires():
    conn = get_db()
    rows = questionnaire_rows(conn)
    conn.close()
    return render_template("research/questionnaires.html", questionnaires=rows, no_data=NO_DATA)


@research_bp.route("/research/questionnaires/create", methods=["GET", "POST"])
@role_required(*RESEARCH_ROLES)
@csrf_protect
def create_questionnaire():
    if request.method == "POST":
        title = (request.form.get("questionnaire_title") or "").strip()
        role = request.form.get("respondent_role") or "learner"
        description = (request.form.get("questionnaire_description") or "").strip()
        study_phase = request.form.get("study_phase") or "Pilot"
        item_lines = [line.strip() for line in (request.form.get("items_text") or "").splitlines() if line.strip()]
        if not title or not item_lines:
            flash("Questionnaire title and at least one item are required.", "danger")
            return redirect(url_for("research.create_questionnaire"))
        conn = get_db()
        try:
            cur = conn.execute("""
                INSERT INTO research_questionnaires
                (questionnaire_title, respondent_role, questionnaire_description, active_status)
                VALUES (?, ?, ?, 'Active')
            """, (title, role, description))
            questionnaire_id = cur.lastrowid
            conn.execute("UPDATE research_questionnaires SET study_phase=? WHERE id=?", (study_phase, questionnaire_id))
            for order, line in enumerate(item_lines, start=1):
                if "|" in line:
                    construct, item_text = [part.strip() for part in line.split("|", 1)]
                else:
                    construct, item_text = "general", line
                conn.execute("""
                    INSERT INTO research_questionnaire_items
                    (questionnaire_id, construct_name, item_text, display_order)
                    VALUES (?, ?, ?, ?)
                """, (questionnaire_id, construct, item_text, order))
            audit_research_event(conn, "CREATE_QUESTIONNAIRE", "research_questionnaire", questionnaire_id, title)
            conn.commit()
            conn.close()
            flash("Questionnaire created.", "success")
            return redirect(url_for("research.questionnaires"))
        except DatabaseIntegrityError:
            conn.rollback()
            conn.close()
            flash("A questionnaire with that title already exists.", "danger")
    return render_template("research/questionnaire_form.html", questionnaire=None, items_text="")


@research_bp.route("/research/questionnaires/<int:questionnaire_id>/edit", methods=["GET", "POST"])
@role_required(*RESEARCH_ROLES)
@csrf_protect
def edit_questionnaire(questionnaire_id):
    conn = get_db()
    questionnaire = conn.execute("SELECT * FROM research_questionnaires WHERE id=?", (questionnaire_id,)).fetchone()
    if not questionnaire:
        conn.close()
        return "Questionnaire not found", 404
    items = conn.execute("""
        SELECT * FROM research_questionnaire_items WHERE questionnaire_id=?
        ORDER BY display_order,id
    """, (questionnaire_id,)).fetchall()
    if request.method == "POST":
        title = (request.form.get("questionnaire_title") or "").strip()
        lines = [line.strip() for line in (request.form.get("items_text") or "").splitlines() if line.strip()]
        if not title or not lines:
            conn.close()
            flash("Questionnaire title and at least one item are required.", "danger")
            return redirect(url_for("research.edit_questionnaire", questionnaire_id=questionnaire_id))
        if one(conn, "SELECT COUNT(*) FROM research_questionnaire_responses WHERE questionnaire_id=?", (questionnaire_id,)):
            conn.close()
            flash("An instrument with responses cannot be structurally edited; create a versioned questionnaire instead.", "warning")
            return redirect(url_for("research.questionnaires"))
        try:
            conn.execute("""
                UPDATE research_questionnaires SET questionnaire_title=?, respondent_role=?,
                  questionnaire_description=?, study_phase=?, active_status=? WHERE id=?
            """, (title, request.form.get("respondent_role") or "learner",
                  (request.form.get("questionnaire_description") or "").strip(),
                  request.form.get("study_phase") or "Pilot",
                  request.form.get("active_status") or "Active", questionnaire_id))
            conn.execute("DELETE FROM research_questionnaire_items WHERE questionnaire_id=?", (questionnaire_id,))
            for order, line in enumerate(lines, start=1):
                construct, item_text = ([part.strip() for part in line.split("|", 1)]
                                        if "|" in line else ("general", line))
                conn.execute("""
                    INSERT INTO research_questionnaire_items
                    (questionnaire_id,construct_name,item_text,display_order,required)
                    VALUES (?,?,?,?,1)
                """, (questionnaire_id, construct, item_text, order))
            audit_research_event(conn, "UPDATE_QUESTIONNAIRE", "research_questionnaire", questionnaire_id,
                                 "Updated instrument before responses were collected")
            conn.commit()
            conn.close()
            flash("Questionnaire updated.", "success")
            return redirect(url_for("research.questionnaires"))
        except DatabaseIntegrityError:
            conn.rollback()
            flash("A questionnaire with that title already exists.", "danger")
    item_text = "\n".join(f"{item['construct_name']} | {item['item_text']}" for item in items)
    conn.close()
    return render_template("research/questionnaire_form.html", questionnaire=questionnaire, items_text=item_text)


@research_bp.route("/research/questionnaires/<int:questionnaire_id>/respond", methods=["GET", "POST"])
@role_required("learner", "teacher", "school_admin", "super_admin")
@csrf_protect
def respond_questionnaire(questionnaire_id):
    conn = get_db()
    questionnaire = conn.execute("SELECT * FROM research_questionnaires WHERE id=?", (questionnaire_id,)).fetchone()
    if not questionnaire:
        conn.close()
        return "Questionnaire not found", 404
    items = conn.execute("""
        SELECT * FROM research_questionnaire_items
        WHERE questionnaire_id=?
        ORDER BY display_order, id
    """, (questionnaire_id,)).fetchall()
    participant = conn.execute(
        f"""SELECT id FROM research_participants rp
            WHERE user_id=? AND {ELIGIBLE_PARTICIPANT_SQL}
            ORDER BY id LIMIT 1""",
        (session.get("user_id"),),
    ).fetchone()
    if request.method == "POST":
        if questionnaire["respondent_role"] != session.get("role"):
            conn.close()
            flash("This questionnaire is assigned to a different participant role.", "warning")
            return redirect(url_for("research.questionnaires"))
        if not participant:
            conn.close()
            flash("A consented, active research participant record is required before submitting a questionnaire.", "warning")
            return redirect(url_for("research.questionnaires"))
        existing = conn.execute("""
            SELECT id, completion_status FROM research_questionnaire_responses
            WHERE questionnaire_id=? AND respondent_user_id=?
        """, (questionnaire_id, session.get("user_id"))).fetchone()
        if existing:
            if existing["completion_status"] == "Submitted":
                conn.close()
                flash("A final response has already been submitted for this questionnaire.", "warning")
                return redirect(url_for("research.questionnaires"))
            response_id = existing["id"]
        else:
            cur = conn.execute("""
                INSERT INTO research_questionnaire_responses
                (questionnaire_id, respondent_user_id, participant_id, respondent_role)
                VALUES (?, ?, ?, ?)
            """, (questionnaire_id, session.get("user_id"), participant["id"] if participant else None, session.get("role")))
            response_id = cur.lastrowid
        for item in items:
            score = int(request.form.get(f"score_{item['id']}") or 0)
            if score < 1 or score > 5:
                conn.rollback()
                conn.close()
                flash("All questionnaire items require a score from 1 to 5.", "danger")
                return redirect(url_for("research.respond_questionnaire", questionnaire_id=questionnaire_id))
            existing_answer = conn.execute("""
                SELECT id FROM research_questionnaire_answers
                WHERE response_id=? AND item_id=?
            """, (response_id, item["id"])).fetchone()
            if existing_answer:
                conn.execute("""
                    UPDATE research_questionnaire_answers
                    SET score=?, comment=?
                    WHERE id=?
                """, (score, request.form.get(f"comment_{item['id']}") or None, existing_answer["id"]))
            else:
                conn.execute("""
                    INSERT INTO research_questionnaire_answers (response_id, item_id, score, comment)
                    VALUES (?, ?, ?, ?)
                """, (response_id, item["id"], score, request.form.get(f"comment_{item['id']}") or None))
        conn.execute("""
            UPDATE research_questionnaire_responses
            SET submitted_at=CURRENT_TIMESTAMP, completion_status='Submitted'
            WHERE id=?
        """, (response_id,))
        audit_research_event(conn, "QUESTIONNAIRE_SUBMITTED", "research_questionnaire", questionnaire_id, questionnaire["questionnaire_title"])
        conn.commit()
        conn.close()
        flash("Questionnaire response saved.", "success")
        return redirect(url_for("research.questionnaires"))
    conn.close()
    return render_template("research/questionnaire_response.html", questionnaire=questionnaire, items=items)


@research_bp.route("/research/questionnaire-results")
@role_required(*RESEARCH_ROLES)
def questionnaire_results():
    conn = get_db()
    rows = questionnaire_result_rows(conn)
    summary = {
        "questionnaire_response_count": one(conn, "SELECT COUNT(*) FROM research_questionnaire_responses"),
        "average_learner_satisfaction": average_questionnaire_score(conn, role="learner", construct="satisfaction"),
        "average_teacher_satisfaction": average_questionnaire_score(conn, role="teacher"),
    }
    conn.close()
    return render_table(
        "Questionnaire Results",
        "Aggregated 5-point Likert results by respondent group and construct.",
        [
            ("questionnaire_title", "Questionnaire"),
            ("respondent_role", "Role"),
            ("construct_name", "Construct"),
            ("average_score", "Average Score"),
            ("sample_standard_deviation", "Sample SD"),
            ("responses", "Responses"),
            ("answers", "Answers"),
            ("score_1_frequency", "1s"), ("score_2_frequency", "2s"),
            ("score_3_frequency", "3s"), ("score_4_frequency", "4s"),
            ("score_5_frequency", "5s"),
        ],
        rows,
        summary,
        [{"label": "Export Questionnaires", "url": url_for("research.export_questionnaires")}],
    )


@research_bp.route("/research/system-logs")
@role_required(*RESEARCH_ROLES)
def system_logs():
    conn = get_db()
    rows = system_log_rows(conn, limit=200)
    reliability = reliability_summary(conn)
    conn.close()
    return render_table(
        "System Logs for Research",
        "Audit and learner activity records used to support reliability, usage and oversight analysis.",
        [
            ("source", "Source"),
            ("participant_code", "Participant"),
            ("action", "Action"),
            ("entity_type", "Entity Type"),
            ("entity_id", "Entity ID"),
            ("details", "Details"),
            ("created_at", "Date"),
        ],
        rows,
        reliability,
    )


@research_bp.route("/research/reports")
@research_bp.route("/research/export/csv")
@role_required(*RESEARCH_ROLES)
def research_reports():
    conn = get_db()
    metrics = research_metrics(conn)
    weak_concepts = weak_concept_rows(conn, limit=50)
    if request.args.get("format") == "csv" or request.path.endswith("/export/csv"):
        rows = [{"metric": key, "value": value} for key, value in metrics.items()]
        conn.close()
        return csv_response("learn2master_research_report.csv", [("metric", "metric"), ("value", "value")], rows, "research_report")
    conn.close()
    return render_template("research/reports.html", metrics=metrics, weak_concepts=weak_concepts)


@research_bp.route("/research/chapter-four-report")
@role_required(*RESEARCH_ROLES)
def chapter_four_report():
    conn = get_db()
    filters = research_filter_values()
    feedback_rows = feedback_responsiveness_rows(conn, filters)
    reliability_rows = operational_reliability_rows(conn, filters)
    integrity = integrity_report(conn)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": filters,
        "metrics": research_metrics(conn),
        "participants": participant_rows(conn, filters),
        "pretest": assessment_result_rows(conn, "pretest", filters),
        "posttest": assessment_result_rows(conn, "posttest", filters),
        "learning_gain": learning_gain_rows(conn, filters),
        "mastery": mastery_rows(conn, filters),
        "teacher_summary": teacher_oversight_data(conn)[0],
        "feedback_rows": feedback_rows,
        "feedback_summary": feedback_responsiveness_summary(feedback_rows),
        "reliability_rows": reliability_rows,
        "reliability_summary": operational_reliability_summary(reliability_rows),
        "integrity": integrity,
        "questionnaire_results": questionnaire_result_rows(conn),
        "system_logs": system_log_rows(conn, limit=20),
        "readiness": chapter_evidence_readiness(conn),
    }
    data["gain_summary"] = learning_gain_stats(data["learning_gain"])
    data["mastery_summary"] = mastery_summary(
        data["mastery"],
        participant_summary(conn, filters)["eligible_learners"],
    )
    data["excluded_unpaired_cases"] = max(0, len(data["pretest"]) - data["gain_summary"]["valid_pairs"])
    conn.close()
    return render_template("research/chapter_four.html", no_data=NO_DATA, **data)


@research_bp.route("/research/chapter-five-insights")
@role_required(*RESEARCH_ROLES)
def chapter_five_insights():
    conn = get_db()
    metrics = research_metrics(conn)
    gains = learning_gain_rows(conn)
    weak_concepts = weak_concept_rows(conn, limit=6)
    oversight_summary, _ = teacher_oversight_data(conn)
    questionnaire_results = questionnaire_result_rows(conn)
    readiness = chapter_evidence_readiness(conn)
    has_data = bool(gains or questionnaire_results or metrics["attempts"])
    insights = []
    def add(statement, metric, source, valid_cases, scope, evidence_type="observational"):
        insights.append({"statement": statement, "metric": metric, "source": source,
                         "valid_cases": valid_cases, "scope": scope, "evidence_type": evidence_type})
    if has_data:
        if metrics["average_learning_gain"] > 0:
            add(f"The valid paired records show an average positive change of {metrics['average_learning_gain']} percentage points; this observational result does not by itself establish causation.", metrics["average_learning_gain"], "Paired assessment attempts", len(gains), "Eligible paired learners/outcomes in the recorded study phase")
        else:
            add("The recorded paired evidence does not currently show a positive mean gain, or the valid-pair sample is empty.", metrics["average_learning_gain"], "Paired assessment attempts", len(gains), "Eligible paired cases")
        add(f"Recorded mastery attainment is {metrics['mastery_attainment_rate']}% among represented outcome records.", metrics["mastery_attainment_rate"], "Mastery records", metrics["learners"], "Eligible research participants with mastery evidence")
        if weak_concepts:
            concepts = ", ".join(row["concept_tag"].replace("_", " ") for row in weak_concepts[:3])
            add(f"Frequently recorded weak-concept tags include {concepts}; qualitative review is required before treating tags as themes.", len(weak_concepts), "Attempt weak-concept tags", metrics["attempts"], "Recorded assessment attempts")
        add(f"AI support is represented by {metrics['ai_recommendations']} recommendation records with mean stored confidence {metrics['avg_ai_confidence']}%.", metrics["ai_recommendations"], "Recommendations and AI explanations", metrics["ai_recommendations"], "Generated recommendation records", "system-generated evidence")
        add(f"Teacher oversight includes {oversight_summary['number_of_interventions']} interventions, {oversight_summary['teacher_approvals']} approvals and {oversight_summary['teacher_overrides']} overrides.", oversight_summary["number_of_interventions"], "Teacher oversight tables", oversight_summary["learners_supported_by_teacher"], "Recorded teacher actions")
        if metrics["questionnaire_response_count"]:
            add(f"User-acceptance evidence includes {metrics['questionnaire_response_count']} final questionnaire response(s).", metrics["questionnaire_response_count"], "Research questionnaires", metrics["questionnaire_response_count"], "Submitted learner and teacher instruments", "self-report evidence")
        else:
            add("No final questionnaire responses are available, so user acceptance cannot yet be interpreted.", "No data yet.", "Research questionnaires", 0, "No completed instruments", "missing evidence")
        if metrics["sync_success_rate"] == NO_DATA:
            add("No synchronization outcomes have been recorded; external hosting uptime is also outside the application-event dataset.", NO_DATA, "Sync and research events", 0, "Recorded application events only", "operational evidence")
        else:
            add(
                f"Recorded low-connectivity synchronization succeeded for {metrics['sync_success_rate']}% of observed items, "
                f"with {metrics['recorded_system_incidents']} recorded failure incident(s).",
                metrics["sync_success_rate"], "Sync events", metrics["system_usage_count"], "Recorded synchronization events", "operational evidence"
            )
        add("Limitations include legacy attempts without exact start times, possible small-sample instability, and no external provider uptime measurement in this database.", "Limitation", "Schema and completeness review", len(gains), "Current recorded evidence", "limitation")
        add("Recommended next work is to complete the approved pilot, review manual qualitative themes, and triangulate application events with separately collected hosting evidence.", "Recommendation", "Readiness and integrity reports", len(gains), "Future study activity", "recommendation")
    conn.close()
    return render_template(
        "research/chapter_five.html",
        has_data=has_data,
        insights=insights,
        readiness=readiness,
    )


@research_bp.route("/research/export/pre-post")
@role_required(*RESEARCH_ROLES)
def export_pre_post():
    conn = get_db()
    filters = research_filter_values()
    rows = assessment_result_rows(conn, filters=filters)
    conn.close()
    return csv_response("learn2master_pre_post_results.csv", assessment_columns(), rows, "pre_post")


@research_bp.route("/research/export/learning-gain")
@role_required(*RESEARCH_ROLES)
def export_learning_gain():
    conn = get_db()
    filters = research_filter_values()
    rows = learning_gain_rows(conn, filters)
    conn.close()
    columns = [
        ("participant_code", "participant_code"),
        ("study_phase", "study_phase"),
        ("subject", "subject"),
        ("topic", "topic"),
        ("learning_outcome", "learning_outcome"),
        ("pre_attempt_id", "pretest_attempt_id"),
        ("post_attempt_id", "posttest_attempt_id"),
        ("pre_test", "pre_test"),
        ("post_test", "post_test"),
        ("learning_gain", "learning_gain"),
        ("normalized_gain", "normalized_gain"),
        ("percentage_improvement", "percentage_improvement"),
        ("mastery_status", "mastery_status"),
    ]
    return csv_response("learn2master_learning_gain.csv", columns, rows, "learning_gain")


@research_bp.route("/research/export/mastery")
@role_required(*RESEARCH_ROLES)
def export_mastery():
    conn = get_db()
    filters = research_filter_values()
    rows = mastery_rows(conn, filters)
    conn.close()
    columns = [
        ("participant_code", "participant_code"),
        ("subject", "subject"),
        ("topic", "topic"),
        ("learning_outcome", "learning_outcome"),
        ("study_phase", "study_phase"),
        ("pre_attempt_id", "pretest_attempt_id"),
        ("post_attempt_id", "posttest_attempt_id"),
        ("mastery_status", "mastery_status"),
        ("mastery_level", "mastery_level"),
        ("mastery_score", "mastery_score"),
        ("attempts", "attempts"),
        ("time_to_mastery", "time_to_mastery"),
    ]
    return csv_response("learn2master_mastery.csv", columns, rows, "mastery")


@research_bp.route("/research/export/feedback-responsiveness")
@role_required(*RESEARCH_ROLES)
def export_feedback_responsiveness():
    conn = get_db()
    rows = feedback_responsiveness_rows(conn, research_filter_values())
    conn.close()
    columns = [(key, key) for key in (
        "participant_code", "study_phase", "subject", "topic", "learning_outcome",
        "recommendation_id", "recommendation_type", "generated_at", "viewed_at",
        "followed_at", "response_delay_hours", "prior_score", "next_score",
        "performance_change", "response_evidence", "confidence_score",
    )]
    return csv_response("learn2master_feedback_responsiveness.csv", columns, rows, "feedback_responsiveness")


@research_bp.route("/research/export/teacher-oversight")
@role_required(*RESEARCH_ROLES)
def export_teacher_oversight():
    conn = get_db()
    _, rows = teacher_oversight_data(conn)
    conn.close()
    columns = [(key, key) for key in (
        "record_type", "participant_code", "learning_outcome", "action",
        "comment", "details", "created_at",
    )]
    return csv_response("learn2master_teacher_oversight.csv", columns, rows, "teacher_oversight")


@research_bp.route("/research/export/system-reliability")
@role_required(*RESEARCH_ROLES)
def export_system_reliability():
    conn = get_db()
    rows = operational_reliability_rows(conn, research_filter_values())
    conn.close()
    columns = [(key, key) for key in (
        "event_id", "actor_role", "event_type", "entity_type", "entity_id",
        "response_time_ms", "event_status", "error_category", "offline_status", "occurred_at",
    )]
    return csv_response("learn2master_system_reliability.csv", columns, rows, "system_reliability")


@research_bp.route("/research/export/questionnaires")
@role_required(*RESEARCH_ROLES)
def export_questionnaires():
    conn = get_db()
    rows = questionnaire_result_rows(conn)
    conn.close()
    columns = [
        ("questionnaire_title", "questionnaire_title"),
        ("respondent_role", "respondent_role"),
        ("construct_name", "construct"),
        ("average_score", "average_score"),
        ("sample_standard_deviation", "sample_standard_deviation"),
        ("responses", "responses"),
        ("answers", "answers"),
        ("score_1_frequency", "score_1_frequency"),
        ("score_2_frequency", "score_2_frequency"),
        ("score_3_frequency", "score_3_frequency"),
        ("score_4_frequency", "score_4_frequency"),
        ("score_5_frequency", "score_5_frequency"),
    ]
    return csv_response("learn2master_questionnaires.csv", columns, rows, "questionnaires")


@research_bp.route("/research/export/full-dataset")
@role_required(*RESEARCH_ROLES)
def export_full_dataset():
    conn = get_db()
    rows = full_dataset_rows(conn)
    conn.close()
    columns = [
        ("participant_code", "participant_code"),
        ("subject", "subject"),
        ("topic", "topic"),
        ("learning_outcome", "learning_outcome"),
        ("pre_test", "pre_test"),
        ("post_test", "post_test"),
        ("learning_gain", "learning_gain"),
        ("normalized_gain", "normalized_gain"),
        ("mastery_status", "mastery_status"),
        ("attempts", "attempts"),
        ("time_to_mastery", "time_to_mastery"),
        ("teacher_intervention", "teacher_intervention"),
        ("ai_confidence", "ai_confidence"),
        ("reflection_completed", "reflection_completed"),
        ("practical_completed", "practical_completed"),
        ("questionnaire_score", "questionnaire_score"),
    ]
    return csv_response("learn2master_full_research_dataset.csv", columns, rows, "full_dataset")
