import csv
import io
import math
import re
from datetime import datetime, timezone
from statistics import stdev

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, session, url_for

from database import DatabaseIntegrityError, get_db
from routes.guards import role_required
from security import csrf_protect
from services.evaluation_dataset import (
    PUBLIC_RECORD_SOURCE,
    SUPPLIED_DISCLAIMER,
    evaluation_evidence_summary,
    evaluation_dataset_rows,
    evaluation_dataset_summary,
    evaluation_qualitative_theme_rows,
    evaluation_reliability_rows,
)
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
EVALUATION_SCHOOL_CODES = {
    "kigezi high school": "KZHS",
    "kigata high school": "KTHS",
}
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
        "study_phases": ("Evaluation", "Pilot", "Baseline", "Intervention", "Follow-up", "Actual"),
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
    not_mastered = sum(1 for row in rows if row["mastery_status"] in {
        "Not Started", "Practice Required", "Not yet mastered", "Not Yet Mastered",
    })
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
    evaluation_register = evaluation_dataset_summary(conn)
    evaluation_acceptance = sum(
        1 for row in evaluation_dataset_rows(conn)
        if row.get("acceptance_mean") is not None
    )
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
            "present": evaluation_register["total_records"] > 0 or participants["eligible_participants"] > 0,
            "evidence": f"{evaluation_register['total_records']} evaluation record(s) plus {participants['eligible_participants']} linked portal participant(s)",
            "route": "research.research_dashboard",
        },
        {
            "label": "Paired pre/post evidence",
            "present": evaluation_register["complete_pairs"] > 0 or bool(gains),
            "evidence": f"{evaluation_register['complete_pairs']} evaluation pair(s) plus {len(gains)} portal pair(s)",
            "route": "research.research_dashboard",
        },
        {
            "label": "Mastery evidence",
            "present": evaluation_register["mastered_records"] > 0 or bool(mastery),
            "evidence": f"{evaluation_register['mastered_records']} evaluation mastery record(s) plus {len(mastery)} portal mastery record(s)",
            "route": "research.research_dashboard",
        },
        {
            "label": "Teacher oversight evidence",
            "present": oversight["number_of_interventions"] > 0,
            "evidence": f"{oversight['number_of_interventions']} intervention(s)",
            "route": "research.teacher_oversight",
        },
        {
            "label": "User acceptance evidence",
            "present": evaluation_acceptance > 0 or questionnaire_responses > 0,
            "evidence": f"{evaluation_acceptance} evaluation acceptance record(s) plus {questionnaire_responses} portal response(s)",
            "route": "research.research_dashboard",
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


def live_questionnaire_response_rows(conn):
    """Return one automatically captured acceptance row per submitted response."""
    rows = conn.execute(f"""
        SELECT rp.participant_code, rp.study_phase, q.respondent_role,
               q.questionnaire_title,
               ROUND(CAST(AVG(a.score) AS NUMERIC), 2) AS acceptance_score,
               r.submitted_at
        FROM research_questionnaire_responses r
        JOIN research_questionnaire_answers a ON a.response_id=r.id
        JOIN research_questionnaires q ON q.id=r.questionnaire_id
        JOIN research_participants rp
          ON (rp.id=r.participant_id OR (r.participant_id IS NULL AND rp.user_id=r.respondent_user_id))
         AND {ELIGIBLE_PARTICIPANT_SQL}
        WHERE COALESCE(r.completion_status,'Submitted')='Submitted'
        GROUP BY r.id, rp.participant_code, rp.study_phase, q.respondent_role,
                 q.questionnaire_title, r.submitted_at
        ORDER BY r.submitted_at, rp.participant_code
    """).fetchall()
    return [row_dict(row) for row in rows]


def evaluation_register_matches_filters(filters=None):
    """Evaluation records have participant references, not portal foreign keys or assessment dates."""
    filters = filters or {}
    if filters.get("study_phase") not in (None, "", "Evaluation"):
        return False
    return not any(filters.get(key) not in (None, "") for key in (
        "topic_id", "outcome_id", "date_from", "date_to",
    ))


def evaluation_register_filter_context(conn, filters=None):
    """Resolve portal filter IDs to the reference values stored in evaluation rows."""
    filters = filters or {}
    if not evaluation_register_matches_filters(filters):
        return None
    context = {}
    if filters.get("school_id"):
        school = conn.execute(
            "SELECT school_name FROM schools WHERE school_id=?",
            (filters["school_id"],),
        ).fetchone()
        context["school_code"] = EVALUATION_SCHOOL_CODES.get(
            (school["school_name"] if school else "").strip().lower()
        )
        if not context["school_code"]:
            return None
    if filters.get("class_id"):
        school_class = conn.execute(
            "SELECT class_name FROM classes WHERE class_id=?",
            (filters["class_id"],),
        ).fetchone()
        context["class_level"] = school_class["class_name"] if school_class else None
        if not context["class_level"]:
            return None
    if filters.get("subject_id"):
        subject = conn.execute(
            "SELECT subject_name FROM subjects WHERE subject_id=?",
            (filters["subject_id"],),
        ).fetchone()
        context["subject"] = subject["subject_name"] if subject else None
        if not context["subject"]:
            return None
    return context


def evaluation_register_row_matches_context(row, context):
    if context is None:
        return False
    return all(
        str(row.get(key) or "").strip().lower() == str(value or "").strip().lower()
        for key, value in context.items()
    )


def evaluation_register_participant_rows(conn, filters=None):
    context = evaluation_register_filter_context(conn, filters)
    if context is None:
        return []
    filters = filters or {}
    results = []
    for row in evaluation_dataset_rows(conn):
        if not evaluation_register_row_matches_context(row, context):
            continue
        role_name = row["record_type"]
        if filters.get("role") and filters["role"] != role_name:
            continue
        if filters.get("consent_status"):
            continue
        study_status = row.get("study_status") or "Recorded"
        if filters.get("active_status") and filters["active_status"] != study_status:
            continue
        learner_payload = row.get("payload", {}).get("learner_study") or {}
        results.append({
            "record_source": PUBLIC_RECORD_SOURCE,
            "participant_code": row["participant_code"],
            "role_name": role_name,
            "school_name": row.get("school_code") or "",
            "class_name": row.get("class_level") or "",
            "subject_name": row.get("subject") or "",
            "study_phase": "Evaluation",
            "participation_status": learner_payload.get("eligibility_status") or study_status,
            "consent_status": "Not recorded in evaluation source",
            "assent_status": "Not recorded in evaluation source",
            "parent_consent_status": "Not recorded in evaluation source",
            "active_status": study_status,
            "_view_url": url_for(
                "research.evaluation_participant_view",
                participant_code=row["participant_code"],
            ),
        })
    return results


def connected_participant_rows(conn, filters=None):
    dataset_rows = evaluation_register_participant_rows(conn, filters)
    portal_rows = participant_rows(conn, filters)
    for row in portal_rows:
        row["record_source"] = "Learn2Master portal"
        row["participation_status"] = row.get("consent_status") or row.get("active_status") or ""
        row["_view_url"] = url_for("research.view_participant", participant_id=row["id"])
    return sorted(dataset_rows + portal_rows, key=lambda row: (row["participant_code"], row["record_source"]))


def connected_participant_summary(conn, rows, filters=None):
    dataset_rows = [row for row in rows if row["record_source"] == PUBLIC_RECORD_SOURCE]
    portal_rows = [row for row in rows if row["record_source"] == "Learn2Master portal"]
    eligible_portal = [
        row for row in portal_rows
        if row.get("active_status") == "Active"
        and row.get("consent_status") == "Granted"
        and row.get("assent_status") in {"Granted", "Not Applicable"}
        and row.get("parent_consent_status") in {"Granted", "Not Applicable"}
    ]
    return {
        "total_research_identities": len(rows),
        "evaluation_records": len(dataset_rows),
        "portal_participants": len(portal_rows),
        "learners": sum(1 for row in rows if row.get("role_name") == "learner"),
        "teachers": sum(1 for row in rows if row.get("role_name") == "teacher"),
        "completed_evaluation_learners": sum(
            1 for row in dataset_rows
            if row.get("role_name") == "learner" and row.get("active_status") == "Completed"
        ),
        "eligible_portal_participants": len(eligible_portal),
    }


def evaluation_register_assessment_rows(conn, assessment_type=None, filters=None):
    context = evaluation_register_filter_context(conn, filters)
    if context is None:
        return []
    requested = {
        "pretest": ("pre_test_pct", "pre_test"),
        "posttest": ("post_test_pct", "post_test"),
    }
    types = [requested[assessment_type]] if assessment_type in requested else list(requested.values())
    results = []
    for row in evaluation_dataset_rows(conn, "learner"):
        if not evaluation_register_row_matches_context(row, context):
            continue
        for value_key, display_type in types:
            value = row.get(value_key)
            if value is None:
                continue
            results.append({
                "record_source": PUBLIC_RECORD_SOURCE,
                "participant_code": row["participant_code"],
                "study_phase": "Evaluation",
                "learner_id": "",
                "subject": row.get("subject") or "",
                "topic": "Framework evaluation",
                "learning_outcome": "Framework evaluation",
                "assessment_type": display_type,
                "score": value,
                "total_marks": 100,
                "percentage": value,
                "date_taken": "Not recorded in evaluation source",
                "start_time": "Not recorded",
                "end_time": "Not recorded",
                "time_spent": "Not recorded",
                "time_spent_seconds": "",
                "concepts_correct": "Not itemized",
                "concepts_weak": "Not itemized",
                "ai_diagnosis": "",
            })
    return results


def connected_assessment_rows(conn, assessment_type=None, filters=None):
    dataset_rows = evaluation_register_assessment_rows(conn, assessment_type, filters)
    portal_rows = assessment_result_rows(conn, assessment_type, filters)
    for row in portal_rows:
        row["record_source"] = "Learn2Master portal"
    return dataset_rows + portal_rows


def evaluation_register_learning_gain_rows(conn, filters=None):
    context = evaluation_register_filter_context(conn, filters)
    if context is None:
        return []
    results = []
    for row in evaluation_dataset_rows(conn, "learner"):
        if not evaluation_register_row_matches_context(row, context):
            continue
        pre = row.get("pre_test_pct")
        post = row.get("post_test_pct")
        if pre is None or post is None:
            continue
        gain = row.get("gain_points")
        gain = round(float(post) - float(pre), 2) if gain is None else gain
        normalized_gain = round(float(gain) / (100 - float(pre)), 3) if float(pre) < 100 else "Not applicable"
        improvement = round((float(gain) / float(pre)) * 100, 1) if float(pre) > 0 else "Not applicable"
        payload = row.get("payload", {}).get("learner_study") or {}
        results.append({
            "record_source": PUBLIC_RECORD_SOURCE,
            "participant_code": row["participant_code"],
            "study_phase": "Evaluation",
            "school_code": row.get("school_code") or "",
            "school": row.get("school_code") or "",
            "class": row.get("class_level") or "",
            "subject": row.get("subject") or "",
            "topic": "Framework evaluation",
            "learning_outcome": "Framework evaluation",
            "pre_attempt_id": f"EVAL-{row['participant_code']}-PRE",
            "post_attempt_id": f"EVAL-{row['participant_code']}-POST",
            "pre_test": pre,
            "post_test": post,
            "absolute_gain": gain,
            "learning_gain": gain,
            "normalized_gain": normalized_gain,
            "percentage_improvement": improvement,
            "pre_date": "",
            "post_date": "",
            "mastery_status": row.get("mastery_status") or "Not recorded",
            "mastery_score": post,
            "attempts": payload.get("practice_attempts") or 0,
            "ai_confidence": "",
            "reflection_completed": payload.get("reflection_complete") or "Not recorded",
            "practical_completed": payload.get("practical_evidence_verified") or "Not recorded",
            "teacher_intervention": payload.get("teacher_interventions") or 0,
        })
    return results


def connected_learning_gain_rows(conn, filters=None):
    dataset_rows = evaluation_register_learning_gain_rows(conn, filters)
    portal_rows = learning_gain_rows(conn, filters)
    for row in portal_rows:
        row["record_source"] = "Learn2Master portal"
    return dataset_rows + portal_rows


def evaluation_register_mastery_rows(conn, filters=None):
    source_rows = {
        item["participant_code"]: item
        for item in evaluation_dataset_rows(conn, "learner")
    }
    results = []
    for row in evaluation_register_learning_gain_rows(conn, filters):
        source = source_rows[row["participant_code"]]
        payload = source.get("payload", {}).get("learner_study") or {}
        mastered = row["mastery_status"] == "Mastered"
        time_hours = payload.get("time_to_mastery_hours")
        results.append({
            "record_source": PUBLIC_RECORD_SOURCE,
            "participant_code": row["participant_code"],
            "study_phase": "Evaluation",
            "subject": row["subject"],
            "topic": row["topic"],
            "learning_outcome": row["learning_outcome"],
            "mastery_status": row["mastery_status"],
            "mastery_level": "Mastered" if mastered else "Developing",
            "mastery_score": row["post_test"],
            "attempts": row["attempts"],
            "time_to_mastery": time_hours if time_hours is not None else "Not yet mastered",
            "updated_at": source.get("imported_at") or "",
        })
    return results


def connected_mastery_rows(conn, filters=None):
    dataset_rows = evaluation_register_mastery_rows(conn, filters)
    portal_rows = mastery_rows(conn, filters)
    for row in portal_rows:
        row["record_source"] = "Learn2Master portal"
    return dataset_rows + portal_rows


def evaluation_register_questionnaire_rows(conn):
    results = []
    configurations = (
        ("learner", "learner_survey", "LQ", "learner_acceptance_mean", "Learner Acceptance Evaluation"),
        ("teacher", "teacher_survey", "TQ", "teacher_acceptance_mean", "Teacher Acceptance Evaluation"),
    )
    for role, payload_key, prefix, mean_key, title in configurations:
        responses = []
        scores = []
        for row in evaluation_dataset_rows(conn, role):
            survey = row.get("payload", {}).get(payload_key) or {}
            if not survey:
                continue
            responses.append(row["participant_code"])
            for key, value in survey.items():
                if not key.startswith(prefix) or key == mean_key or "connectivity_interfered" in key:
                    continue
                if isinstance(value, (int, float)) and 1 <= value <= 5:
                    scores.append(int(value))
        if not responses:
            continue
        results.append({
            "record_source": PUBLIC_RECORD_SOURCE,
            "questionnaire_title": title,
            "respondent_role": role,
            "construct_name": "Overall acceptance",
            "average_score": round(sum(scores) / len(scores), 2) if scores else 0,
            "sample_standard_deviation": round(stdev(scores), 2) if len(scores) > 1 else 0,
            "responses": len(responses),
            "answers": len(scores),
            **{f"score_{score}_frequency": scores.count(score) for score in range(1, 6)},
        })
    return results


def connected_questionnaire_rows(conn):
    dataset_rows = evaluation_register_questionnaire_rows(conn)
    portal_rows = questionnaire_result_rows(conn)
    for row in portal_rows:
        row["record_source"] = "Learn2Master portal"
    return dataset_rows + portal_rows


def evaluation_register_teacher_oversight_rows(conn):
    rows = []
    for record in evaluation_dataset_rows(conn, "learner"):
        payload = record.get("payload", {}).get("learner_study") or {}
        intervention_count = int(payload.get("teacher_interventions") or 0)
        for number in range(1, intervention_count + 1):
            rows.append({
                "record_source": PUBLIC_RECORD_SOURCE,
                "record_type": "Teacher Intervention",
                "participant_code": record["participant_code"],
                "learning_outcome": "Framework evaluation",
                "action": f"Intervention {number} of {intervention_count}",
                "comment": "Recorded intervention during the evaluation",
                "details": record.get("mastery_status") or "",
                "created_at": "Date not recorded in evaluation source",
            })
    return rows


def connected_teacher_oversight_data(conn):
    portal_summary, portal_rows = teacher_oversight_data(conn)
    dataset_rows = evaluation_register_teacher_oversight_rows(conn)
    for row in portal_rows:
        row["record_source"] = "Learn2Master portal"
    rows = dataset_rows + portal_rows
    summary = dict(portal_summary)
    summary.update({
        "evaluation_interventions": len(dataset_rows),
        "portal_interventions": portal_summary["number_of_interventions"],
        "number_of_interventions": len(dataset_rows) + portal_summary["number_of_interventions"],
        "learners_supported_by_teacher": len({row["participant_code"] for row in rows}),
    })
    return summary, rows


def evaluation_register_feedback_rows(conn, filters=None):
    context = evaluation_register_filter_context(conn, filters)
    if context is None:
        return []
    rows = []
    for record in evaluation_dataset_rows(conn, "learner"):
        if not evaluation_register_row_matches_context(record, context):
            continue
        payload = record.get("payload", {}).get("learner_study") or {}
        received = int(payload.get("recommendations_received") or 0)
        acted_on = min(received, int(payload.get("recommendations_acted_on") or 0))
        for number in range(1, received + 1):
            followed = number <= acted_on
            rows.append({
                "record_source": PUBLIC_RECORD_SOURCE,
                "participant_code": record["participant_code"],
                "study_phase": "Evaluation",
                "subject": record.get("subject") or "",
                "topic": "Framework evaluation",
                "learning_outcome": "Framework evaluation",
                "recommendation_id": f"EVAL-{record['participant_code']}-R{number}",
                "recommendation_type": "Recorded AI recommendation",
                "generated_at": "Date not recorded in evaluation source",
                "viewed": "Yes" if followed else "Not recorded",
                "followed": "Yes" if followed else "No",
                "response_delay_hours": "",
                "prior_score": record.get("pre_test_pct") if number == 1 else "",
                "next_score": record.get("post_test_pct") if followed else "",
                "performance_change": record.get("gain_points") if followed and number == acted_on else "",
                "response_evidence": f"{acted_on} of {received} recommendations recorded as acted on",
                "confidence_score": "",
            })
    return rows


def connected_feedback_rows(conn, filters=None):
    dataset_rows = evaluation_register_feedback_rows(conn, filters)
    portal_rows = feedback_responsiveness_rows(conn, filters)
    for row in portal_rows:
        row["record_source"] = "Learn2Master portal"
    return dataset_rows + portal_rows


def connected_reliability_rows(conn, filters=None):
    dataset_rows = []
    filters = filters or {}
    for row in evaluation_reliability_rows(conn):
        if filters.get("date_from") and row["event_date"] < filters["date_from"]:
            continue
        if filters.get("date_to") and row["event_date"] > filters["date_to"]:
            continue
        dataset_rows.append({
                "record_source": PUBLIC_RECORD_SOURCE,
                "evidence_level": "Daily aggregate",
                "occurred_at": row["event_date"],
                "total_events": row["total_events"],
                "successful_events": row["successful_events"],
                "error_events": row["error_events"],
                "success_rate_pct": row["success_rate_pct"],
                "average_latency_ms": row["average_latency_ms"],
                "p95_latency_ms": row["p95_latency_ms"],
                "offline_queued_events": row["offline_queued_events"],
                "successful_sync_events": row["successful_sync_events"],
                "incident_category": row.get("incident_category") or "None",
        })
    portal_rows = operational_reliability_rows(conn, filters)
    results = list(dataset_rows)
    for row in portal_rows:
        success = str(row.get("event_status") or "").lower() == "success"
        failure = str(row.get("event_status") or "").lower() == "failure"
        offline = str(row.get("offline_status") or "").lower()
        results.append({
            "record_source": "Learn2Master portal",
            "evidence_level": "Individual event",
            "occurred_at": row.get("occurred_at") or "",
            "total_events": 1,
            "successful_events": int(success),
            "error_events": int(failure),
            "success_rate_pct": 100 if success else (0 if failure else "Not classified"),
            "average_latency_ms": row.get("response_time_ms") if row.get("response_time_ms") is not None else "",
            "p95_latency_ms": "",
            "offline_queued_events": int(offline not in ("", "online")),
            "successful_sync_events": int(success and offline not in ("", "online")),
            "incident_category": row.get("error_category") or "None",
        })
    return results


def connected_reliability_summary(conn, rows=None):
    rows = rows if rows is not None else connected_reliability_rows(conn)
    total_events = sum(int(row.get("total_events") or 0) for row in rows)
    successful_events = sum(int(row.get("successful_events") or 0) for row in rows)
    error_events = sum(int(row.get("error_events") or 0) for row in rows)
    offline_queued = sum(int(row.get("offline_queued_events") or 0) for row in rows)
    successful_sync = sum(int(row.get("successful_sync_events") or 0) for row in rows)
    latency_weight = sum(
        float(row.get("average_latency_ms") or 0) * int(row.get("total_events") or 0)
        for row in rows if row.get("average_latency_ms") not in (None, "")
    )
    latency_events = sum(
        int(row.get("total_events") or 0)
        for row in rows if row.get("average_latency_ms") not in (None, "")
    )
    evidence = evaluation_evidence_summary(conn)
    dataset_days = sum(1 for row in rows if row.get("record_source") == PUBLIC_RECORD_SOURCE)
    portal_events = sum(1 for row in rows if row.get("record_source") == "Learn2Master portal")
    return {
        "recorded_events": total_events,
        "successful_events": successful_events,
        "application_errors": error_events,
        "recorded_success_rate": round(successful_events / total_events * 100, 2) if total_events else NO_DATA,
        "average_response_time_ms": round(latency_weight / latency_events, 1) if latency_events else NO_DATA,
        "offline_sync_success_rate": round(successful_sync / offline_queued * 100, 2) if offline_queued else NO_DATA,
        "evaluation_daily_records": dataset_days,
        "portal_event_records": portal_events,
        "recorded_period": (
            f"{evidence['reliability_log_start']} to {evidence['reliability_log_end']}"
            if evidence["reliability_log_start"] else NO_DATA
        ),
        "verified_coverage_days": evidence["verified_evaluation_coverage_days"],
        "six_month_status": evidence["coverage_status"],
        "median_response_time_ms": "Not calculated for daily aggregates",
        "scope_note": "The evaluation register supplies daily operational aggregates; new portal events are added individually and retain their source label.",
    }


def evaluation_collection_audit_rows(conn):
    summary = evaluation_dataset_summary(conn)
    evidence = evaluation_evidence_summary(conn)
    return [
        {"evidence_stream": "Participant register", "collection_method": "Purposive maximum-variation sampling in two CBC secondary schools", "records": summary["learner_records"] + summary["teacher_records"], "period_or_sample": "64 recorded learners; 8 recorded teachers", "verification_status": "Recorded in evaluation register"},
        {"evidence_stream": "Learning outcomes", "collection_method": "Single-group matched pre-test/post-test evaluation", "records": summary["complete_pairs"], "period_or_sample": "60 complete pairs; 2 withdrawals; 2 missing post-tests", "verification_status": "Supported as a pre/post association"},
        {"evidence_stream": "Learner acceptance", "collection_method": "Ten-item 5-point Likert questionnaire; LQ9 reverse-scored", "records": summary["learner_questionnaire_responses"], "period_or_sample": f"Mean {summary['learner_acceptance']}/5", "verification_status": "Recorded for this sample"},
        {"evidence_stream": "Teacher acceptance", "collection_method": "Eight-item 5-point Likert questionnaire", "records": summary["teacher_questionnaire_responses"], "period_or_sample": f"Mean {summary['teacher_acceptance']}/5", "verification_status": "Recorded for this sample"},
        {"evidence_stream": "System reliability", "collection_method": "Daily aggregate operational and offline-synchronization log", "records": summary["reliability_days"], "period_or_sample": f"{summary['reliability_log_start']} to {summary['reliability_log_end']}", "verification_status": "Supported for the recorded 28-day window"},
        {"evidence_stream": "Qualitative evidence", "collection_method": "Thematic summary of learner and teacher responses", "records": summary["qualitative_themes"], "period_or_sample": f"{summary['qualitative_mentions']} recorded mentions", "verification_status": "Theme counts recorded; retain source excerpts separately"},
        {"evidence_stream": "Participant assessment dates", "collection_method": "Exact dated assessment source records", "records": 0, "period_or_sample": "Dates are not present in the learner evaluation rows", "verification_status": "Not yet verified"},
        {"evidence_stream": "Six-month duration", "collection_method": "Verified dated evidence spanning at least 182 calendar days", "records": evidence["verified_evidence_log_rows"], "period_or_sample": f"Verified coverage: {evidence['verified_evaluation_coverage_days']} days", "verification_status": evidence["coverage_status"]},
    ]


def connected_research_rows(conn):
    """Combine evaluation-register and new portal evidence without overwriting either source."""
    rows = []
    for row in evaluation_dataset_rows(conn, "learner"):
        payload = row.get("payload", {}).get("learner_study") or {}
        pre_test = row.get("pre_test_pct")
        gain = row.get("gain_points")
        normalized_gain = ""
        if pre_test is not None and gain is not None and float(pre_test) < 100:
            normalized_gain = round(float(gain) / (100 - float(pre_test)), 3)
        rows.append({
            "record_source": PUBLIC_RECORD_SOURCE,
            "capture_mode": "Recorded study dataset",
            "record_type": "learner_paired_assessment",
            "participant_code": row["participant_code"],
            "study_phase": "Evaluation",
            "school_code": row.get("school_code") or "",
            "subject": row.get("subject") or "",
            "class_level": row.get("class_level") or "",
            "learning_outcome": "",
            "study_status": row.get("study_status") or "",
            "pre_test": row.get("pre_test_pct"),
            "post_test": row.get("post_test_pct"),
            "learning_gain": row.get("gain_points"),
            "normalized_gain": normalized_gain,
            "mastery_status": row.get("mastery_status") or "",
            "acceptance_score": row.get("acceptance_mean"),
            "attempts": payload.get("practice_attempts") or 0,
            "time_to_mastery": payload.get("time_to_mastery_hours") or "Not yet mastered",
            "teacher_intervention": payload.get("teacher_interventions") or 0,
            "ai_confidence": "",
            "reflection_completed": payload.get("reflection_complete") or "Not recorded",
            "practical_completed": payload.get("practical_evidence_verified") or "Not recorded",
            "captured_at": row.get("imported_at") or "",
        })
    for row in evaluation_dataset_rows(conn, "teacher"):
        rows.append({
            "record_source": PUBLIC_RECORD_SOURCE,
            "capture_mode": "Recorded study dataset",
            "record_type": "teacher_questionnaire",
            "participant_code": row["participant_code"],
            "study_phase": "Evaluation",
            "school_code": row.get("school_code") or "",
            "subject": row.get("subject") or "",
            "class_level": "",
            "learning_outcome": "",
            "study_status": row.get("study_status") or "",
            "pre_test": "",
            "post_test": "",
            "learning_gain": "",
            "normalized_gain": "",
            "mastery_status": "",
            "acceptance_score": row.get("acceptance_mean"),
            "attempts": "",
            "time_to_mastery": "",
            "teacher_intervention": "",
            "ai_confidence": "",
            "reflection_completed": "",
            "practical_completed": "",
            "captured_at": row.get("imported_at") or "",
        })
    for row in evaluation_reliability_rows(conn):
        rows.append({
            "record_source": PUBLIC_RECORD_SOURCE,
            "capture_mode": "Recorded daily aggregate",
            "record_type": "system_reliability_daily",
            "participant_code": "",
            "study_phase": "Evaluation",
            "school_code": "",
            "subject": "",
            "class_level": "",
            "learning_outcome": "Operational reliability",
            "study_status": row.get("incident_category") or "None",
            "pre_test": "", "post_test": "", "learning_gain": "", "normalized_gain": "",
            "mastery_status": "", "acceptance_score": "", "attempts": "",
            "time_to_mastery": "", "teacher_intervention": "", "ai_confidence": "",
            "reflection_completed": "", "practical_completed": "",
            "total_events": row.get("total_events"),
            "successful_events": row.get("successful_events"),
            "error_events": row.get("error_events"),
            "success_rate_pct": row.get("success_rate_pct"),
            "average_latency_ms": row.get("average_latency_ms"),
            "p95_latency_ms": row.get("p95_latency_ms"),
            "offline_queued_events": row.get("offline_queued_events"),
            "successful_sync_events": row.get("successful_sync_events"),
            "qualitative_theme": "", "mention_count": "", "interpretation": "",
            "captured_at": row.get("event_date") or "",
        })
    for row in evaluation_qualitative_theme_rows(conn):
        rows.append({
            "record_source": PUBLIC_RECORD_SOURCE,
            "capture_mode": "Recorded thematic summary",
            "record_type": "qualitative_theme",
            "participant_code": row.get("respondent_group") or "",
            "study_phase": "Evaluation",
            "school_code": "", "subject": "", "class_level": "",
            "learning_outcome": "Qualitative evaluation",
            "study_status": "Qualitative theme",
            "pre_test": "", "post_test": "", "learning_gain": "", "normalized_gain": "",
            "mastery_status": "", "acceptance_score": "", "attempts": "",
            "time_to_mastery": "", "teacher_intervention": "", "ai_confidence": "",
            "reflection_completed": "", "practical_completed": "",
            "total_events": "", "successful_events": "", "error_events": "",
            "success_rate_pct": "", "average_latency_ms": "", "p95_latency_ms": "",
            "offline_queued_events": "", "successful_sync_events": "",
            "qualitative_theme": row.get("coded_theme") or "",
            "mention_count": row.get("mention_count") or 0,
            "interpretation": row.get("interpretation") or "",
            "captured_at": row.get("imported_at") or "",
        })

    mastery_times = {
        (row["participant_code"], row["subject"], row["topic"], row["learning_outcome"]): row["time_to_mastery"]
        for row in mastery_rows(conn)
    }
    for row in learning_gain_rows(conn):
        rows.append({
            "record_source": "Learn2Master portal",
            "capture_mode": "Automatically captured",
            "record_type": "learner_paired_assessment",
            "participant_code": row["participant_code"],
            "study_phase": row.get("study_phase") or "",
            "school_code": row.get("school_code") or "",
            "subject": row.get("subject") or "",
            "class_level": row.get("class") or "",
            "learning_outcome": row.get("learning_outcome") or "",
            "study_status": "Active linked participant",
            "pre_test": row.get("pre_test"),
            "post_test": row.get("post_test"),
            "learning_gain": row.get("learning_gain"),
            "normalized_gain": row.get("normalized_gain"),
            "mastery_status": row.get("mastery_status") or "",
            "acceptance_score": "",
            "attempts": row.get("attempts") or 0,
            "time_to_mastery": mastery_times.get(
                (row["participant_code"], row["subject"], row.get("topic") or "", row["learning_outcome"]),
                "Not yet mastered",
            ),
            "teacher_intervention": row.get("teacher_intervention") or 0,
            "ai_confidence": row.get("ai_confidence") or 0,
            "reflection_completed": row.get("reflection_completed") or "No",
            "practical_completed": row.get("practical_completed") or "No",
            "captured_at": row.get("post_date") or "",
        })
    for row in live_questionnaire_response_rows(conn):
        rows.append({
            "record_source": "Learn2Master portal",
            "capture_mode": "Automatically captured",
            "record_type": f"{row['respondent_role']}_questionnaire",
            "participant_code": row["participant_code"],
            "study_phase": row.get("study_phase") or "",
            "school_code": "",
            "subject": "",
            "class_level": "",
            "learning_outcome": row.get("questionnaire_title") or "",
            "study_status": "Submitted",
            "pre_test": "",
            "post_test": "",
            "learning_gain": "",
            "normalized_gain": "",
            "mastery_status": "",
            "acceptance_score": row.get("acceptance_score"),
            "attempts": "",
            "time_to_mastery": "",
            "teacher_intervention": "",
            "ai_confidence": "",
            "reflection_completed": "",
            "practical_completed": "",
            "captured_at": row.get("submitted_at") or "",
        })
    return rows


def research_capture_links(conn, live_metrics=None):
    """Describe how operational records feed the connected research report."""
    live_metrics = live_metrics or research_metrics(conn)
    _, oversight_rows = teacher_oversight_data(conn)
    dataset_rows = evaluation_dataset_rows(conn)
    dataset_learners = [row for row in dataset_rows if row["record_type"] == "learner"]
    dataset_summary = evaluation_dataset_summary(conn)
    dataset_assessments = sum(
        int(row.get("pre_test_pct") is not None) + int(row.get("post_test_pct") is not None)
        for row in dataset_learners
    )
    dataset_interventions = sum(
        int((row.get("payload", {}).get("learner_study") or {}).get("teacher_interventions") or 0)
        for row in dataset_learners
    )
    dataset_recommendations = sum(
        int((row.get("payload", {}).get("learner_study") or {}).get("recommendations_received") or 0)
        for row in dataset_learners
    )
    dataset_acceptance = sum(1 for row in dataset_rows if row.get("acceptance_mean") is not None)
    mastery_count = one(conn, f"""
        SELECT COUNT(*) FROM mastery_records mr
        JOIN research_participants rp ON rp.user_id=mr.learner_id
             AND {ELIGIBLE_PARTICIPANT_SQL}
    """)
    unlinked_attempts = one(conn, f"""
        SELECT COUNT(*) FROM assessment_attempts aa
        WHERE NOT EXISTS (
            SELECT 1 FROM research_participants rp
            WHERE rp.user_id=aa.learner_id AND {ELIGIBLE_PARTICIPANT_SQL}
        )
    """)
    links = [
        {"stream": "Evaluation register", "system_source": "Participant, questionnaire, reliability and qualitative evidence", "count": dataset_summary["total_records"] + dataset_summary["reliability_days"] + dataset_summary["qualitative_themes"], "status": "Connected", "route": "research.supplied_evaluation"},
        {"stream": "Assessments", "system_source": "Evaluation pre/post records plus portal assessment attempts", "count": dataset_assessments + live_metrics["attempts"], "status": "Connected", "route": "research.pre_post_results"},
        {"stream": "Mastery", "system_source": "Evaluation outcomes plus portal mastery updates", "count": dataset_summary["complete_pairs"] + mastery_count, "status": "Connected", "route": "research.mastery_attainment"},
        {"stream": "Acceptance", "system_source": "Evaluation surveys plus portal questionnaires", "count": dataset_acceptance + live_metrics["questionnaire_response_count"], "status": "Connected", "route": "research.questionnaire_results"},
        {"stream": "Teacher oversight", "system_source": "Evaluation intervention counts plus portal reviews", "count": dataset_interventions + len(oversight_rows), "status": "Connected", "route": "research.teacher_oversight"},
        {"stream": "AI support", "system_source": "Evaluation recommendation follow-through plus portal explanations", "count": dataset_recommendations + live_metrics["ai_recommendations"], "status": "Connected", "route": "research.feedback_responsiveness"},
        {"stream": "Reliability", "system_source": "Evaluation daily aggregates plus portal application events", "count": dataset_summary["reliability_days"] + live_metrics["reliability_evidence_count"], "status": "Connected", "route": "research.system_reliability"},
        {"stream": "Qualitative themes", "system_source": "Recorded learner and teacher thematic summary", "count": dataset_summary["qualitative_themes"], "status": "Connected", "route": "research.evidence_verification"},
    ]
    return links, unlinked_attempts


def connected_research_summary(conn, live_metrics=None):
    """Create a transparent cross-source summary for Chapters Four and Five."""
    evaluation_register = evaluation_dataset_summary(conn)
    live_metrics = live_metrics or research_metrics(conn)
    live_gains = learning_gain_rows(conn)
    evaluation_pairs = evaluation_register["complete_pairs"]
    portal_pairs = len(live_gains)
    total_pairs = evaluation_pairs + portal_pairs

    def weighted(dataset_value, portal_value):
        if not total_pairs:
            return 0
        return round(((dataset_value * evaluation_pairs) + (portal_value * portal_pairs)) / total_pairs, 2)

    portal_improved = sum(1 for row in live_gains if row.get("learning_gain", 0) > 0)
    portal_mastered = sum(1 for row in live_gains if row.get("mastery_status") == "Mastered")
    links, unlinked_attempts = research_capture_links(conn, live_metrics)
    return {
        "evaluation_pairs": evaluation_pairs,
        "portal_pairs": portal_pairs,
        "total_paired_records": total_pairs,
        "average_pre_test": weighted(evaluation_register["average_pre_test"], live_metrics["average_pre_test"]),
        "average_post_test": weighted(evaluation_register["average_post_test"], live_metrics["average_post_test"]),
        "average_gain": weighted(evaluation_register["average_gain"], live_metrics["average_learning_gain"]),
        "improved_records": evaluation_register["improved_pairs"] + portal_improved,
        "improved_rate": percentage(evaluation_register["improved_pairs"] + portal_improved, total_pairs),
        "mastered_records": evaluation_register["mastered_records"] + portal_mastered,
        "mastery_rate": percentage(evaluation_register["mastered_records"] + portal_mastered, total_pairs),
        "evaluation_records": evaluation_register["total_records"],
        "evaluation_evidence_rows": evaluation_register["total_records"] + evaluation_register["reliability_days"] + evaluation_register["qualitative_themes"],
        "portal_participants": live_metrics["eligible_participants"],
        "portal_questionnaires": live_metrics["questionnaire_response_count"],
        "evaluation_questionnaires": evaluation_register["questionnaire_responses"],
        "total_questionnaire_responses": evaluation_register["questionnaire_responses"] + live_metrics["questionnaire_response_count"],
        "evaluation_reliability_days": evaluation_register["reliability_days"],
        "reliability_period": f"{evaluation_register['reliability_log_start']} to {evaluation_register['reliability_log_end']}",
        "six_month_status": evaluation_evidence_summary(conn)["coverage_status"],
        "portal_events": live_metrics["system_usage_count"],
        "unlinked_attempts": unlinked_attempts,
        "capture_links": links,
    }


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
    supplied_metrics = evaluation_dataset_summary(conn)
    connected_summary = connected_research_summary(conn, metrics)
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
    return render_template(
        "research/dashboard.html",
        metrics=metrics,
        supplied_metrics=supplied_metrics,
        connected_summary=connected_summary,
        weak_concepts=weak_concepts,
        chart_data=chart_data,
    )


@research_bp.route("/research/demo-evaluation")
@research_bp.route("/research/supplied-evaluation")
@role_required(*RESEARCH_ROLES)
def supplied_evaluation():
    conn = get_db()
    summary = evaluation_dataset_summary(conn)
    evidence_summary = evaluation_evidence_summary(conn)
    learners = evaluation_dataset_rows(conn, "learner")
    teachers = evaluation_dataset_rows(conn, "teacher")
    reliability = evaluation_reliability_rows(conn)
    qualitative_themes = evaluation_qualitative_theme_rows(conn)
    conn.close()
    return render_template(
        "research/supplied_evaluation.html",
        summary=summary,
        learners=learners,
        teachers=teachers,
        evidence_summary=evidence_summary,
        reliability=reliability,
        qualitative_themes=qualitative_themes,
        disclaimer=SUPPLIED_DISCLAIMER,
    )


@research_bp.route("/research/demo-evaluation/export.csv")
@research_bp.route("/research/supplied-evaluation/export.csv")
@role_required(*RESEARCH_ROLES)
def export_supplied_evaluation():
    conn = get_db()
    rows = evaluation_dataset_rows(conn)
    conn.close()
    columns = [
        ("source_label", "source_label"),
        ("record_type", "record_type"),
        ("participant_code", "participant_code"),
        ("school_code", "school_code"),
        ("subject", "subject"),
        ("class_level", "class_level"),
        ("study_status", "study_status"),
        ("pre_test_pct", "pre_test_pct"),
        ("post_test_pct", "post_test_pct"),
        ("gain_points", "gain_points"),
        ("acceptance_mean", "acceptance_mean"),
        ("mastery_status", "mastery_status"),
        ("imported_at", "imported_at"),
    ]
    return csv_response(
        "learn2master_research_evaluation_data.csv",
        columns,
        rows,
        "research_evaluation",
    )


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
    rows = connected_participant_rows(conn, filters)
    summary = connected_participant_summary(conn, rows, filters)
    options = research_filter_options(conn)
    conn.close()
    return render_table(
        "Controlled Participant Register",
        "One controlled register contains all recorded evaluation participants and new consent-linked portal participants. Every evaluation participant opens to an evidence profile showing how the record is used across the system.",
        [
            ("record_source", "Source"),
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


@research_bp.route("/research/evaluation-participants/<participant_code>")
@role_required(*RESEARCH_ROLES)
def evaluation_participant_view(participant_code):
    conn = get_db()
    participant = next(
        (
            row for row in evaluation_dataset_rows(conn)
            if row["participant_code"].lower() == participant_code.lower()
        ),
        None,
    )
    if not participant:
        conn.close()
        abort(404)

    payload = participant.get("payload") or {}
    learner = payload.get("learner_study") or {}
    learner_survey = payload.get("learner_survey") or {}
    teacher_survey = payload.get("teacher_survey") or {}
    questionnaire = learner_survey or teacher_survey
    questionnaire_items = [
        {
            "item": key.replace("_", " "),
            "score": value,
        }
        for key, value in questionnaire.items()
        if (key.startswith("LQ") or key.startswith("TQ"))
        and key not in {"LQ9_reverse_scored"}
    ]
    if participant["record_type"] == "learner":
        linked_features = [
            ("Controlled Participant Register", "research.participants"),
            ("Pre/Post Assessment Results", "research.pre_post_results"),
            ("Learning Gain", "research.learning_gain"),
            ("Mastery Attainment", "research.mastery_attainment"),
            ("Questionnaire Results", "research.questionnaire_results"),
            ("Teacher Oversight", "research.teacher_oversight"),
            ("AI Feedback Responsiveness", "research.feedback_responsiveness"),
            ("Chapter Four", "research.chapter_four_report"),
            ("Chapter Five", "research.chapter_five_insights"),
        ]
    else:
        linked_features = [
            ("Controlled Participant Register", "research.participants"),
            ("Questionnaire Results", "research.questionnaire_results"),
            ("Teacher Oversight", "research.teacher_oversight"),
            ("Chapter Four", "research.chapter_four_report"),
            ("Chapter Five", "research.chapter_five_insights"),
        ]
    conn.close()
    return render_template(
        "research/evaluation_participant_view.html",
        participant=participant,
        learner=learner,
        questionnaire_items=questionnaire_items,
        linked_features=[
            {"label": label, "url": url_for(endpoint)}
            for label, endpoint in linked_features
        ],
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
    rows = connected_assessment_rows(conn, filters=filters)
    options = research_filter_options(conn)
    conn.close()
    return render_table(
        "Pre-test and Post-test Results",
        "Recorded evaluation assessments and new portal attempts are presented together with their source. Unrecorded dates and timing remain clearly marked.",
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
    rows = connected_assessment_rows(conn, "pretest", filters)
    options = research_filter_options(conn)
    conn.close()
    return render_table("Pre-test Results", "Diagnostic pre-test results by participant and learning outcome.", assessment_columns(), rows, filters=filters, filter_options=options)


@research_bp.route("/research/post-test-results")
@role_required(*RESEARCH_ROLES)
def post_test_results():
    conn = get_db()
    filters = research_filter_values()
    rows = connected_assessment_rows(conn, "posttest", filters)
    options = research_filter_options(conn)
    conn.close()
    return render_table("Post-test Results", "Post-test mastery evidence by participant and learning outcome.", assessment_columns(), rows, filters=filters, filter_options=options)


def assessment_columns():
    return [
        ("record_source", "Source"),
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
    rows = connected_learning_gain_rows(conn, filters)
    summary = learning_gain_stats(rows)
    options = research_filter_options(conn)
    conn.close()
    return render_table(
        "Learning Gain Analysis",
        "Evaluation-register pairs and new portal pairs use the same formula: post-test percentage minus pre-test percentage. The source column prevents accidental double counting.",
        [
            ("record_source", "Source"),
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
    rows = connected_mastery_rows(conn, filters)
    participant_records = connected_participant_rows(conn, filters)
    summary = mastery_summary(
        rows,
        sum(1 for row in participant_records if row.get("role_name") == "learner"),
    )
    options = research_filter_options(conn)
    conn.close()
    return render_table(
        "Mastery Attainment Report",
        "Evidence for Objective 3 combines recorded evaluation mastery outcomes with automatically updated portal mastery records.",
        [
            ("record_source", "Source"),
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
    summary, rows = connected_teacher_oversight_data(conn)
    conn.close()
    return render_table(
        "Teacher Oversight Report",
        "Recorded evaluation intervention counts are linked with detailed approvals, overrides, feedback and reviews captured by the portal.",
        [
            ("record_source", "Source"),
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
    rows = connected_feedback_rows(conn, filters)
    summary = feedback_responsiveness_summary(rows)
    options = research_filter_options(conn)
    conn.close()
    return render_table(
        "AI Feedback Responsiveness",
        "Recorded recommendation follow-through is linked with new portal recommendation evidence. Portal follow-through still requires later practice or post-test evidence.",
        [("record_source", "Source"), ("participant_code", "Participant"), ("study_phase", "Phase"),
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
    rows = connected_reliability_rows(conn, filters)
    summary = connected_reliability_summary(conn, rows)
    conn.close()
    return render_table(
        "Connected System Reliability",
        "Recorded daily aggregates and new portal events are shown together without presenting them as a six-month uptime record.",
        [("record_source", "Source"), ("occurred_at", "Date"),
         ("evidence_level", "Evidence Level"), ("total_events", "Total Events"),
         ("successful_events", "Successful"), ("error_events", "Errors"),
         ("success_rate_pct", "Success Rate (%)"), ("average_latency_ms", "Average Latency (ms)"),
         ("p95_latency_ms", "P95 Latency (ms)"), ("offline_queued_events", "Offline Queued"),
         ("successful_sync_events", "Successful Sync"), ("incident_category", "Incident")],
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
        "Portal Data Collection Readiness",
        f"Overall status: {report['overall_status']}. This checks new portal collection; recorded evaluation evidence is documented in the Evidence Verification Register.",
        [("item", "Requirement"), ("status", "Status"), ("evidence", "Evidence / next action")],
        report["items"], report["summary"],
        [{"label": "Open Evidence Verification", "url": url_for("research.evidence_verification")}],
    )


@research_bp.route("/research/evidence-verification")
@role_required(*RESEARCH_ROLES)
def evidence_verification():
    conn = get_db()
    rows = evaluation_collection_audit_rows(conn)
    evidence = evaluation_evidence_summary(conn)
    conn.close()
    return render_table(
        "Data Collection and Evidence Verification",
        "This register answers how each result was collected, the available sample or period, and whether the evidence supports the associated claim.",
        [("evidence_stream", "Evidence Stream"), ("collection_method", "How Data Was Collected"),
         ("records", "Records"), ("period_or_sample", "Period / Sample"),
         ("verification_status", "Verification Status")],
        rows,
        {
            "verified_evidence_log_rows": evidence["verified_evidence_log_rows"],
            "verified_coverage_days": evidence["verified_evaluation_coverage_days"],
            "reliability_days": evidence["reliability_days"],
            "six_month_status": evidence["coverage_status"],
        },
        [{"label": "Open Evaluation Results", "url": url_for("research.supplied_evaluation")},
         {"label": "Open Questionnaire Results", "url": url_for("research.questionnaire_results")}],
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
    evaluation_summary = evaluation_dataset_summary(conn)
    conn.close()
    return render_template(
        "research/questionnaires.html",
        questionnaires=rows,
        evaluation_summary=evaluation_summary,
        no_data=NO_DATA,
    )


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
    rows = connected_questionnaire_rows(conn)
    dataset_summary = evaluation_dataset_summary(conn)
    portal_response_count = one(conn, "SELECT COUNT(*) FROM research_questionnaire_responses")
    summary = {
        "evaluation_learner_responses": dataset_summary["learner_questionnaire_responses"],
        "evaluation_learner_acceptance": dataset_summary["learner_acceptance"],
        "evaluation_teacher_responses": dataset_summary["teacher_questionnaire_responses"],
        "evaluation_teacher_acceptance": dataset_summary["teacher_acceptance"],
        "portal_questionnaire_responses": portal_response_count,
    }
    conn.close()
    return render_table(
        "Questionnaire Results",
        "Aggregated 5-point Likert evidence from the evaluation register and newly submitted portal questionnaires, separated by source.",
        [
            ("record_source", "Source"),
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
    evaluation_summary = evaluation_dataset_summary(conn)
    connected_summary = connected_research_summary(conn, metrics)
    weak_concepts = weak_concept_rows(conn, limit=50)
    if request.args.get("format") == "csv" or request.path.endswith("/export/csv"):
        rows = [
            {"section": "connected_research", "metric": key, "value": value}
            for key, value in connected_summary.items()
            if key != "capture_links"
        ]
        rows.extend(
            {"section": "evaluation_register", "metric": key, "value": value}
            for key, value in evaluation_summary.items()
            if key != "disclaimer"
        )
        rows.extend(
            {"section": "automatically_captured_portal", "metric": key, "value": value}
            for key, value in metrics.items()
        )
        conn.close()
        return csv_response(
            "learn2master_connected_research_report.csv",
            [("section", "section"), ("metric", "metric"), ("value", "value")],
            rows,
            "connected_research_report",
        )
    conn.close()
    return render_template(
        "research/reports.html",
        metrics=metrics,
        evaluation_summary=evaluation_summary,
        connected_summary=connected_summary,
        capture_links=connected_summary["capture_links"],
        weak_concepts=weak_concepts,
    )


@research_bp.route("/research/chapter-four-report")
@role_required(*RESEARCH_ROLES)
def chapter_four_report():
    conn = get_db()
    filters = research_filter_values()
    metrics = research_metrics(conn)
    connected_summary = connected_research_summary(conn, metrics)
    feedback_rows = connected_feedback_rows(conn, filters)
    reliability_rows = connected_reliability_rows(conn, filters)
    integrity = integrity_report(conn)
    data = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": filters,
        "supplied_summary": evaluation_dataset_summary(conn),
        "supplied_learners": evaluation_dataset_rows(conn, "learner"),
        "supplied_teachers": evaluation_dataset_rows(conn, "teacher"),
        "evidence_summary": evaluation_evidence_summary(conn),
        "qualitative_themes": evaluation_qualitative_theme_rows(conn),
        "metrics": metrics,
        "connected_summary": connected_summary,
        "capture_links": connected_summary["capture_links"],
        "participants": connected_participant_rows(conn, filters),
        "pretest": connected_assessment_rows(conn, "pretest", filters),
        "posttest": connected_assessment_rows(conn, "posttest", filters),
        "learning_gain": connected_learning_gain_rows(conn, filters),
        "mastery": connected_mastery_rows(conn, filters),
        "teacher_summary": connected_teacher_oversight_data(conn)[0],
        "feedback_rows": feedback_rows,
        "feedback_summary": feedback_responsiveness_summary(feedback_rows),
        "reliability_rows": reliability_rows,
        "reliability_summary": connected_reliability_summary(conn, reliability_rows),
        "integrity": integrity,
        "questionnaire_results": connected_questionnaire_rows(conn),
        "system_logs": system_log_rows(conn, limit=20),
        "readiness": chapter_evidence_readiness(conn),
    }
    data["gain_summary"] = learning_gain_stats(data["learning_gain"])
    data["mastery_summary"] = mastery_summary(
        data["mastery"],
        sum(1 for row in data["participants"] if row.get("role_name") == "learner"),
    )
    data["excluded_unpaired_cases"] = max(0, len(data["pretest"]) - data["gain_summary"]["valid_pairs"])
    conn.close()
    return render_template("research/chapter_four.html", no_data=NO_DATA, **data)


@research_bp.route("/research/chapter-five-insights")
@role_required(*RESEARCH_ROLES)
def chapter_five_insights():
    conn = get_db()
    metrics = research_metrics(conn)
    evaluation_summary = evaluation_dataset_summary(conn)
    connected_summary = connected_research_summary(conn, metrics)
    gains = learning_gain_rows(conn)
    weak_concepts = weak_concept_rows(conn, limit=6)
    oversight_summary, _ = teacher_oversight_data(conn)
    questionnaire_results = connected_questionnaire_rows(conn)
    qualitative_themes = evaluation_qualitative_theme_rows(conn)
    evidence_summary = evaluation_evidence_summary(conn)
    readiness = chapter_evidence_readiness(conn)
    has_data = bool(evaluation_summary["total_records"] or gains or questionnaire_results or metrics["attempts"])
    insights = []
    def add(statement, metric, source, valid_cases, scope, evidence_type="observational"):
        insights.append({"statement": statement, "metric": metric, "source": source,
                         "valid_cases": valid_cases, "scope": scope, "evidence_type": evidence_type})
    if has_data:
        if evaluation_summary["complete_pairs"]:
            add(
                f"The evaluation records show a mean increase of {evaluation_summary['average_gain']} percentage points, with {evaluation_summary['improved_pairs']} of {evaluation_summary['complete_pairs']} complete learner pairs improving.",
                evaluation_summary["average_gain"],
                evaluation_summary["source_label"],
                evaluation_summary["complete_pairs"],
                "Recorded learner evaluation",
            )
            add(
                f"Recorded acceptance scores average {evaluation_summary['learner_acceptance']}/5 for learners and {evaluation_summary['teacher_acceptance']}/5 for teachers.",
                evaluation_summary["learner_acceptance"],
                "Learner and teacher evaluation questionnaires",
                evaluation_summary["learner_records"] + evaluation_summary["teacher_records"],
                "Recorded learner and teacher acceptance evidence",
                "self-report evidence",
            )
        add(
            f"The connected research evidence currently contains {connected_summary['total_paired_records']} paired result records across the evaluation register and automatically captured portal activity.",
            connected_summary["total_paired_records"],
            "Connected research dataset",
            connected_summary["total_paired_records"],
            "Evaluation register plus consent-linked portal records",
            "connected evidence",
        )
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
        add(
            f"User-acceptance evidence includes {evaluation_summary['learner_questionnaire_responses']} learner and {evaluation_summary['teacher_questionnaire_responses']} teacher evaluation responses, plus {metrics['questionnaire_response_count']} new portal response(s).",
            evaluation_summary["questionnaire_responses"] + metrics["questionnaire_response_count"],
            "Evaluation-register and portal questionnaires",
            evaluation_summary["questionnaire_responses"] + metrics["questionnaire_response_count"],
            "Recorded learner and teacher instruments",
            "self-report evidence",
        )
        if evaluation_summary["reliability_days"]:
            add(
                f"Recorded operational evidence covers {evaluation_summary['reliability_days']} daily records from {evaluation_summary['reliability_log_start']} to {evaluation_summary['reliability_log_end']}, with {evaluation_summary['operational_success_rate']}% successful events and {evaluation_summary['offline_sync_success_rate']}% offline-sync success.",
                evaluation_summary["operational_success_rate"],
                "Evaluation system reliability",
                evaluation_summary["reliability_days"],
                "Recorded 28-day operational window",
                "operational evidence",
            )
        if qualitative_themes:
            add(
                f"The recorded qualitative summary contains {len(qualitative_themes)} themes and {sum(row['mention_count'] for row in qualitative_themes)} recorded mentions across learner and teacher groups.",
                len(qualitative_themes),
                "Evaluation qualitative themes",
                sum(row["mention_count"] for row in qualitative_themes),
                "Thematic summary; source excerpts retained separately",
                "qualitative evidence",
            )
        if not evidence_summary["six_month_duration_supported"]:
            add(
                "The current records do not verify a six-month participant evaluation because learner assessment dates are absent and the verified Evidence Log contains no rows.",
                evidence_summary["verified_evaluation_coverage_days"],
                "Evaluation evidence-verification controls",
                evidence_summary["verified_evidence_log_rows"],
                "Duration claims require at least 182 days of dated, source-linked evidence",
                "limitation",
            )
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
        evaluation_summary=evaluation_summary,
        connected_summary=connected_summary,
        qualitative_themes=qualitative_themes,
        evidence_summary=evidence_summary,
    )


@research_bp.route("/research/export/pre-post")
@role_required(*RESEARCH_ROLES)
def export_pre_post():
    conn = get_db()
    filters = research_filter_values()
    rows = connected_assessment_rows(conn, filters=filters)
    conn.close()
    return csv_response("learn2master_pre_post_results.csv", assessment_columns(), rows, "pre_post")


@research_bp.route("/research/export/learning-gain")
@role_required(*RESEARCH_ROLES)
def export_learning_gain():
    conn = get_db()
    filters = research_filter_values()
    rows = connected_learning_gain_rows(conn, filters)
    conn.close()
    columns = [
        ("record_source", "record_source"),
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
    rows = connected_mastery_rows(conn, filters)
    conn.close()
    columns = [
        ("record_source", "record_source"),
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
    rows = connected_feedback_rows(conn, research_filter_values())
    conn.close()
    columns = [(key, key) for key in (
        "record_source", "participant_code", "study_phase", "subject", "topic", "learning_outcome",
        "recommendation_id", "recommendation_type", "generated_at", "viewed_at",
        "followed_at", "response_delay_hours", "prior_score", "next_score",
        "performance_change", "response_evidence", "confidence_score",
    )]
    return csv_response("learn2master_feedback_responsiveness.csv", columns, rows, "feedback_responsiveness")


@research_bp.route("/research/export/teacher-oversight")
@role_required(*RESEARCH_ROLES)
def export_teacher_oversight():
    conn = get_db()
    _, rows = connected_teacher_oversight_data(conn)
    conn.close()
    columns = [(key, key) for key in (
        "record_source", "record_type", "participant_code", "learning_outcome", "action",
        "comment", "details", "created_at",
    )]
    return csv_response("learn2master_teacher_oversight.csv", columns, rows, "teacher_oversight")


@research_bp.route("/research/export/system-reliability")
@role_required(*RESEARCH_ROLES)
def export_system_reliability():
    conn = get_db()
    rows = connected_reliability_rows(conn, research_filter_values())
    conn.close()
    columns = [(key, key) for key in (
        "record_source", "evidence_level", "occurred_at", "total_events",
        "successful_events", "error_events", "success_rate_pct", "average_latency_ms",
        "p95_latency_ms", "offline_queued_events", "successful_sync_events", "incident_category",
    )]
    return csv_response("learn2master_system_reliability.csv", columns, rows, "system_reliability")


@research_bp.route("/research/export/questionnaires")
@role_required(*RESEARCH_ROLES)
def export_questionnaires():
    conn = get_db()
    rows = connected_questionnaire_rows(conn)
    conn.close()
    columns = [
        ("record_source", "record_source"),
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
    rows = connected_research_rows(conn)
    conn.close()
    columns = [
        ("record_source", "record_source"),
        ("capture_mode", "capture_mode"),
        ("record_type", "record_type"),
        ("participant_code", "participant_code"),
        ("study_phase", "study_phase"),
        ("school_code", "school_code"),
        ("subject", "subject"),
        ("class_level", "class_level"),
        ("learning_outcome", "learning_outcome"),
        ("study_status", "study_status"),
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
        ("acceptance_score", "acceptance_score"),
        ("total_events", "total_events"),
        ("successful_events", "successful_events"),
        ("error_events", "error_events"),
        ("success_rate_pct", "success_rate_pct"),
        ("average_latency_ms", "average_latency_ms"),
        ("p95_latency_ms", "p95_latency_ms"),
        ("offline_queued_events", "offline_queued_events"),
        ("successful_sync_events", "successful_sync_events"),
        ("qualitative_theme", "qualitative_theme"),
        ("mention_count", "mention_count"),
        ("interpretation", "interpretation"),
        ("captured_at", "captured_at"),
    ]
    return csv_response("learn2master_connected_research_dataset.csv", columns, rows, "connected_full_dataset")
