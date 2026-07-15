"""Evaluation reports that use operational evidence without exposing identities."""

import statistics
from datetime import datetime


ELIGIBLE = """
rp.active_status='Active' AND rp.consent_status='Granted'
AND rp.assent_status IN ('Granted','Not Applicable')
AND rp.parent_consent_status IN ('Granted','Not Applicable')
"""


def _dict(row):
    return {key: row[key] for key in row.keys()}


def _dt(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("T", " ").split("+")[0])
    except ValueError:
        return None


def feedback_responsiveness_rows(conn, filters=None):
    filters = filters or {}
    clauses = []
    params = []
    mapping = {
        "study_phase": "rp.study_phase", "school_id": "rp.school_id",
        "class_id": "rp.class_id", "subject_id": "s.subject_id",
        "topic_id": "lo.topic_id", "outcome_id": "lo.outcome_id",
    }
    for key, column in mapping.items():
        if filters.get(key) not in (None, ""):
            clauses.append(f"{column}=?")
            params.append(filters[key])
    if filters.get("date_from"):
        clauses.append("r.created_at >= ?")
        params.append(filters["date_from"])
    if filters.get("date_to"):
        clauses.append("r.created_at < ?")
        params.append(filters["date_to"] + " 23:59:59")
    where = " AND " + " AND ".join(clauses) if clauses else ""
    rows = conn.execute(f"""
        SELECT rp.participant_code, rp.study_phase, s.subject_name AS subject,
               t.topic_title AS topic, lo.outcome_name AS learning_outcome,
               r.recommendation_id, r.created_at AS generated_at, r.viewed_at,
               r.first_response_at, r.followed_at, r.response_evidence,
               r.confidence_score, r.recommendation_type,
               (SELECT aa.score FROM assessment_attempts aa
                JOIN assessments a ON a.assessment_id=aa.assessment_id
                JOIN lessons l ON l.lesson_id=a.lesson_id
                WHERE aa.learner_id=r.learner_id AND l.outcome_id=r.outcome_id
                  AND COALESCE(aa.completed_at,aa.attempted_at) <= r.created_at
                ORDER BY COALESCE(aa.completed_at,aa.attempted_at) DESC LIMIT 1) AS prior_score,
               (SELECT aa.score FROM assessment_attempts aa
                JOIN assessments a ON a.assessment_id=aa.assessment_id
                JOIN lessons l ON l.lesson_id=a.lesson_id
                WHERE aa.learner_id=r.learner_id AND l.outcome_id=r.outcome_id
                  AND a.assessment_type IN ('practice','posttest')
                  AND COALESCE(aa.completed_at,aa.attempted_at) > r.created_at
                ORDER BY COALESCE(aa.completed_at,aa.attempted_at) ASC LIMIT 1) AS next_score
        FROM recommendations r
        JOIN research_participants rp ON rp.user_id=r.learner_id AND {ELIGIBLE}
        JOIN learning_outcomes lo ON lo.outcome_id=r.outcome_id
        JOIN competencies c ON c.competency_id=lo.competency_id
        JOIN subjects s ON s.subject_id=c.subject_id
        LEFT JOIN topics t ON t.topic_id=lo.topic_id
        WHERE 1=1 {where}
        ORDER BY r.created_at DESC, r.recommendation_id DESC
    """, params).fetchall()
    result = []
    for raw in rows:
        row = _dict(raw)
        generated, responded = _dt(row["generated_at"]), _dt(row["first_response_at"] or row["followed_at"])
        row["viewed"] = "Yes" if row["viewed_at"] else "No"
        row["followed"] = "Yes" if row["followed_at"] else "No"
        row["response_delay_hours"] = round((responded-generated).total_seconds()/3600, 2) if generated and responded and responded >= generated else ""
        prior, after = row.get("prior_score"), row.get("next_score")
        row["performance_change"] = round(float(after)-float(prior), 2) if prior is not None and after is not None else ""
        result.append(row)
    return result


