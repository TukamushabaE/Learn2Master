from flask import Blueprint, render_template, session

from database import get_db
from routes.guards import role_required

ai_bp = Blueprint("ai", __name__)


@ai_bp.route("/ai/explanations")
@role_required("learner", "teacher", "school_admin", "super_admin")
def explanations():
    conn = get_db()
    params = []
    where = ""
    if session.get("role") == "learner":
        where = "WHERE ai.learner_id = ?"
        params.append(session["user_id"])
    rows = conn.execute(f"""
        SELECT ai.*, learner.full_name AS learner_name, lo.outcome_code, lo.outcome_name,
               subjects.subject_name
        FROM ai_explanations ai
        JOIN users learner ON learner.user_id = ai.learner_id
        JOIN learning_outcomes lo ON lo.outcome_id = ai.outcome_id
        JOIN competencies c ON c.competency_id = lo.competency_id
        JOIN subjects ON subjects.subject_id = c.subject_id
        {where}
        ORDER BY ai.created_at DESC
        LIMIT 80
    """, params).fetchall()
    conn.close()
    return render_template("ai/explanations.html", rows=rows)


@ai_bp.route("/learner/ai-coach")
@role_required("learner")
def learner_ai_coach():
    learner_id = session["user_id"]
    conn = get_db()
    recommendations = conn.execute("""
        SELECT recommendations.*, lo.outcome_code, lo.outcome_name, subjects.subject_name
        FROM recommendations
        JOIN learning_outcomes lo ON lo.outcome_id = recommendations.outcome_id
        JOIN competencies c ON c.competency_id = lo.competency_id
        JOIN subjects ON subjects.subject_id = c.subject_id
        WHERE recommendations.learner_id = ?
        ORDER BY recommendations.created_at DESC
        LIMIT 20
    """, (learner_id,)).fetchall()
    bkt = conn.execute("""
        SELECT bkt_mastery.*, lo.outcome_code, lo.outcome_name
        FROM bkt_mastery
        JOIN learning_outcomes lo ON lo.outcome_id = bkt_mastery.outcome_id
        WHERE bkt_mastery.learner_id = ?
        ORDER BY bkt_mastery.probability_mastery ASC, bkt_mastery.updated_at DESC
        LIMIT 20
    """, (learner_id,)).fetchall()
    explanations = conn.execute("""
        SELECT ai.*, lo.outcome_code, lo.outcome_name
        FROM ai_explanations ai
        JOIN learning_outcomes lo ON lo.outcome_id = ai.outcome_id
        WHERE ai.learner_id = ?
        ORDER BY ai.created_at DESC
        LIMIT 10
    """, (learner_id,)).fetchall()
    conn.close()
    return render_template("ai/learner_coach.html", recommendations=recommendations, bkt=bkt, explanations=explanations)
