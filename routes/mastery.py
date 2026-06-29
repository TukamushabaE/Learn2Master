from flask import Blueprint, render_template, redirect, session, url_for
from database import get_db

mastery_bp = Blueprint("mastery", __name__)


@mastery_bp.route("/mastery")
def mastery():
    if "user_id" not in session:
        return redirect(url_for("auth.home"))

    learner_id = session["user_id"]

    conn = get_db()
    records = conn.execute("""
        SELECT 
            subjects.subject_name,
            competencies.competency_code,
            competencies.competency_name,
            learning_outcomes.outcome_code,
            learning_outcomes.outcome_name,
            COALESCE(mastery_records.mastery_score, 0) AS mastery_score,
            COALESCE(mastery_records.mastery_level, 'Beginner') AS mastery_level,
            COALESCE(mastery_records.mastery_status, 'Not Started') AS mastery_status
        FROM learning_outcomes
        JOIN competencies ON learning_outcomes.competency_id = competencies.competency_id
        JOIN subjects ON competencies.subject_id = subjects.subject_id
        LEFT JOIN mastery_records
            ON learning_outcomes.outcome_id = mastery_records.outcome_id
            AND mastery_records.learner_id = ?
        ORDER BY subjects.subject_name, competencies.competency_code, learning_outcomes.sequence_order
    """, (learner_id,)).fetchall()
    conn.close()

    return render_template("mastery.html", records=records)