from flask import Blueprint, render_template, session
from routes.guards import role_required
from database import get_db

subjects_bp = Blueprint("subjects", __name__)


@subjects_bp.route("/subjects")
@role_required("learner")
def subjects():
    learner_id = session["user_id"]
    conn = get_db()

    subjects = conn.execute("""
        SELECT subject_id, subject_name
        FROM subjects
        WHERE subject_name IN ('Physics', 'ICT')
        ORDER BY CASE subject_name WHEN 'Physics' THEN 1 WHEN 'ICT' THEN 2 ELSE 3 END
    """).fetchall()

    subject_cards = []
    for subject in subjects:
        total = conn.execute("""
            SELECT COUNT(*) AS total
            FROM learning_outcomes lo
            JOIN competencies c ON lo.competency_id = c.competency_id
            WHERE c.subject_id = ?
        """, (subject["subject_id"],)).fetchone()["total"]

        mastered = conn.execute("""
            SELECT COUNT(*) AS total
            FROM mastery_records mr
            JOIN learning_outcomes lo ON mr.outcome_id = lo.outcome_id
            JOIN competencies c ON lo.competency_id = c.competency_id
            WHERE c.subject_id = ? AND mr.learner_id = ? AND mr.mastery_status = 'Mastered'
        """, (subject["subject_id"], learner_id)).fetchone()["total"]

        progress = round((mastered / total) * 100) if total else 0

        subject_cards.append({
            "id": subject["subject_id"],
            "name": subject["subject_name"],
            "code": "PHY" if subject["subject_name"] == "Physics" else "ICT",
            "icon": "⚛" if subject["subject_name"] == "Physics" else "💻",
            "description": "Senior One research topic: Measurements in Physics." if subject["subject_name"] == "Physics" else "Senior One research topic: Introduction to ICT.",
            "progress": progress,
            "mastered": mastered,
            "total": total,
        })

    conn.close()
    return render_template("subjects.html", subjects=subject_cards)


@subjects_bp.route("/subjects/<int:subject_id>")
@role_required("learner")
def subject_detail(subject_id):
    learner_id = session["user_id"]
    conn = get_db()

    subject = conn.execute("SELECT * FROM subjects WHERE subject_id=?", (subject_id,)).fetchone()
    if not subject:
        conn.close()
        return "Subject not found", 404
    conn.execute("""
        INSERT INTO activity_logs (learner_id, activity_type, activity_description)
        VALUES (?, 'Subject Opened', ?)
    """, (learner_id, f"Opened subject {subject['subject_name']}"))

    pathways = conn.execute("""
        SELECT course_id, course_title, course_description, difficulty_level
        FROM courses
        WHERE subject_id=?
        ORDER BY course_id
    """, (subject_id,)).fetchall()

    pathway_cards = []
    for p in pathways:
        total = conn.execute("""
            SELECT COUNT(*) AS total
            FROM lessons
            WHERE course_id=?
        """, (p["course_id"],)).fetchone()["total"]

        mastered = conn.execute("""
            SELECT COUNT(*) AS total
            FROM mastery_records mr
            JOIN lessons l ON mr.outcome_id = l.outcome_id
            WHERE l.course_id=? AND mr.learner_id=? AND mr.mastery_status='Mastered'
        """, (p["course_id"], learner_id)).fetchone()["total"]

        progress = round((mastered / total) * 100) if total else 0
        pathway_cards.append({"pathway": p, "progress": progress, "mastered": mastered, "total": total})

    conn.commit()
    conn.close()
    return render_template("subject_detail.html", subject=subject, pathway_cards=pathway_cards)