def feedback_responsiveness_summary(rows):
    delays = [float(row["response_delay_hours"]) for row in rows if row.get("response_delay_hours") not in (None, "")]
    followed = sum(1 for row in rows if row.get("followed") == "Yes")
    viewed = sum(1 for row in rows if row.get("viewed") == "Yes")
    return {
        "recommendations_generated": len(rows),
        "recommendations_viewed": viewed,
        "recommendations_followed": followed,
        "follow_through_rate": round(followed/len(rows)*100, 1) if rows else 0,
        "average_response_delay_hours": round(statistics.mean(delays), 2) if delays else "No data yet.",
        "median_response_delay_hours": round(statistics.median(delays), 2) if delays else "No data yet.",
        "unresolved_recommendations": len(rows)-followed,
    }


def reliability_rows(conn, filters=None):
    filters = filters or {}
    clauses, params = [], []
    if filters.get("date_from"):
        clauses.append("occurred_at >= ?")
        params.append(filters["date_from"])
    if filters.get("date_to"):
        clauses.append("occurred_at < ?")
        params.append(filters["date_to"] + " 23:59:59")
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    return [_dict(row) for row in conn.execute(f"""
        SELECT event_id, actor_role, event_type, entity_type, entity_id,
               response_time_ms, event_status, error_category, offline_status,
               occurred_at
        FROM research_events {where}
        ORDER BY occurred_at DESC, event_id DESC
    """, params).fetchall()]


def reliability_summary(rows):
    durations = [float(row["response_time_ms"]) for row in rows if row.get("response_time_ms") is not None]
    succeeded = sum(1 for row in rows if str(row.get("event_status") or "").lower() == "success")
    failed = sum(1 for row in rows if str(row.get("event_status") or "").lower() == "failure")
    timed = succeeded + failed
    incomplete = sum(1 for row in rows if str(row.get("event_status") or "").lower() not in ("success", "failure"))
    return {
        "recorded_events": len(rows),
        "successful_events": succeeded,
        "failed_events": failed,
        "recorded_success_rate": round(succeeded/timed*100, 1) if timed else "No data yet.",
        "average_response_time_ms": round(statistics.mean(durations), 1) if durations else "No data yet.",
        "median_response_time_ms": round(statistics.median(durations), 1) if durations else "No data yet.",
        "incomplete_events": incomplete,
        "application_errors": sum(1 for row in rows if row.get("error_category") == "application_error"),
        "offline_or_queued_events": sum(1 for row in rows if str(row.get("offline_status") or "").lower() not in ("", "online")),
        "scope_note": "Recorded application events only; this is not an external uptime percentage.",
    }


TRACEABILITY = [
    ("RQ1 / Objective 1", "How can CBC outcomes be represented as a mastery sequence?", "Design and development", "Curriculum configuration", "subjects → competencies → learning_outcomes → lessons", "/admin/subjects", "Chapter 4 curriculum configuration", "Chapter 5 design interpretation"),
    ("RQ2 / Objective 2", "How does adaptive feedback respond to diagnosed weakness?", "Demonstration", "AI recommendation generated, viewed and followed", "assessment_attempts + recommendations + research_events", "/research/feedback-responsiveness", "Chapter 4 feedback responsiveness", "Chapter 5 cautious adaptive-feedback interpretation"),
    ("RQ3 / Objective 3", "What learning gain and mastery are observed?", "Evaluation", "Valid paired pre/post by learner, outcome and phase", "assessment_attempts + mastery_records", "/research/learning-gain", "Chapter 4 paired outcomes and mastery", "Chapter 5 outcome interpretation"),
    ("RQ4 / Objective 4", "How do teachers oversee mastery decisions?", "Evaluation", "Interventions, reviews, approvals and overrides", "teacher_interventions + teacher_feedback + mastery_reviews", "/research/teacher-oversight", "Chapter 4 teacher oversight", "Chapter 5 oversight interpretation"),
    ("RQ5 / Objective 5", "Is the framework acceptable and operationally dependable?", "Evaluation and communication", "Likert responses and recorded application events", "research_questionnaire_* + research_events", "/research/questionnaire-results", "Chapter 4 questionnaire and reliability evidence", "Chapter 5 usability and limitation interpretation"),
]


def traceability_rows():
    keys = ("objective", "research_question", "dsrm_stage", "operational_measure", "database_evidence", "application_route", "chapter_four", "chapter_five")
    return [dict(zip(keys, row), status="Implemented") for row in TRACEABILITY]
