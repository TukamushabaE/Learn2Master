import math
from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename
from routes.guards import role_required
from database import get_db
from security import csrf_protect
from services.analytics_engine import teacher_overview, recent_ai_recommendations
from engine import get_kb

teacher_bp = Blueprint("teacher", __name__)


def learner_rows(conn):
    return conn.execute("""
        SELECT learner.user_id, learner.full_name, learner.username, learner.email,
               COALESCE(lp.class_level, 'Senior One') AS class_level,
               COALESCE(lp.learning_pace, 'Not classified') AS learning_pace,
               COALESCE(lp.learning_style, 'Adaptive / Mixed') AS learning_style,
               COUNT(mr.mastery_id) AS mastery_records,
               SUM(CASE WHEN mr.mastery_status='Mastered' THEN 1 ELSE 0 END) AS mastered_records,
               ROUND(AVG(COALESCE(mr.mastery_score, 0)), 1) AS avg_mastery
        FROM users learner
        JOIN roles r ON learner.role_id = r.role_id
        LEFT JOIN learner_profiles lp ON lp.learner_id = learner.user_id
        LEFT JOIN mastery_records mr ON mr.learner_id = learner.user_id
        WHERE r.role_name='learner'
        GROUP BY learner.user_id
        ORDER BY learner.full_name
    """).fetchall()


@teacher_bp.route("/teacher")
@role_required("teacher", "school_admin", "super_admin")
def teacher_dashboard():
    conn = get_db()
    overview = teacher_overview(conn)
    recommendations = recent_ai_recommendations(conn)
    interventions = conn.execute("""
        SELECT ti.*, learner.full_name AS learner_name, lo.outcome_name
        FROM teacher_interventions ti
        JOIN users learner ON ti.learner_id = learner.user_id
        JOIN learning_outcomes lo ON ti.outcome_id = lo.outcome_id
        ORDER BY ti.created_at DESC LIMIT 8
    """).fetchall()
    weak = conn.execute("""
        SELECT cm.concept_tag, ROUND(AVG(cm.latest_score),1) AS avg_score, COUNT(*) AS evidence
        FROM concept_mastery cm
        GROUP BY cm.concept_tag
        ORDER BY avg_score ASC
        LIMIT 6
    """).fetchall()
    conn.close()
    return render_template("teacher/dashboard.html", overview=overview, recommendations=recommendations, interventions=interventions, weak=weak)


@teacher_bp.route("/teacher/learners")
@role_required("teacher", "school_admin", "super_admin")
def learners():
    conn = get_db()
    rows = learner_rows(conn)
    conn.close()
    return render_template("teacher/learners.html", learners=rows)


@teacher_bp.route("/teacher/portfolio/<int:learner_id>")
@role_required("teacher", "school_admin", "super_admin")
def learner_portfolio(learner_id):
    conn = get_db()
    learner = conn.execute("SELECT * FROM users WHERE user_id=?", (learner_id,)).fetchone()
    rows = conn.execute("""
        SELECT lo.outcome_id, subjects.subject_name, lo.outcome_code, lo.outcome_name,
               lo.practical_required, lo.teacher_review_required,
               COALESCE(mr.pretest_score,0) AS pretest_score,
               COALESCE(mr.practice_score,0) AS practice_score,
               COALESCE(mr.posttest_score,0) AS posttest_score,
               COALESCE(mr.mastery_score,0) AS mastery_score,
               COALESCE(mr.mastery_status,'Not Started') AS mastery_status,
               COALESCE(mr.mastery_level,'Beginning') AS mastery_level,
               (SELECT COUNT(*) FROM learning_reflections lr WHERE lr.learner_id=? AND lr.outcome_id=lo.outcome_id) AS reflections,
               (SELECT COUNT(*) FROM practical_evidence pe WHERE pe.learner_id=? AND pe.outcome_id=lo.outcome_id) AS practical_evidence,
               (SELECT COUNT(*) FROM recommendations rec WHERE rec.learner_id=? AND rec.outcome_id=lo.outcome_id) AS recommendations,
               (SELECT COUNT(*) FROM teacher_mastery_reviews tr WHERE tr.learner_id=? AND tr.outcome_id=lo.outcome_id) AS teacher_reviews
        FROM learning_outcomes lo
        JOIN competencies c ON c.competency_id=lo.competency_id
        JOIN subjects ON subjects.subject_id=c.subject_id
        LEFT JOIN mastery_records mr ON mr.outcome_id=lo.outcome_id AND mr.learner_id=?
        ORDER BY subjects.subject_name, lo.sequence_order
    """, (learner_id, learner_id, learner_id, learner_id, learner_id)).fetchall()
    evidence = conn.execute("""
        SELECT pe.*, lo.outcome_code, lo.outcome_name
        FROM practical_evidence pe
        JOIN learning_outcomes lo ON lo.outcome_id=pe.outcome_id
        WHERE pe.learner_id=?
        ORDER BY pe.created_at DESC
    """, (learner_id,)).fetchall()
    feedback = conn.execute("""
        SELECT tf.*, lo.outcome_code, lo.outcome_name
        FROM teacher_feedback tf
        JOIN learning_outcomes lo ON lo.outcome_id=tf.outcome_id
        WHERE tf.learner_id=?
        ORDER BY tf.created_at DESC LIMIT 20
    """, (learner_id,)).fetchall()
    conn.close()
    return render_template("teacher/portfolio.html", learner=learner, rows=rows, evidence=evidence, feedback=feedback)


