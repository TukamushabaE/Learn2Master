import csv
import io
import math
from datetime import datetime

from flask import Blueprint, Response, flash, redirect, render_template, request, session, url_for

from database import DatabaseIntegrityError, get_db
from routes.guards import role_required
from security import csrf_protect

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
    writer.writerow([label for _, label in columns])
    for row in rows:
        writer.writerow([row.get(key, "") for key, _ in columns])
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def participant_rows(conn):
    return [row_dict(row) for row in conn.execute("""
        SELECT rp.id, rp.participant_code, rp.user_id, roles.role_name,
               rp.study_phase, rp.consent_status, rp.assent_status,
               rp.parent_consent_status, rp.active_status, rp.created_at,
               schools.school_name, classes.class_name, subjects.subject_name
        FROM research_participants rp
        LEFT JOIN users ON users.user_id=rp.user_id
        LEFT JOIN roles ON roles.role_id=users.role_id
        LEFT JOIN schools ON schools.school_id=rp.school_id
        LEFT JOIN classes ON classes.class_id=rp.class_id
        LEFT JOIN subjects ON subjects.subject_id=rp.subject_id
        ORDER BY rp.participant_code
    """).fetchall()]


def participant_summary(conn):
    rows = participant_rows(conn)
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


def assessment_result_rows(conn, assessment_type=None):
    params = []
    where = "WHERE assessments.assessment_type IN ('pretest','posttest')"
    if assessment_type:
        where = "WHERE assessments.assessment_type = ?"
        params.append(assessment_type)

    rows = conn.execute(f"""
        SELECT rp.participant_code,
               users.user_id AS learner_id,
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


def learning_gain_rows(conn):
    rows = conn.execute(f"""
        SELECT rp.participant_code,
               users.user_id AS learner_id,
               subjects.subject_name AS subject,
               topics.topic_title AS topic,
               lo.outcome_name AS learning_outcome,
               mastery_records.pretest_score,
               mastery_records.posttest_score,
               mastery_records.mastery_status,
               mastery_records.mastery_score,
               mastery_records.updated_at,
               (
                    SELECT COUNT(*)
                    FROM assessment_attempts aa
                    JOIN assessments a ON a.assessment_id=aa.assessment_id
                    JOIN lessons l ON l.lesson_id=a.lesson_id
                    WHERE aa.learner_id=mastery_records.learner_id
                      AND l.outcome_id=mastery_records.outcome_id
               ) AS attempts,
               (
                    SELECT ROUND(CAST(AVG(confidence_score) AS NUMERIC),1)
                    FROM ai_explanations ax
                    WHERE ax.learner_id=mastery_records.learner_id
                      AND ax.outcome_id=mastery_records.outcome_id
               ) AS ai_confidence,
               (
                    SELECT COUNT(*)
                    FROM learning_reflections lr
                    WHERE lr.learner_id=mastery_records.learner_id
                      AND lr.outcome_id=mastery_records.outcome_id
               ) AS reflection_count,
               (
                    SELECT COUNT(*)
                    FROM practical_evidence pe
                    WHERE pe.learner_id=mastery_records.learner_id
                      AND pe.outcome_id=mastery_records.outcome_id
               ) AS practical_count,
               (
                    SELECT COUNT(*)
                    FROM teacher_interventions ti
                    WHERE ti.learner_id=mastery_records.learner_id
                      AND ti.outcome_id=mastery_records.outcome_id
               ) AS teacher_intervention_count
        FROM mastery_records
        JOIN users ON users.user_id=mastery_records.learner_id
        JOIN research_participants rp ON rp.user_id=users.user_id
             AND {ELIGIBLE_PARTICIPANT_SQL}
        JOIN learning_outcomes lo ON lo.outcome_id=mastery_records.outcome_id
        JOIN competencies ON competencies.competency_id=lo.competency_id
        JOIN subjects ON subjects.subject_id=competencies.subject_id
        LEFT JOIN topics ON topics.topic_id=lo.topic_id
        WHERE mastery_records.pretest_score > 0 OR mastery_records.posttest_score > 0
        ORDER BY participant_code, subjects.subject_name, lo.sequence_order
    """).fetchall()

    results = []
    for row in rows:
        pre = safe_round(row["pretest_score"])
        post = safe_round(row["posttest_score"])
        gain = round(post - pre, 1)
        normalized_gain = round((post - pre) / (100 - pre), 3) if pre < 100 else None
        improvement = round(((post - pre) / pre) * 100, 1) if pre > 0 else None
        results.append({
            "participant_code": row["participant_code"],
            "learner_id": row["learner_id"],
            "subject": row["subject"],
            "topic": row["topic"] or "",
            "learning_outcome": row["learning_outcome"],
            "pre_test": pre,
            "post_test": post,
            "learning_gain": gain,
            "normalized_gain": normalized_gain if normalized_gain is not None else "Not applicable",
            "percentage_improvement": improvement if improvement is not None else "Not applicable",
            "mastery_status": row["mastery_status"],
            "mastery_score": safe_round(row["mastery_score"]),
            "attempts": row["attempts"] or 0,
            "ai_confidence": safe_round(row["ai_confidence"]),
            "reflection_completed": "Yes" if row["reflection_count"] else "No",
            "practical_completed": "Yes" if row["practical_count"] else "No",
            "teacher_intervention": row["teacher_intervention_count"] or 0,
            "updated_at": fmt_datetime(row["updated_at"]),
        })
    return results


def learning_gain_stats(rows):
    gains = [row["learning_gain"] for row in rows]
    pre = [row["pre_test"] for row in rows]
    post = [row["post_test"] for row in rows]
    return {
        "average_pre_test": safe_round(sum(pre) / len(pre) if pre else 0),
        "average_post_test": safe_round(sum(post) / len(post) if post else 0),
        "average_gain": safe_round(sum(gains) / len(gains) if gains else 0),
        "highest_gain": max(gains) if gains else 0,
        "lowest_gain": min(gains) if gains else 0,
        "standard_deviation": population_stddev(gains),
        "variance": population_variance(gains),
    }


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


def mastery_rows(conn):
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
        ORDER BY participant_code, subjects.subject_name, lo.sequence_order
    """).fetchall()

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
               q.questionnaire_description, q.created_at,
               COUNT(DISTINCT qi.id) AS item_count,
               COUNT(DISTINCT qr.id) AS response_count
        FROM research_questionnaires q
        LEFT JOIN research_questionnaire_items qi ON qi.questionnaire_id=q.id
        LEFT JOIN research_questionnaire_responses qr ON qr.questionnaire_id=q.id
        GROUP BY q.id, q.questionnaire_title, q.respondent_role, q.active_status,
                 q.questionnaire_description, q.created_at
        ORDER BY q.respondent_role, q.questionnaire_title
    """).fetchall()]


def questionnaire_result_rows(conn):
    return [row_dict(row) for row in conn.execute(f"""
        SELECT q.questionnaire_title,
               q.respondent_role,
               qi.construct_name,
               ROUND(CAST(AVG(a.score) AS NUMERIC), 2) AS average_score,
               COUNT(DISTINCT r.id) AS responses,
               COUNT(a.id) AS answers
        FROM research_questionnaire_answers a
        JOIN research_questionnaire_responses r ON r.id=a.response_id
        JOIN research_participants rp ON (rp.id=r.participant_id OR (r.participant_id IS NULL AND rp.user_id=r.respondent_user_id))
             AND {ELIGIBLE_PARTICIPANT_SQL}
        JOIN research_questionnaire_items qi ON qi.id=a.item_id
        JOIN research_questionnaires q ON q.id=qi.questionnaire_id
        GROUP BY q.questionnaire_title, q.respondent_role, qi.construct_name
        ORDER BY q.respondent_role, q.questionnaire_title, qi.construct_name
    """).fetchall()]


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
    rows = audit_rows + activity_rows
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
    }
    metrics["avg_pretest"] = metrics["average_pre_test"]
    metrics["avg_posttest"] = metrics["average_post_test"]
    metrics["learning_gain"] = metrics["average_learning_gain"]
    metrics["mastery_rate"] = metrics["mastery_attainment_rate"]
    metrics["time_to_mastery_hours"] = metrics["average_time_to_mastery"]
    metrics["teacher_interventions"] = metrics["teacher_intervention_count"]
    return metrics


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


def render_table(title, subtitle, columns, rows, summary=None, actions=None, chart=None):
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


@research_bp.route("/research/participants")
@role_required(*RESEARCH_ROLES)
def participants():
    conn = get_db()
    rows = participant_rows(conn)
    summary = participant_summary(conn)
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
        ],
        rows,
        summary,
        [{"label": "Create Participant", "url": url_for("research.create_participant")}],
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
                request.form.get("parent_consent_status") or "Pending",
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
    return render_template("research/participant_form.html", **options)


@research_bp.route("/research/pre-post-results")
@role_required(*RESEARCH_ROLES)
def pre_post_results():
    conn = get_db()
    rows = assessment_result_rows(conn)
    conn.close()
    return render_table(
        "Pre-test and Post-test Results",
        "Operational assessment attempts are reused; missing start time and time spent are shown as not recorded.",
        assessment_columns(),
        rows,
        actions=[{"label": "Export Pre/Post CSV", "url": url_for("research.export_pre_post")}],
    )


@research_bp.route("/research/pre-test-results")
@role_required(*RESEARCH_ROLES)
def pre_test_results():
    conn = get_db()
    rows = assessment_result_rows(conn, "pretest")
    conn.close()
    return render_table("Pre-test Results", "Diagnostic pre-test results by participant and learning outcome.", assessment_columns(), rows)


@research_bp.route("/research/post-test-results")
@role_required(*RESEARCH_ROLES)
def post_test_results():
    conn = get_db()
    rows = assessment_result_rows(conn, "posttest")
    conn.close()
    return render_table("Post-test Results", "Post-test mastery evidence by participant and learning outcome.", assessment_columns(), rows)


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
    rows = learning_gain_rows(conn)
    summary = learning_gain_stats(rows)
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
        [{"label": "Export Learning Gain", "url": url_for("research.export_learning_gain")}],
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
    )


@research_bp.route("/research/mastery-attainment")
@role_required(*RESEARCH_ROLES)
def mastery_attainment():
    conn = get_db()
    rows = mastery_rows(conn)
    summary = mastery_summary(rows, participant_summary(conn)["eligible_learners"])
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
        [{"label": "Export Mastery", "url": url_for("research.export_mastery")}],
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
    return render_template("research/questionnaire_form.html")


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
            SELECT id FROM research_questionnaire_responses
            WHERE questionnaire_id=? AND respondent_user_id=?
        """, (questionnaire_id, session.get("user_id"))).fetchone()
        if existing:
            response_id = existing["id"]
            conn.execute("UPDATE research_questionnaire_responses SET submitted_at=CURRENT_TIMESTAMP WHERE id=?", (response_id,))
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
            ("responses", "Responses"),
            ("answers", "Answers"),
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
    data = {
        "metrics": research_metrics(conn),
        "participants": participant_rows(conn),
        "pretest": assessment_result_rows(conn, "pretest"),
        "posttest": assessment_result_rows(conn, "posttest"),
        "learning_gain": learning_gain_rows(conn),
        "mastery": mastery_rows(conn),
        "teacher_summary": teacher_oversight_data(conn)[0],
        "questionnaire_results": questionnaire_result_rows(conn),
        "system_logs": system_log_rows(conn, limit=20),
    }
    data["gain_summary"] = learning_gain_stats(data["learning_gain"])
    data["mastery_summary"] = mastery_summary(
        data["mastery"],
        participant_summary(conn)["eligible_learners"],
    )
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
    has_data = bool(gains or questionnaire_results or metrics["attempts"])
    insights = []
    if has_data:
        if metrics["average_learning_gain"] > 0:
            insights.append(f"Learning improved by an average gain of {metrics['average_learning_gain']} percentage points.")
        else:
            insights.append("Learning gain is not yet positive or there is insufficient paired pre/post evidence.")
        insights.append(f"Mastery attainment currently stands at {metrics['mastery_attainment_rate']}%.")
        if weak_concepts:
            concepts = ", ".join(row["concept_tag"].replace("_", " ") for row in weak_concepts[:3])
            insights.append(f"The most difficult concepts currently appear to be: {concepts}.")
        insights.append(f"AI support is represented by {metrics['ai_recommendations']} recommendation records and average confidence of {metrics['avg_ai_confidence']}%.")
        insights.append(f"Teacher oversight contributed {oversight_summary['number_of_interventions']} interventions, {oversight_summary['teacher_approvals']} approvals and {oversight_summary['teacher_overrides']} overrides.")
        if metrics["questionnaire_response_count"]:
            insights.append(f"User acceptance evidence includes {metrics['questionnaire_response_count']} questionnaire response(s).")
        else:
            insights.append("Usability evidence is pending questionnaire responses.")
        if metrics["sync_success_rate"] == NO_DATA:
            insights.append("System reliability evidence is not yet available because no synchronization outcomes have been recorded.")
        else:
            insights.append(
                f"Recorded low-connectivity synchronization succeeded for {metrics['sync_success_rate']}% of observed items, "
                f"with {metrics['recorded_system_incidents']} recorded failure incident(s)."
            )
        insights.append("Current limitations include legacy assessment attempts without exact start times and the absence of external hosting uptime measurements in the local database.")
        insights.append("Recommended improvements include expanding pilot participants, collecting questionnaire responses, and combining the research logs with production-host uptime monitoring.")
    conn.close()
    return render_template("research/chapter_five.html", has_data=has_data, insights=insights)


