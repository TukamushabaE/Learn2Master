from flask import Blueprint, render_template, session
from routes.guards import role_required
from database import get_db

student_bp = Blueprint("student", __name__)


@student_bp.route("/student/dashboard")
@role_required("learner")
def student_dashboard():
    learner_id = session["user_id"]
    conn = get_db()

    total_outcomes = conn.execute("SELECT COUNT(*) AS total FROM learning_outcomes").fetchone()["total"]
    mastered_outcomes = conn.execute("""
        SELECT COUNT(*) AS total FROM mastery_records
        WHERE learner_id=? AND mastery_status='Mastered'
    """, (learner_id,)).fetchone()["total"]
    attempted = conn.execute("""
        SELECT COUNT(DISTINCT lo.outcome_id) AS total
        FROM assessment_attempts aa
        JOIN assessments a ON aa.assessment_id = a.assessment_id
        JOIN lessons l ON a.lesson_id = l.lesson_id
        JOIN learning_outcomes lo ON l.outcome_id = lo.outcome_id
        WHERE aa.learner_id=?
    """, (learner_id,)).fetchone()["total"]

    avg_mastery = conn.execute("""
        SELECT AVG(mastery_score) AS avg_score
        FROM mastery_records
        WHERE learner_id=?
    """, (learner_id,)).fetchone()["avg_score"]
    avg_mastery = round(avg_mastery) if avg_mastery is not None else 0

    latest_recommendation = conn.execute("""
        SELECT recommendation_reason, recommendation_type, confidence_score,
               expected_mastery, estimated_study_minutes, recommended_resource, created_at
        FROM recommendations
        WHERE learner_id=?
        ORDER BY created_at DESC
        LIMIT 1
    """, (learner_id,)).fetchone()

    pathways = conn.execute("""
        SELECT c.course_id, c.course_title, c.course_description, s.subject_name,
            COALESCE(AVG(mr.mastery_score), 0) AS avg_score
        FROM courses c
        JOIN subjects s ON c.subject_id = s.subject_id
        LEFT JOIN lessons l ON l.course_id = c.course_id
        LEFT JOIN mastery_records mr ON mr.outcome_id = l.outcome_id AND mr.learner_id=?
        WHERE s.subject_name IN ('Physics', 'ICT')
        GROUP BY c.course_id
        ORDER BY s.subject_name DESC
    """, (learner_id,)).fetchall()

    activities = conn.execute("""
        SELECT activity_type, activity_description, created_at
        FROM activity_logs
        WHERE learner_id=?
        ORDER BY created_at DESC
        LIMIT 4
    """, (learner_id,)).fetchall()

    conn.close()

    stats = {
        "total_outcomes": total_outcomes,
        "mastered_outcomes": mastered_outcomes,
        "attempted": attempted,
        "avg_mastery": avg_mastery,
    }
    return render_template("student_dashboard.html", stats=stats, latest_recommendation=latest_recommendation, pathways=pathways, activities=activities)

@student_bp.route("/student/assessments")
@role_required("learner")
def assessments():
    learner_id = session["user_id"]
    conn = get_db()
    rows = conn.execute("""
        SELECT subjects.subject_name, courses.course_title, lo.outcome_code, lo.outcome_name,
               assessments.assessment_type, assessments.assessment_title,
               COALESCE(MAX(assessment_attempts.score), NULL) AS best_score,
               COUNT(assessment_attempts.attempt_id) AS attempts
        FROM assessments
        JOIN lessons ON assessments.lesson_id = lessons.lesson_id
        JOIN courses ON lessons.course_id = courses.course_id
        JOIN subjects ON courses.subject_id = subjects.subject_id
        JOIN learning_outcomes lo ON lessons.outcome_id = lo.outcome_id
        LEFT JOIN assessment_attempts ON assessment_attempts.assessment_id = assessments.assessment_id
            AND assessment_attempts.learner_id = ?
        GROUP BY assessments.assessment_id
        ORDER BY subjects.subject_name, lo.sequence_order, assessments.assessment_type
    """, (learner_id,)).fetchall()
    conn.close()
    return render_template("student/assessments.html", rows=rows)


