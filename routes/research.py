import csv
import io

from flask import Blueprint, Response, render_template, request
from routes.guards import role_required
from database import get_db

research_bp = Blueprint("research", __name__)


def one(conn, sql, params=()):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row and row[0] is not None else 0


def research_metrics(conn):
    metrics = {
        "learners": one(conn, "SELECT COUNT(*) FROM users JOIN roles ON users.role_id=roles.role_id WHERE roles.role_name='learner'"),
        "attempts": one(conn, "SELECT COUNT(*) FROM assessment_attempts"),
        "mastery_records": one(conn, "SELECT COUNT(*) FROM mastery_records"),
        "mastered": one(conn, "SELECT COUNT(*) FROM mastery_records WHERE mastery_status='Mastered'"),
        "avg_pretest": one(conn, "SELECT ROUND(AVG(pretest_score),1) FROM mastery_records"),
        "avg_posttest": one(conn, "SELECT ROUND(AVG(posttest_score),1) FROM mastery_records"),
        "avg_mastery": one(conn, "SELECT ROUND(AVG(mastery_score),1) FROM mastery_records"),
        "teacher_interventions": one(conn, "SELECT COUNT(*) FROM teacher_interventions"),
        "ai_recommendations": one(conn, "SELECT COUNT(*) FROM recommendations"),
        "reflections": one(conn, "SELECT COUNT(*) FROM learning_reflections"),
        "practical_evidence": one(conn, "SELECT COUNT(*) FROM practical_evidence"),
        "approved_practical": one(conn, "SELECT COUNT(*) FROM practical_evidence WHERE teacher_status='Approved'"),
        "bkt_observations": one(conn, "SELECT COALESCE(SUM(observations),0) FROM bkt_mastery"),
        "avg_bkt_mastery": one(conn, "SELECT ROUND(AVG(probability_mastery)*100,1) FROM bkt_mastery"),
        "offline_pending": one(conn, "SELECT COUNT(*) FROM offline_sync_queue WHERE sync_status='Pending'"),
        "offline_synced": one(conn, "SELECT COUNT(*) FROM sync_queue WHERE sync_status='Synced'"),
        "offline_failed": one(conn, "SELECT COUNT(*) FROM sync_queue WHERE sync_status='Failed'"),
        "cached_resources": one(conn, "SELECT COUNT(*) FROM cached_resources WHERE cache_status='Cached'"),
        "avg_attempts_to_mastery": one(conn, """
            SELECT ROUND(AVG(attempt_count),1)
            FROM (
                SELECT mr.learner_id, mr.outcome_id, COUNT(aa.attempt_id) AS attempt_count
                FROM mastery_records mr
                JOIN lessons l ON l.outcome_id=mr.outcome_id
                JOIN assessments a ON a.lesson_id=l.lesson_id
                LEFT JOIN assessment_attempts aa ON aa.assessment_id=a.assessment_id AND aa.learner_id=mr.learner_id
                WHERE mr.mastery_status='Mastered'
                GROUP BY mr.learner_id, mr.outcome_id
            )
        """),
        "teacher_approval_rate": one(conn, """
            SELECT ROUND(100.0 * SUM(CASE WHEN decision IN ('Teacher Approved','Teacher Override') THEN 1 ELSE 0 END) / COUNT(*), 1)
            FROM teacher_mastery_reviews
        """),
        "avg_ai_confidence": one(conn, "SELECT ROUND(AVG(confidence_score),1) FROM ai_explanations"),
        "time_to_mastery_hours": one(conn, """
            SELECT ROUND(AVG((julianday(mr.updated_at) - julianday(first_attempt.first_attempt_at)) * 24), 1)
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
        """),
        "feedback_response_hours": one(conn, """
            SELECT ROUND(AVG((julianday(reviewed_at) - julianday(created_at)) * 24), 1)
            FROM practical_evidence
            WHERE reviewed_at IS NOT NULL
        """),
        "system_usage": one(conn, """
            SELECT
                (SELECT COUNT(*) FROM activity_logs) +
                (SELECT COUNT(*) FROM assessment_attempts) +
                (SELECT COUNT(*) FROM recommendations) +
                (SELECT COUNT(*) FROM practical_evidence) +
                (SELECT COUNT(*) FROM activity_submissions)
        """),
    }
    metrics["learning_gain"] = round(float(metrics["avg_posttest"] or 0) - float(metrics["avg_pretest"] or 0), 1)
    metrics["mastery_rate"] = round((metrics["mastered"] / metrics["mastery_records"] * 100), 1) if metrics["mastery_records"] else 0
    required_evidence = max(1, metrics["learners"] * one(conn, "SELECT COUNT(*) FROM learning_outcomes"))
    completed_evidence = metrics["reflections"] + metrics["practical_evidence"]
    metrics["evidence_completion_rate"] = round((completed_evidence / required_evidence) * 100, 1) if required_evidence else 0
    metrics["practical_evidence_approval_rate"] = round(
        (metrics["approved_practical"] / metrics["practical_evidence"] * 100), 1
    ) if metrics["practical_evidence"] else 0
    metrics["reflection_completion_rate"] = round(
        (metrics["reflections"] / required_evidence * 100), 1
    ) if required_evidence else 0
    total_sync = metrics["offline_synced"] + metrics["offline_failed"] + metrics["offline_pending"]
    metrics["offline_sync_success_rate"] = round(
        (metrics["offline_synced"] / total_sync * 100), 1
    ) if total_sync else 0
    return metrics


@research_bp.route("/research-dashboard")
@research_bp.route("/research/dashboard")
@role_required("school_admin", "super_admin", "teacher")
def research_dashboard():
    conn = get_db()
    metrics = research_metrics(conn)
    weak_concepts = conn.execute("""
        SELECT concept_tag, ROUND(AVG(latest_score),1) AS avg_score, COUNT(*) AS evidence
        FROM concept_mastery
        GROUP BY concept_tag
        ORDER BY avg_score ASC
        LIMIT 8
    """).fetchall()
    conn.close()
    return render_template("research/dashboard.html", metrics=metrics, weak_concepts=weak_concepts)


@research_bp.route("/research/reports")
@research_bp.route("/research/export/csv")
@role_required("school_admin", "super_admin", "teacher")
def research_reports():
    conn = get_db()
    metrics = research_metrics(conn)
    weak_concepts = conn.execute("""
        SELECT concept_tag, ROUND(AVG(latest_score),1) AS avg_score, COUNT(*) AS evidence
        FROM concept_mastery
        GROUP BY concept_tag
        ORDER BY avg_score ASC
    """).fetchall()
    if request.args.get("format") == "csv" or request.path.endswith("/export/csv"):
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["metric", "value"])
        for key, value in metrics.items():
            writer.writerow([key, value])
        writer.writerow([])
        writer.writerow(["weak_concept", "average_score", "evidence_records"])
        for row in weak_concepts:
            writer.writerow([row["concept_tag"], row["avg_score"], row["evidence"]])
        conn.close()
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=learn2master_research_report.csv"},
        )
    conn.close()
    return render_template("research/reports.html", metrics=metrics, weak_concepts=weak_concepts)
