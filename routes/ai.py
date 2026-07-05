from flask import Blueprint, render_template, session, request, jsonify
from database import get_db
from routes.guards import role_required, login_required
from engine import AIEngine
from extensions import limiter
import json

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

@ai_bp.route("/ai/tutor", methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def ai_tutor():
    user_input = request.json.get("message", "")
    learner_id = session.get("user_id")

    if not user_input or len(user_input) > 1000:
        return jsonify({"response": "Please provide a valid question (max 1000 chars)."}), 400

    conn = get_db()

    mastery_records = conn.execute("""
        SELECT mr.knowledge_level, lo.outcome_name
        FROM mastery_records mr
        JOIN learning_outcomes lo ON mr.learning_outcome_id = lo.outcome_id
        WHERE mr.user_id = ?
    """, (learner_id,)).fetchall()

    avg_mastery = sum([m["knowledge_level"] for m in mastery_records]) / len(mastery_records) if mastery_records else 0.0

    gaps = AIEngine.analyze_knowledge_gaps(mastery_records)

    context = {
        "user_id": learner_id,
        "username": session.get("username", "Student"),
        "avg_mastery": avg_mastery,
        "gaps": gaps
    }

    response_text = AIEngine.tutor_response(user_input, context)
    conn.close()

    return jsonify({"response": response_text})

@ai_bp.route("/ai/evaluate-all-work")
@login_required
def evaluate_all_work():
    learner_id = session["user_id"]
    if session.get("role") != "learner":
        learner_id = request.args.get("learner_id")
        if not learner_id:
             return redirect(url_for("teacher.teacher_dashboard"))

    conn = get_db()
    evaluation = AIEngine.evaluate_all_work(learner_id, conn)
    conn.close()

    return render_template("ai/evaluation.html", evaluation=evaluation)