@student_bp.route("/student/analytics")
@role_required("learner")
def my_analytics():
    learner_id = session["user_id"]
    conn = get_db()
    concept_rows = conn.execute("""
        SELECT concept_tag, latest_score, latest_assessment_type, attempt_count, concept_status, updated_at
        FROM concept_mastery
        WHERE learner_id = ?
        ORDER BY latest_score ASC, concept_tag
    """, (learner_id,)).fetchall()
    mastery_rows = conn.execute("""
        SELECT subjects.subject_name, lo.outcome_code, lo.outcome_name, mr.pretest_score,
               mr.practice_score, mr.posttest_score, mr.mastery_score, mr.mastery_level, mr.mastery_status
        FROM mastery_records mr
        JOIN learning_outcomes lo ON mr.outcome_id=lo.outcome_id
        JOIN competencies c ON lo.competency_id=c.competency_id
        JOIN subjects ON c.subject_id=subjects.subject_id
        WHERE mr.learner_id=?
        ORDER BY subjects.subject_name, lo.sequence_order
    """, (learner_id,)).fetchall()
    recommendations = conn.execute("""
        SELECT recommendation_reason, recommendation_type, teacher_status, created_at
        FROM recommendations
        WHERE learner_id=?
        ORDER BY created_at DESC LIMIT 10
    """, (learner_id,)).fetchall()
    conn.close()
    return render_template("student/analytics.html", concept_rows=concept_rows, mastery_rows=mastery_rows, recommendations=recommendations)


@student_bp.route("/learner/portfolio")
@role_required("learner")
def portfolio():
    learner_id = session["user_id"]
    conn = get_db()
    rows = conn.execute("""
        SELECT lo.outcome_id, subjects.subject_name, topics.topic_title, lo.outcome_code, lo.outcome_name,
               lo.practical_required, COALESCE(mr.pretest_score,0) AS pretest_score,
               COALESCE(mr.practice_score,0) AS practice_score, COALESCE(mr.posttest_score,0) AS posttest_score,
               COALESCE(mr.mastery_score,0) AS mastery_score, COALESCE(mr.mastery_status,'Not Started') AS mastery_status,
               COALESCE(mr.mastery_level,'Beginning') AS mastery_level,
               (SELECT COUNT(*) FROM assessment_attempts aa JOIN assessments a ON aa.assessment_id=a.assessment_id JOIN lessons l ON a.lesson_id=l.lesson_id WHERE aa.learner_id=? AND l.outcome_id=lo.outcome_id AND a.assessment_type='pretest') AS pretest_done,
               (SELECT COUNT(*) FROM assessment_attempts aa JOIN assessments a ON aa.assessment_id=a.assessment_id JOIN lessons l ON a.lesson_id=l.lesson_id WHERE aa.learner_id=? AND l.outcome_id=lo.outcome_id AND a.assessment_type='practice') AS practice_done,
               (SELECT COUNT(*) FROM assessment_attempts aa JOIN assessments a ON aa.assessment_id=a.assessment_id JOIN lessons l ON a.lesson_id=l.lesson_id WHERE aa.learner_id=? AND l.outcome_id=lo.outcome_id AND a.assessment_type='posttest') AS posttest_done,
               (SELECT COUNT(*) FROM learning_reflections lr WHERE lr.learner_id=? AND lr.outcome_id=lo.outcome_id) AS reflections,
               (SELECT COUNT(*) FROM practical_evidence pe WHERE pe.learner_id=? AND pe.outcome_id=lo.outcome_id) AS practical_evidence,
               (SELECT COUNT(*) FROM recommendations r WHERE r.learner_id=? AND r.outcome_id=lo.outcome_id) AS recommendations,
               (SELECT COUNT(*) FROM teacher_feedback tf WHERE tf.learner_id=? AND tf.outcome_id=lo.outcome_id) AS teacher_feedback,
               (SELECT COUNT(*) FROM teacher_mastery_reviews tr WHERE tr.learner_id=? AND tr.outcome_id=lo.outcome_id) AS teacher_reviews
        FROM learning_outcomes lo
        JOIN competencies c ON c.competency_id=lo.competency_id
        JOIN subjects ON subjects.subject_id=c.subject_id
        LEFT JOIN topics ON topics.topic_id=lo.topic_id
        LEFT JOIN mastery_records mr ON mr.outcome_id=lo.outcome_id AND mr.learner_id=?
        ORDER BY subjects.subject_name, lo.sequence_order
    """, (learner_id, learner_id, learner_id, learner_id, learner_id, learner_id, learner_id, learner_id, learner_id)).fetchall()
    latest_feedback = conn.execute("""
        SELECT tf.*, lo.outcome_code, lo.outcome_name, teacher.full_name AS teacher_name
        FROM teacher_feedback tf
        JOIN learning_outcomes lo ON lo.outcome_id=tf.outcome_id
        JOIN users teacher ON teacher.user_id=tf.teacher_id
        WHERE tf.learner_id=?
        ORDER BY tf.created_at DESC LIMIT 10
    """, (learner_id,)).fetchall()
    conn.close()
    return render_template("student/portfolio.html", rows=rows, latest_feedback=latest_feedback)