@research_bp.route("/research/export/pre-post")
@role_required(*RESEARCH_ROLES)
def export_pre_post():
    conn = get_db()
    rows = assessment_result_rows(conn)
    conn.close()
    return csv_response("learn2master_pre_post_results.csv", assessment_columns(), rows, "pre_post")


@research_bp.route("/research/export/learning-gain")
@role_required(*RESEARCH_ROLES)
def export_learning_gain():
    conn = get_db()
    rows = learning_gain_rows(conn)
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
        ("percentage_improvement", "percentage_improvement"),
        ("mastery_status", "mastery_status"),
    ]
    return csv_response("learn2master_learning_gain.csv", columns, rows, "learning_gain")


@research_bp.route("/research/export/mastery")
@role_required(*RESEARCH_ROLES)
def export_mastery():
    conn = get_db()
    rows = mastery_rows(conn)
    conn.close()
    columns = [
        ("participant_code", "participant_code"),
        ("subject", "subject"),
        ("topic", "topic"),
        ("learning_outcome", "learning_outcome"),
        ("mastery_status", "mastery_status"),
        ("mastery_level", "mastery_level"),
        ("mastery_score", "mastery_score"),
        ("attempts", "attempts"),
        ("time_to_mastery", "time_to_mastery"),
    ]
    return csv_response("learn2master_mastery.csv", columns, rows, "mastery")


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
        ("responses", "responses"),
        ("answers", "answers"),
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