@teacher_bp.route("/teacher/mastery/<int:learner_id>/<int:outcome_id>/<action>", methods=["POST"])
@role_required("teacher", "school_admin", "super_admin")
@csrf_protect
def mastery_decision(learner_id, outcome_id, action):
    decisions = {
        "approve": ("Teacher Approved", "Mastered"),
        "override": ("Teacher Override", request.form.get("mastery_status") or "Mastered"),
        "reopen": ("Reopened", "In Progress"),
        "remediate": ("Remediation Assigned", "Remediation Required"),
    }
    if action not in decisions:
        flash("Unsupported mastery action.", "danger")
        return redirect(url_for("teacher.learner_portfolio", learner_id=learner_id))
    decision, status = decisions[action]
    comment = request.form.get("teacher_comment") or f"{decision} by teacher."
    conn = get_db()
    conn.execute("""
        INSERT INTO teacher_mastery_reviews
        (teacher_id, learner_id, outcome_id, decision, reason, teacher_comment)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (session["user_id"], learner_id, outcome_id, decision, request.form.get("reason"), comment))
    conn.execute("""
        INSERT INTO teacher_interventions
        (teacher_id, learner_id, outcome_id, intervention_type, intervention_note, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (session["user_id"], learner_id, outcome_id, decision, comment, status))
    conn.execute("""
        INSERT INTO teacher_feedback
        (teacher_id, learner_id, outcome_id, feedback_type, feedback_text)
        VALUES (?, ?, ?, ?, ?)
    """, (session["user_id"], learner_id, outcome_id, decision, comment))
    existing_mastery = conn.execute("""
        SELECT mastery_score, mastery_level
        FROM mastery_records
        WHERE learner_id=? AND outcome_id=?
    """, (learner_id, outcome_id)).fetchone()
    score = existing_mastery["mastery_score"] if existing_mastery else 0
    level = existing_mastery["mastery_level"] if existing_mastery else "Beginning"
    conn.execute("""
        INSERT INTO mastery_records
        (learner_id, outcome_id, mastery_score, mastery_level, mastery_status, is_unlocked)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(learner_id, outcome_id)
        DO UPDATE SET mastery_status=excluded.mastery_status, updated_at=CURRENT_TIMESTAMP
    """, (learner_id, outcome_id, score, level, status))
    conn.commit()
    conn.close()
    flash(f"Mastery decision recorded: {decision}.", "success")
    return redirect(url_for("teacher.learner_portfolio", learner_id=learner_id))


@teacher_bp.route("/teacher/mastery-monitor")
@role_required("teacher", "school_admin", "super_admin")
def mastery_monitor():
    conn = get_db()
    rows = conn.execute("""
        SELECT learner.full_name, subjects.subject_name, lo.outcome_code, lo.outcome_name,
               COALESCE(mr.pretest_score,0) AS pretest_score,
               COALESCE(mr.practice_score,0) AS practice_score,
               COALESCE(mr.posttest_score,0) AS posttest_score,
               COALESCE(mr.mastery_score,0) AS mastery_score,
               COALESCE(mr.mastery_level,'Beginning') AS mastery_level,
               COALESCE(mr.mastery_status,'Not Started') AS mastery_status
        FROM learning_outcomes lo
        JOIN competencies c ON lo.competency_id=c.competency_id
        JOIN subjects ON c.subject_id=subjects.subject_id
        CROSS JOIN users learner
        JOIN roles r ON learner.role_id=r.role_id AND r.role_name='learner'
        LEFT JOIN mastery_records mr ON mr.outcome_id=lo.outcome_id AND mr.learner_id=learner.user_id
        ORDER BY learner.full_name, subjects.subject_name, lo.sequence_order
    """).fetchall()
    conn.close()
    return render_template("teacher/mastery_monitor.html", rows=rows)


@teacher_bp.route("/teacher/ai-insights")
@role_required("teacher", "school_admin", "super_admin")
def ai_insights():
    conn = get_db()
    recommendations = recent_ai_recommendations(conn, limit=30)
    explanations = conn.execute("""
        SELECT ai.*, learner.full_name, lo.outcome_name
        FROM ai_explanations ai
        JOIN users learner ON ai.learner_id=learner.user_id
        JOIN learning_outcomes lo ON ai.outcome_id=lo.outcome_id
        ORDER BY ai.created_at DESC LIMIT 30
    """).fetchall()
    conn.close()
    return render_template("teacher/ai_insights.html", recommendations=recommendations, explanations=explanations)


@teacher_bp.route("/teacher/reports")
@role_required("teacher", "school_admin", "super_admin")
def reports():
    conn = get_db()
    overview = teacher_overview(conn)
    interventions = conn.execute("""
        SELECT ti.*, learner.full_name AS learner_name, lo.outcome_name
        FROM teacher_interventions ti
        JOIN users learner ON ti.learner_id=learner.user_id
        JOIN learning_outcomes lo ON ti.outcome_id=lo.outcome_id
        ORDER BY ti.created_at DESC LIMIT 50
    """).fetchall()
    conn.close()
    return render_template("teacher/reports.html", overview=overview, interventions=interventions)


@teacher_bp.route("/teacher/recommendation/<int:recommendation_id>/<action>", methods=["POST"])
@role_required("teacher", "school_admin", "super_admin")
@csrf_protect
def review_recommendation(recommendation_id, action):
    if action not in {"approve", "override"}:
        flash("Unsupported recommendation action.", "danger")
        return redirect(url_for("teacher.teacher_dashboard"))
    status = "Approved" if action == "approve" else "Overridden"
    conn = get_db()
    conn.execute("UPDATE recommendations SET teacher_status = ? WHERE recommendation_id = ?", (status, recommendation_id))
    rec = conn.execute("SELECT * FROM recommendations WHERE recommendation_id = ?", (recommendation_id,)).fetchone()
    if rec:
        note = request.form.get("intervention_note") or f"AI recommendation {status.lower()} by teacher."
        conn.execute("""
            INSERT INTO teacher_interventions (teacher_id, learner_id, outcome_id, intervention_type, intervention_note, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session["user_id"], rec["learner_id"], rec["outcome_id"], status, note, "Recorded"))
    conn.commit(); conn.close()
    flash(f"Recommendation {status.lower()} and teacher intervention recorded.", "success")
    return redirect(url_for("teacher.teacher_dashboard"))


@teacher_bp.route("/teacher/practical-evidence")
@role_required("teacher", "school_admin", "super_admin")
def practical_evidence():
    conn = get_db()
    rows = conn.execute("""
        SELECT pe.*, learner.full_name AS learner_name, lo.outcome_name, subjects.subject_name
        FROM practical_evidence pe
        JOIN users learner ON pe.learner_id = learner.user_id
        JOIN learning_outcomes lo ON pe.outcome_id = lo.outcome_id
        JOIN competencies c ON lo.competency_id = c.competency_id
        JOIN subjects ON c.subject_id = subjects.subject_id
        ORDER BY pe.created_at DESC
    """).fetchall()
    conn.close()
    return render_template("teacher/practical_evidence.html", rows=rows)


@teacher_bp.route("/teacher/practical-evidence/<int:practical_id>/<action>", methods=["POST"])
@role_required("teacher", "school_admin", "super_admin")
@csrf_protect
def review_practical_evidence(practical_id, action):
    if action not in {"approve", "revise"}:
        flash("Unsupported evidence action.", "danger")
        return redirect(url_for("teacher.practical_evidence"))
    status = "Approved" if action == "approve" else "Needs Revision"
    comment = request.form.get("teacher_comment") or ("Evidence approved." if action == "approve" else "Revise and resubmit evidence.")
    rubric_level = request.form.get("rubric_level") or ("Proficient" if action == "approve" else "Developing")
    try:
        rubric_score = int(request.form.get("rubric_score") or (3 if action == "approve" else 2))
    except ValueError:
        rubric_score = 0
    conn = get_db()
    row = conn.execute("SELECT * FROM practical_evidence WHERE practical_id=?", (practical_id,)).fetchone()
    if row:
        conn.execute("""
            UPDATE practical_evidence
            SET teacher_status=?, teacher_comment=?, rubric_level=?, rubric_score=?, reviewed_at=CURRENT_TIMESTAMP
            WHERE practical_id=?
        """, (status, comment, rubric_level, rubric_score, practical_id))
        rubric = conn.execute("""
            SELECT rubric_id FROM rubric_criteria
            WHERE outcome_id=? AND level=?
            LIMIT 1
        """, (row["outcome_id"], rubric_level)).fetchone()
        conn.execute("""
            INSERT INTO rubric_assessments
            (practical_id, rubric_id, teacher_id, level, score, teacher_comment)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (practical_id, rubric["rubric_id"] if rubric else None, session["user_id"], rubric_level, rubric_score, comment))
        conn.execute("""
            INSERT INTO teacher_interventions (teacher_id, learner_id, outcome_id, intervention_type, intervention_note, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (session["user_id"], row["learner_id"], row["outcome_id"], "Practical Evidence Review", comment, status))
    conn.commit(); conn.close()
    flash(f"Practical evidence marked as {status}.", "success")
    return redirect(url_for("teacher.practical_evidence"))


@teacher_bp.route("/teacher/kb")
@role_required("teacher", "school_admin", "super_admin")
def teacher_kb_view():
    page = request.args.get('page', 1, type=int)
    per_page = 50
    kb = get_kb()
    total_chunks = len(kb.chunks)
    total_pages = math.ceil(total_chunks / per_page)

    start = (page - 1) * per_page
    end = start + per_page
    chunks = kb.chunks[start:end]

    return render_template("teacher_kb_view.html", chunks=chunks, page=page, total_pages=total_pages)


@teacher_bp.route("/teacher/students/pending")
@role_required("teacher", "school_admin")
def pending_students():
    conn = get_db()
    # Teachers see students from their school
    user = conn.execute("SELECT school_id FROM users WHERE user_id = ?", (session["user_id"],)).fetchone()
    students = conn.execute("""
        SELECT u.* FROM users u
        JOIN roles r ON u.role_id = r.role_id
        WHERE r.role_name = 'learner' AND u.account_status = 'Pending' AND u.school_id = ?
    """, (user['school_id'],)).fetchall()
    conn.close()
    return render_template("teacher/pending_students.html", students=students)

@teacher_bp.route("/teacher/students/approve/<int:user_id>", methods=["POST"])
@role_required("teacher", "school_admin")
@csrf_protect
def approve_student(user_id):
    conn = get_db()
    conn.execute("UPDATE users SET account_status = 'Active', approved_by = ?, approved_at = CURRENT_TIMESTAMP WHERE user_id = ?", (session['user_id'], user_id))
    conn.commit()
    conn.close()
    flash("Student account approved.", "success")
    return redirect(url_for("teacher.pending_students"))

@teacher_bp.route("/teacher/students/assign-subjects", methods=["GET", "POST"])
@role_required("teacher", "school_admin")
@csrf_protect
def assign_subjects():
    conn = get_db()
    if request.method == "POST":
        student_ids = request.form.getlist("student_ids")
        subject_ids = request.form.getlist("subject_ids")

        for sid in student_ids:
            for subid in subject_ids:
                try:
                    conn.execute("""
                        INSERT INTO student_subject_assignments (student_id, subject_id, assigned_by)
                        VALUES (?, ?, ?)
                        ON CONFLICT(student_id, subject_id) DO NOTHING
                    """, (sid, subid, session['user_id']))
                except Exception: pass
        conn.commit()
        flash("Subjects assigned successfully.", "success")
        return redirect(url_for("teacher.teacher_dashboard"))

    user = conn.execute("SELECT school_id FROM users WHERE user_id = ?", (session["user_id"],)).fetchone()
    students = conn.execute("""
        SELECT u.user_id, u.full_name FROM users u
        JOIN roles r ON u.role_id = r.role_id
        WHERE r.role_name = 'learner' AND u.account_status = 'Active' AND u.school_id = ?
    """, (user['school_id'],)).fetchall()
    subjects = conn.execute("SELECT * FROM subjects").fetchall()
    conn.close()
    return render_template("teacher/assign_subjects.html", students=students, subjects=subjects)


@teacher_bp.route("/teacher/students/create", methods=["GET", "POST"])
@role_required("teacher", "school_admin")
@csrf_protect
def create_student():
    conn = get_db()
    if request.method == "POST":
        username = request.form.get("username")
        full_name = request.form.get("full_name")
        email = request.form.get("email")
        password = request.form.get("password")

        user_info = conn.execute("SELECT school_id FROM users WHERE user_id = ?", (session["user_id"],)).fetchone()
        role = conn.execute("SELECT role_id FROM roles WHERE role_name = 'learner'").fetchone()

        try:
            conn.execute("""
                INSERT INTO users (full_name, username, email, password_hash, role_id, school_id, account_status, security_level, approved_by, approved_at)
                VALUES (?, ?, ?, ?, ?, ?, 'Active', 1, ?, CURRENT_TIMESTAMP)
            """, (full_name, username, email, generate_password_hash(password), role['role_id'], user_info['school_id'], session['user_id']))
            conn.commit()
            flash("Student created successfully.", "success")
            return redirect(url_for("teacher.teacher_dashboard"))
        except Exception as e:
            flash(f"Error creating student: {e}", "danger")

    conn.close()
    return render_template("teacher/student_form.html")


@teacher_bp.route("/teacher/kb/upload", methods=["GET", "POST"])
@role_required("teacher", "school_admin")
@csrf_protect
def teacher_kb_upload():
    import magic
    from werkzeug.utils import secure_filename
    conn = get_db()
    teacher_id = session["user_id"]
    kb = get_kb()

    # Check 10MB limit
    usage = conn.execute("SELECT SUM(original_size_bytes) FROM teacher_kb_uploads WHERE teacher_id = ?", (teacher_id,)).fetchone()[0] or 0
    LIMIT = 10 * 1024 * 1024 # 10MB

    if request.method == "POST":
        file = request.files.get("file")
        if file and file.filename:
            filename = secure_filename(file.filename)
            ext = os.path.splitext(filename)[1].lower()
            if ext not in {'.txt', '.md', '.json', '.pdf'}:
                flash("Unsupported file type. Use .txt, .md, .json, or .pdf", "danger")
                return redirect(url_for("teacher.teacher_kb_upload"))

            # Calculate file size before saving
            file.seek(0, os.SEEK_END)
            file_size = file.tell()
            file.seek(0)

            if usage + file_size > LIMIT:
                filepath.unlink()
                flash("Upload failed: You have exceeded your 10MB storage limit.", "danger")
                return redirect(url_for("teacher.teacher_kb_upload"))

            filepath = kb.directory / filename
            file.save(str(filepath))

            # Use unified processing method with summarization forced for teachers
            success, summary_size = kb.process_file(str(filepath), metadata={"teacher_id": teacher_id}, summarize=True)

            if success:
                # Record upload
                conn.execute("""
                    INSERT INTO teacher_kb_uploads (teacher_id, filename, original_size_bytes, summary_size_bytes)
                    VALUES (?, ?, ?, ?)
                """, (teacher_id, filename, file_size, summary_size))
                conn.commit()
                flash(f"File {filename} uploaded and processed with AI summarization.", "success")
            else:
                flash(f"Error processing {filename}.", "danger")

            return redirect(url_for("teacher.teacher_kb_upload"))

    uploads = conn.execute("SELECT * FROM teacher_kb_uploads WHERE teacher_id = ?", (teacher_id,)).fetchall()
    conn.close()
    return render_template("teacher/kb_upload.html", uploads=uploads, usage=usage, limit=LIMIT)
