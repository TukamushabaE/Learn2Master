from routes.guards import login_required
from flask import Blueprint, render_template, redirect, session, url_for, request
from database import get_db


dashboard_bp = Blueprint("dashboard", __name__)


@dashboard_bp.route("/dashboard")
@login_required
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("auth.home"))

    learner_id = session["user_id"]
    selected_subject_id = request.args.get("subject_id")
    selected_course_id = request.args.get("course_id")

    conn = get_db()

    user = conn.execute("""
        SELECT users.full_name, users.username, roles.role_name, schools.school_name
        FROM users
        JOIN roles ON users.role_id = roles.role_id
        LEFT JOIN schools ON users.school_id = schools.school_id
        WHERE users.user_id = ?
    """, (learner_id,)).fetchone()

    subjects = conn.execute("""
        SELECT subject_id, subject_name
        FROM subjects
        ORDER BY subject_name
    """).fetchall()

    courses = []
    selected_subject = None

    if selected_subject_id:
        selected_subject = conn.execute("""
            SELECT subject_id, subject_name
            FROM subjects
            WHERE subject_id = ?
        """, (selected_subject_id,)).fetchone()

        courses = conn.execute("""
            SELECT course_id, course_title, course_description, difficulty_level
            FROM courses
            WHERE subject_id = ?
            ORDER BY course_title
        """, (selected_subject_id,)).fetchall()

    selected_course = None
    lessons = []

    if selected_course_id:
        selected_course = conn.execute("""
            SELECT course_id, course_title, course_description, difficulty_level
            FROM courses
            WHERE course_id = ?
        """, (selected_course_id,)).fetchone()

        lessons = conn.execute("""
            SELECT 
                lessons.lesson_id,
                lessons.lesson_title,
                lessons.estimated_minutes,
                learning_outcomes.outcome_code,
                learning_outcomes.outcome_name,
                COALESCE(mastery_records.mastery_score, 0) AS mastery_score,
                COALESCE(mastery_records.mastery_status, 'Not Started') AS mastery_status
            FROM lessons
            JOIN learning_outcomes ON lessons.outcome_id = learning_outcomes.outcome_id
            LEFT JOIN mastery_records
                ON learning_outcomes.outcome_id = mastery_records.outcome_id
                AND mastery_records.learner_id = ?
            WHERE lessons.course_id = ?
            ORDER BY lessons.sequence_order
        """, (learner_id, selected_course_id)).fetchall()

    total_courses = conn.execute("""
        SELECT COUNT(*) AS total FROM courses
    """).fetchone()["total"]

    total_outcomes = conn.execute("""
        SELECT COUNT(*) AS total FROM learning_outcomes
    """).fetchone()["total"]

    mastered_outcomes = conn.execute("""
        SELECT COUNT(*) AS total
        FROM mastery_records
        WHERE learner_id = ? AND mastery_status = 'Mastered'
    """, (learner_id,)).fetchone()["total"]

    activities = conn.execute("""
        SELECT activity_type, activity_description, created_at
        FROM activity_logs
        WHERE learner_id = ?
        ORDER BY created_at DESC
        LIMIT 5
    """, (learner_id,)).fetchall()

    conn.close()

    progress_percentage = round((mastered_outcomes / total_outcomes) * 100) if total_outcomes else 0

    dashboard_data = {
        "total_courses": total_courses,
        "total_outcomes": total_outcomes,
        "mastered_outcomes": mastered_outcomes,
        "progress_percentage": progress_percentage
    }

    return render_template(
        "dashboard.html",
        user=user,
        dashboard_data=dashboard_data,
        subjects=subjects,
        courses=courses,
        lessons=lessons,
        selected_subject=selected_subject,
        selected_subject_id=selected_subject_id,
        selected_course=selected_course,
        selected_course_id=selected_course_id,
        activities=activities
    )