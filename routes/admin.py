import os
from datetime import datetime, timedelta
from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from database import DatabaseIntegrityError, get_db
from engine import get_kb
from routes.guards import role_required
from security import csrf_protect

admin_bp = Blueprint("admin", __name__)

ROLE_SECURITY_DEFAULTS = {
    "learner": 1,
    "teacher": 3,
    "school_admin": 4,
    "super_admin": 5,
}
ROLE_SECURITY_LIMITS = {
    "learner": (1, 2),
    "teacher": (3, 3),
    "school_admin": (4, 4),
    "super_admin": (5, 5),
}
ACCOUNT_STATUSES = ("Active", "Pending", "Suspended", "Locked")
SCHOOL_ADMIN_MANAGED_ROLES = {"learner", "teacher"}
SETTING_GROUPS = [
    {
        "key": "ai_personalization",
        "title": "AI & Personalization Settings",
        "summary": "Controls how the platform adapts content, hints, pacing and feedback for each learner.",
        "settings": [
            {
                "key": "ai_adaptivity_level",
                "label": "Adaptivity Level",
                "type": "select",
                "default": "balanced",
                "options": [
                    ("conservative", "Conservative"),
                    ("balanced", "Balanced"),
                    ("aggressive", "Aggressive"),
                ],
                "description": "How strongly AI adjusts difficulty and content sequencing from performance evidence.",
            },
            {
                "key": "ai_learning_style_profile",
                "label": "Learning Style Profile",
                "type": "select",
                "default": "multimodal",
                "options": [
                    ("multimodal", "Multimodal"),
                    ("visual_first", "Visual-first"),
                    ("text_first", "Text-first"),
                    ("audio_supported", "Audio-supported"),
                ],
                "description": "Preferred presentation mode for notes, examples, diagrams and feedback.",
            },
            {
                "key": "ai_pacing_mode",
                "label": "Pacing Mode",
                "type": "select",
                "default": "guided_self_paced",
                "options": [
                    ("independent_self_paced", "Independent self-paced"),
                    ("guided_self_paced", "Guided self-paced"),
                    ("target_date_guided", "Target-date guided"),
                ],
                "description": "Whether learners move freely or follow AI/teacher pacing toward target dates.",
            },
            {
                "key": "ai_tutor_persona",
                "label": "AI Tutor Persona",
                "type": "select",
                "default": "supportive_coach",
                "options": [
                    ("supportive_coach", "Supportive coach"),
                    ("socratic_guide", "Socratic guide"),
                    ("strict_examiner", "Strict examiner"),
                    ("minimal_hints", "Minimal hints"),
                ],
                "description": "Tone, strictness and hinting style used by AI-generated support.",
            },
        ],
    },
    {
        "key": "cbc_mastery",
        "title": "CBC & Mastery Configuration",
        "summary": "Defines the curriculum standard, mastery evidence rules and progression model.",
        "settings": [
            {
                "key": "cbc_framework_mapping",
                "label": "Competency Framework Mapping",
                "type": "select",
                "default": "uganda_lower_secondary_cbc",
                "options": [
                    ("uganda_lower_secondary_cbc", "Uganda Lower Secondary CBC"),
                    ("kenya_cbc", "Kenya CBC"),
                    ("institutional_custom", "Institutional custom framework"),
                ],
                "description": "National or institutional competency framework used for outcome mapping.",
            },
            {
                "key": "mastery_threshold",
                "label": "Default Mastery Threshold",
                "type": "number",
                "default": "80",
                "min": 50,
                "max": 100,
                "suffix": "%",
                "description": "Default score or evidence threshold required to prove mastery.",
            },
            {
                "key": "prerequisite_enforcement",
                "label": "Prerequisite Enforcement",
                "type": "select",
                "default": "strict",
                "options": [
                    ("strict", "Strict dependency pathway"),
                    ("teacher_override", "Teacher override allowed"),
                    ("open_exploration", "Open exploration"),
                ],
                "description": "Whether learners can skip ahead or must unlock outcomes in order.",
            },
            {
                "key": "strand_visibility",
                "label": "Strand & Sub-strand Visibility",
                "type": "select",
                "default": "outcome_concept",
                "options": [
                    ("strand_only", "Strand only"),
                    ("strand_substrand", "Strand and sub-strand"),
                    ("outcome_concept", "Outcome and concept detail"),
                ],
                "description": "Granularity of the curriculum tree shown to learners and teachers.",
            },
        ],
    },
    {
        "key": "assessment_evaluation",
        "title": "Assessment & Evaluation Behaviors",
        "summary": "Controls feedback timing, retry policy, assessment integrity and alternative evidence modes.",
        "settings": [
            {
                "key": "assessment_feedback_mode",
                "label": "Formative vs. Summative Feedback",
                "type": "select",
                "default": "instant_formative_delayed_summative",
                "options": [
                    ("instant_formative_delayed_summative", "Instant formative, delayed summative"),
                    ("all_instant", "Instant feedback for all"),
                    ("all_delayed", "Feedback after submission only"),
                ],
                "description": "When AI explanations and corrective feedback appear.",
            },
            {
                "key": "proctoring_integrity_mode",
                "label": "Proctoring & Integrity",
                "type": "select",
                "default": "audit_only",
                "options": [
                    ("off", "Off"),
                    ("audit_only", "Audit only"),
                    ("browser_lock", "Browser lock"),
                    ("plagiarism_focus", "Plagiarism and focus checks"),
                ],
                "description": "Assessment integrity controls used for high-stakes tasks.",
            },
            {
                "key": "retry_policy_attempts",
                "label": "Mastery Retry Attempts",
                "type": "number",
                "default": "3",
                "min": 1,
                "max": 10,
                "description": "Number of allowed attempts before teacher intervention is recommended.",
            },
            {
                "key": "retry_cooldown_hours",
                "label": "Retry Cooldown",
                "type": "number",
                "default": "0",
                "min": 0,
                "max": 168,
                "suffix": "hours",
                "description": "Waiting time between mastery assessment attempts.",
            },
            {
                "key": "alternative_assessment_modes",
                "label": "Alternative Assessment Modes",
                "type": "select",
                "default": "teacher_review",
                "options": [
                    ("disabled", "Disabled"),
                    ("teacher_review", "Portfolio/project with teacher review"),
                    ("ai_assisted_review", "AI-assisted portfolio/project review"),
                ],
                "description": "Portfolio, oral, project or practical evidence grading support.",
            },
        ],
    },
    {
        "key": "roles_collaboration",
        "title": "User Roles & Collaboration",
        "summary": "Defines observer access, guardian visibility and peer collaboration boundaries.",
        "settings": [
            {
                "key": "parent_observer_access",
                "label": "Parent / Guardian Observer Access",
                "type": "select",
                "default": "disabled",
                "options": [
                    ("disabled", "Disabled"),
                    ("view_only", "View-only dashboard"),
                    ("invite_required", "Invite required"),
                ],
                "description": "Guardian visibility into learner progress and reports.",
            },
            {
                "key": "co_teacher_observer_access",
                "label": "Co-teacher & Observer Access",
                "type": "select",
                "default": "school_admin_approved",
                "options": [
                    ("disabled", "Disabled"),
                    ("school_admin_approved", "School admin approved"),
                    ("open_with_audit", "Open with audit trail"),
                ],
                "description": "Controls educator collaboration and live-progress observer access.",
            },
            {
                "key": "peer_visibility",
                "label": "Peer-to-peer Visibility",
                "type": "select",
                "default": "private",
                "options": [
                    ("private", "Private progress"),
                    ("class_anonymous", "Anonymous class comparison"),
                    ("class_named", "Named class leaderboards"),
                ],
                "description": "Learner visibility in peer dashboards, groups and leaderboards.",
            },
        ],
    },
    {
        "key": "privacy_safety_compliance",
        "title": "Privacy, Safety & Compliance",
        "summary": "Sets data minimization, compliance posture, content filtering and learner safety guardrails.",
        "settings": [
            {
                "key": "student_data_retention_days",
                "label": "Data Retention",
                "type": "number",
                "default": "365",
                "min": 30,
                "max": 3650,
                "suffix": "days",
                "description": "How long learner telemetry and AI evidence records are retained before review/export/deletion.",
            },
            {
                "key": "compliance_mode",
                "label": "Compliance Mode",
                "type": "select",
                "default": "local_school_policy",
                "options": [
                    ("local_school_policy", "Local school policy"),
                    ("gdpr_ready", "GDPR-ready"),
                    ("coppa_gdpr_local", "COPPA/GDPR/local hybrid"),
                ],
                "description": "Privacy-control baseline for consent, export and deletion workflows.",
            },
            {
                "key": "content_filtering_level",
                "label": "Content Filtering",
                "type": "select",
                "default": "strict",
                "options": [
                    ("standard", "Standard"),
                    ("strict", "Strict learner-safe"),
                    ("exam_safe", "Exam-safe locked mode"),
                ],
                "description": "Sensitivity of AI guardrails for learner-generated text and uploads.",
            },
        ],
    },
    {
        "key": "notifications_interventions",
        "title": "Notifications & Interventions",
        "summary": "Controls automated nudges, at-risk detection and delivery channels for interventions.",
        "settings": [
            {
                "key": "nudge_frequency",
                "label": "Nudge Frequency",
                "type": "select",
                "default": "weekly",
                "options": [
                    ("off", "Off"),
                    ("weekly", "Weekly"),
                    ("twice_weekly", "Twice weekly"),
                    ("daily", "Daily"),
                ],
                "description": "How often AI sends reminders about gaps, deadlines and unfinished practice.",
            },
            {
                "key": "at_risk_threshold",
                "label": "At-risk Alert Threshold",
                "type": "number",
                "default": "60",
                "min": 0,
                "max": 100,
                "suffix": "%",
                "description": "Predicted mastery level below which teachers are alerted.",
            },
            {
                "key": "delivery_channels",
                "label": "Delivery Channels",
                "type": "select",
                "default": "in_app",
                "options": [
                    ("in_app", "In-app only"),
                    ("in_app_email", "In-app and email"),
                    ("in_app_email_sms", "In-app, email and SMS"),
                ],
                "description": "Notification channels for learners, teachers and guardians.",
            },
        ],
    },
]


def current_admin(conn):
    return conn.execute("""
        SELECT users.user_id, users.school_id, users.security_level, roles.role_name
        FROM users
        JOIN roles ON users.role_id = roles.role_id
        WHERE users.user_id = ?
    """, (session.get("user_id"),)).fetchone()


def school_scope_for(conn, admin=None):
    admin = admin or current_admin(conn)
    if admin and admin["role_name"] == "super_admin":
        return None
    return admin["school_id"] if admin else None


def managed_schools(conn, admin=None):
    scope = school_scope_for(conn, admin)
    if scope is None:
        return conn.execute("SELECT school_id, school_name FROM schools ORDER BY school_name").fetchall()
    return conn.execute("SELECT school_id, school_name FROM schools WHERE school_id = ?", (scope,)).fetchall()


def can_assign_role(admin, role_name):
    if not admin:
        return False
    if admin["role_name"] == "super_admin":
        return role_name in ROLE_SECURITY_DEFAULTS
    return role_name in SCHOOL_ADMIN_MANAGED_ROLES


def can_manage_user(admin, user):
    if not admin or not user:
        return False
    if admin["role_name"] == "super_admin":
        return True
    return (
        user["school_id"] == admin["school_id"]
        and user["role_name"] in SCHOOL_ADMIN_MANAGED_ROLES
        and int(user["security_level"] or 1) < int(admin["security_level"] or 4)
    )


def can_apply_school(admin, school_id):
    if not admin:
        return False
    if admin["role_name"] == "super_admin":
        return school_id is not None
    return school_id == admin["school_id"]


def normalize_status(status):
    return status if status in ACCOUNT_STATUSES else "Active"


def normalize_security_level(role_name, submitted_level, admin):
    role_min, role_max = ROLE_SECURITY_LIMITS.get(role_name, (1, 1))
    try:
        requested = int(submitted_level)
    except (TypeError, ValueError):
        requested = ROLE_SECURITY_DEFAULTS.get(role_name, role_min)
    admin_max = int(admin["security_level"] or ROLE_SECURITY_DEFAULTS.get(admin["role_name"], 1))
    return max(role_min, min(requested, role_max, admin_max))


def password_meets_policy(password):
    password = password or ""
    return (
        len(password) >= 8
        and any(ch.isalpha() for ch in password)
        and any(ch.isdigit() for ch in password)
    )


def setting_specs():
    for group in SETTING_GROUPS:
        for setting in group["settings"]:
            yield group, setting


def ensure_system_settings(conn):
    for group, setting in setting_specs():
        conn.execute("""
            INSERT INTO system_settings
            (setting_key, setting_value, setting_description, setting_category, setting_type)
            SELECT ?, ?, ?, ?, ?
            WHERE NOT EXISTS (SELECT 1 FROM system_settings WHERE setting_key = ?)
        """, (
            setting["key"],
            str(setting["default"]),
            setting["description"],
            group["title"],
            setting["type"],
            setting["key"],
        ))
    conn.commit()


def validate_setting_value(setting, raw_value):
    value = str(raw_value or "").strip()
    if setting["type"] == "select":
        allowed = {option[0] for option in setting["options"]}
        if value not in allowed:
            raise ValueError(f"{setting['label']} has an unsupported option.")
        return value
    if setting["type"] == "number":
        try:
            number = int(value)
        except ValueError as exc:
            raise ValueError(f"{setting['label']} must be a number.") from exc
        if number < setting.get("min", number) or number > setting.get("max", number):
            raise ValueError(
                f"{setting['label']} must be between {setting.get('min')} and {setting.get('max')}."
            )
        return str(number)
    return value[:160]


def grouped_settings(conn):
    rows = {
        row["setting_key"]: row
        for row in conn.execute("SELECT * FROM system_settings").fetchall()
    }
    groups = []
    for group in SETTING_GROUPS:
        display_settings = []
        for setting in group["settings"]:
            row = rows.get(setting["key"])
            display = dict(setting)
            display["value"] = row["setting_value"] if row else str(setting["default"])
            display["updated_at"] = row["updated_at"] if row else None
            display_settings.append(display)
        groups.append({
            "key": group["key"],
            "title": group["title"],
            "summary": group["summary"],
            "settings": display_settings,
        })
    return groups


def validate_account_form(form, creating=True):
    errors = []
    if not form.get("full_name", "").strip():
        errors.append("Full name is required.")
    if creating and not form.get("username", "").strip():
        errors.append("Username is required.")
    if creating and not form.get("password", "").strip():
        errors.append("Temporary password is required.")
    if creating and not password_meets_policy(form.get("password")):
        errors.append("Temporary password must be at least 8 characters and include letters and numbers.")
    if form.get("account_status", "Active") not in ACCOUNT_STATUSES:
        errors.append("Unknown account status.")
    return errors


def admin_summary(conn, school_id=None):
    def one(sql, params=()):
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else 0

    user_where = "WHERE users.school_id = ?" if school_id is not None else ""
    user_params = (school_id,) if school_id is not None else ()
    role_join_scope = "AND users.school_id = ?" if school_id is not None else ""
    role_params = (school_id,) if school_id is not None else ()

    role_counts = conn.execute("""
        SELECT roles.role_name, COUNT(users.user_id) AS total
        FROM roles
        LEFT JOIN users ON users.role_id = roles.role_id
        """ + role_join_scope + """
        GROUP BY roles.role_name
        ORDER BY roles.role_name
    """, role_params).fetchall()

    return {
        "users": one(f"SELECT COUNT(*) FROM users {user_where}", user_params),
        "learners": one("SELECT COUNT(*) FROM users JOIN roles ON users.role_id=roles.role_id WHERE roles.role_name='learner'" + (" AND users.school_id=?" if school_id is not None else ""), user_params),
        "teachers": one("SELECT COUNT(*) FROM users JOIN roles ON users.role_id=roles.role_id WHERE roles.role_name='teacher'" + (" AND users.school_id=?" if school_id is not None else ""), user_params),
        "school_admins": one("SELECT COUNT(*) FROM users JOIN roles ON users.role_id=roles.role_id WHERE roles.role_name='school_admin'" + (" AND users.school_id=?" if school_id is not None else ""), user_params),
        "super_admins": one("SELECT COUNT(*) FROM users JOIN roles ON users.role_id=roles.role_id WHERE roles.role_name='super_admin'" + (" AND users.school_id=?" if school_id is not None else ""), user_params),
        "locked": one("SELECT COUNT(*) FROM users WHERE account_status='Locked'" + (" AND school_id=?" if school_id is not None else ""), user_params),
        "suspended": one("SELECT COUNT(*) FROM users WHERE account_status='Suspended'" + (" AND school_id=?" if school_id is not None else ""), user_params),
        "schools": one("SELECT COUNT(*) FROM schools"),
        "subjects": one("SELECT COUNT(*) FROM subjects"),
        "competencies": one("SELECT COUNT(*) FROM competencies"),
        "outcomes": one("SELECT COUNT(*) FROM learning_outcomes"),
        "courses": one("SELECT COUNT(*) FROM courses"),
        "questions": one("SELECT COUNT(*) FROM questions"),
        "attempts": one("SELECT COUNT(*) FROM assessment_attempts JOIN users ON users.user_id=assessment_attempts.learner_id" + (" WHERE users.school_id=?" if school_id is not None else ""), user_params),
        "recommendations": one("SELECT COUNT(*) FROM recommendations JOIN users ON users.user_id=recommendations.learner_id" + (" WHERE users.school_id=?" if school_id is not None else ""), user_params),
        "role_counts": role_counts,
    }


def available_roles(conn):
    admin = current_admin(conn)
    rows = conn.execute("""
        SELECT role_id, role_name, display_name
        FROM roles
        ORDER BY CASE role_name
            WHEN 'learner' THEN 1
            WHEN 'teacher' THEN 2
            WHEN 'school_admin' THEN 3
            WHEN 'super_admin' THEN 4
            ELSE 5
        END
    """).fetchall()
    return [row for row in rows if can_assign_role(admin, row["role_name"])]


def audit(conn, action, entity_type, entity_id, details):
    ip = request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()
    user_agent = (request.user_agent.string or "unknown")[:120]
    enriched_details = f"{details} | ip={ip} | user_agent={user_agent}"
    conn.execute("""
        INSERT INTO audit_logs (actor_id, action, entity_type, entity_id, details)
        VALUES (?, ?, ?, ?, ?)
    """, (session.get("user_id"), action, entity_type, str(entity_id), enriched_details))


def role_id_for(conn, role_name):
    row = conn.execute("SELECT role_id FROM roles WHERE role_name = ?", (role_name,)).fetchone()
    return row["role_id"] if row else None


def assignment_lists(conn, admin=None):
    scope = school_scope_for(conn, admin)
    school_filter = ""
    params = []
    if scope is not None:
        school_filter = "WHERE school_id = ?"
        params.append(scope)
    return {
        "subjects": conn.execute("SELECT subject_id, subject_name FROM subjects ORDER BY subject_name").fetchall(),
        "classes": conn.execute(f"SELECT class_id, class_name FROM classes {school_filter} ORDER BY class_name", params).fetchall(),
    }


def save_user_assignments(conn, user_id, role_name, school_id, subject_id=None, class_id=None):
    if role_name == "learner" and class_id:
        conn.execute("DELETE FROM enrollments WHERE learner_id = ?", (user_id,))
        conn.execute("INSERT INTO enrollments (learner_id, class_id) VALUES (?, ?) ON CONFLICT DO NOTHING", (user_id, class_id))
    elif role_name == "teacher" and subject_id:
        conn.execute("DELETE FROM teacher_subject_assignments WHERE teacher_id = ?", (user_id,))
        conn.execute("""
            INSERT INTO teacher_subject_assignments
            (teacher_id, subject_id, class_id, school_id, assigned_by)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT DO NOTHING
        """, (user_id, subject_id, class_id, school_id, session.get("user_id")))


QUESTION_TYPES = (
    "multiple_choice",
    "short_answer",
    "fill_blank",
    "matching",
    "practical_task",
    "coding_task",
    "investigation_task",
    "reflection_question",
)
BLOOM_LEVELS = ("Remember", "Understand", "Apply", "Analyse", "Evaluate", "Create")
DIFFICULTY_LEVELS = ("basic", "standard", "intermediate", "advanced")


def question_form_lists(conn):
    return {
        "assessments": conn.execute("""
            SELECT a.assessment_id, a.assessment_title, a.assessment_type,
                   lo.outcome_code, lo.outcome_name, subjects.subject_name
            FROM assessments a
            JOIN lessons l ON l.lesson_id=a.lesson_id
            JOIN learning_outcomes lo ON lo.outcome_id=l.outcome_id
            JOIN competencies c ON c.competency_id=lo.competency_id
            JOIN subjects ON subjects.subject_id=c.subject_id
            ORDER BY subjects.subject_name, lo.sequence_order, a.assessment_type
        """).fetchall(),
        "concepts": conn.execute("""
            SELECT concepts.*, lo.outcome_code, subjects.subject_name
            FROM concepts
            JOIN learning_outcomes lo ON lo.outcome_id=concepts.outcome_id
            JOIN competencies c ON c.competency_id=lo.competency_id
            JOIN subjects ON subjects.subject_id=c.subject_id
            ORDER BY subjects.subject_name, lo.sequence_order, concepts.concept_tag
        """).fetchall(),
        "question_types": QUESTION_TYPES,
        "bloom_levels": BLOOM_LEVELS,
        "difficulty_levels": DIFFICULTY_LEVELS,
    }


def metadata_for_assessment(conn, assessment_id, concept_tag=None):
    row = conn.execute("""
        SELECT a.assessment_id, lo.outcome_id, lo.topic_id, lo.competency_id, c.subject_id
        FROM assessments a
        JOIN lessons l ON l.lesson_id=a.lesson_id
        JOIN learning_outcomes lo ON lo.outcome_id=l.outcome_id
        JOIN competencies c ON c.competency_id=lo.competency_id
        WHERE a.assessment_id=?
    """, (assessment_id,)).fetchone()
    if not row:
        return None
    concept = None
    if concept_tag:
        concept = conn.execute("""
            SELECT concept_id
            FROM concepts
            WHERE outcome_id=? AND concept_tag=?
        """, (row["outcome_id"], concept_tag)).fetchone()
    return {
        "subject_id": row["subject_id"],
        "topic_id": row["topic_id"],
        "learning_outcome_id": row["outcome_id"],
        "competency_id": row["competency_id"],
        "concept_id": concept["concept_id"] if concept else None,
    }


def save_question_options(conn, question_id, form):
    conn.execute("DELETE FROM question_options WHERE question_id=?", (question_id,))
    options = [
        form.get("option_a", "").strip(),
        form.get("option_b", "").strip(),
        form.get("option_c", "").strip(),
        form.get("option_d", "").strip(),
    ]
    correct = (form.get("correct_option") or "A").upper()
    labels = ("A", "B", "C", "D")
    for label, text in zip(labels, options):
        if not text:
            continue
        conn.execute("""
            INSERT INTO question_options (question_id, option_text, is_correct)
            VALUES (?, ?, ?)
        """, (question_id, text, 1 if label == correct else 0))


@admin_bp.app_template_global()
def security_label(level):
    labels = {
        1: "Learner Access",
        2: "Support Access",
        3: "Teacher Access",
        4: "School Administration",
        5: "System Ownership",
    }
    return labels.get(int(level or 1), "Custom Access")


@admin_bp.route("/admin")
@role_required("school_admin", "super_admin")
def admin_dashboard():
    conn = get_db()
    admin = current_admin(conn)
    scope = school_scope_for(conn, admin)
    summary = admin_summary(conn, scope)
    params = []
    where = ""
    if scope is not None:
        where = "WHERE users.school_id = ?"
        params.append(scope)
    recent_users = conn.execute("""
        SELECT users.full_name, users.username, users.email, roles.role_name, schools.school_name,
               users.account_status, users.security_level, users.last_login_at, users.created_at
        FROM users
        JOIN roles ON users.role_id = roles.role_id
        LEFT JOIN schools ON users.school_id = schools.school_id
        """ + where + """
        ORDER BY users.created_at DESC
        LIMIT 8
    """, params).fetchall()
    conn.close()
    return render_template("admin/dashboard.html", summary=summary, recent_users=recent_users)


@admin_bp.route("/admin/users")
@role_required("school_admin", "super_admin")
def users():
    conn = get_db()
    admin = current_admin(conn)
    role_filter = request.args.get("role", "")
    status_filter = request.args.get("status", "")
    search = request.args.get("q", "").strip()
    params = []
    clauses = ["1=1"]
    scope = school_scope_for(conn, admin)

    if scope is not None:
        clauses.append("users.school_id = ?")
        params.append(scope)
        clauses.append("roles.role_name IN ('learner', 'teacher')")
    if role_filter:
        clauses.append("roles.role_name = ?")
        params.append(role_filter)
    if status_filter:
        clauses.append("users.account_status = ?")
        params.append(status_filter)
    if search:
        clauses.append("(users.full_name LIKE ? OR users.username LIKE ? OR users.email LIKE ?)")
        params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

    rows = conn.execute(f"""
        SELECT users.user_id, users.full_name, users.username, users.email, users.phone, users.title,
               users.account_status, users.security_level, users.must_change_password,
               users.failed_login_attempts, users.locked_until, users.last_login_at, users.created_at,
               roles.role_name, roles.display_name, schools.school_name
        FROM users
        JOIN roles ON users.role_id = roles.role_id
        LEFT JOIN schools ON users.school_id = schools.school_id
        WHERE {" AND ".join(clauses)}
        ORDER BY users.security_level DESC, roles.role_name, users.full_name
    """, params).fetchall()
    roles = available_roles(conn)
    schools = managed_schools(conn, admin)
    conn.close()
    return render_template(
        "admin/users.html",
        users=rows,
        roles=roles,
        schools=schools,
        statuses=ACCOUNT_STATUSES,
        role_filter=role_filter,
        status_filter=status_filter,
        search=search,
    )


@admin_bp.route("/admin/users/create", methods=["GET", "POST"])
@role_required("school_admin", "super_admin")
@csrf_protect
def create_user():
    conn = get_db()
    admin = current_admin(conn)
    roles = available_roles(conn)
    schools = managed_schools(conn, admin)
    assignments = assignment_lists(conn, admin)
    allowed_role_names = {role["role_name"] for role in roles}

    if request.method == "POST":
        role_name = request.form.get("role_name", "learner")
        school_id = int(request.form.get("school_id") or 0) or None
        errors = validate_account_form(request.form, creating=True)
        if errors:
            for error in errors:
                flash(error, "danger")
            conn.close()
            return redirect(url_for("admin.create_user"))
        if role_name not in allowed_role_names or not can_apply_school(admin, school_id):
            conn.close()
            flash("You do not have permission to create that account.", "danger")
            return redirect(url_for("admin.users"))

        try:
            status = normalize_status(request.form.get("account_status", "Active"))
            security_level = normalize_security_level(role_name, request.form.get("security_level"), admin)
            cur = conn.execute("""
                INSERT INTO users
                (full_name, username, email, phone, title, password_hash, role_id, school_id,
                 account_status, security_level, must_change_password, approved_by, approved_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                request.form.get("full_name", "").strip(),
                request.form.get("username", "").strip(),
                request.form.get("email", "").strip() or None,
                request.form.get("phone", "").strip() or None,
                request.form.get("title", "").strip() or None,
                generate_password_hash(request.form.get("password") or "ChangeMe123!"),
                role_id_for(conn, role_name),
                school_id,
                status,
                security_level,
                1 if request.form.get("must_change_password") else 0,
                session.get("user_id"),
            ))
            user_id = cur.lastrowid
            save_user_assignments(
                conn,
                user_id,
                role_name,
                school_id,
                int(request.form.get("subject_id") or 0) or None,
                int(request.form.get("class_id") or 0) or None,
            )
            audit(conn, "CREATE_USER", "user", user_id, f"Created {role_name} account with security level {security_level}")
            conn.commit()
            flash("Account created and recorded in the audit trail.", "success")
            return redirect(url_for("admin.users"))
        except DatabaseIntegrityError:
            conn.rollback()
            flash("Could not create account because the username or email already exists.", "danger")

    conn.close()
    return render_template(
        "admin/user_form.html",
        user=None,
        roles=roles,
        schools=schools,
        subjects=assignments["subjects"],
        classes=assignments["classes"],
        assigned_subject_id=None,
        assigned_class_id=None,
        statuses=ACCOUNT_STATUSES,
        defaults=ROLE_SECURITY_DEFAULTS,
    )


@admin_bp.route("/admin/users/<int:user_id>/edit", methods=["GET", "POST"])
@role_required("school_admin", "super_admin")
@csrf_protect
def edit_user(user_id):
    conn = get_db()
    admin = current_admin(conn)
    user = conn.execute("""
        SELECT users.*, roles.role_name, roles.display_name, schools.school_name
        FROM users
        JOIN roles ON users.role_id = roles.role_id
        LEFT JOIN schools ON users.school_id = schools.school_id
        WHERE users.user_id = ?
    """, (user_id,)).fetchone()
    if not can_manage_user(admin, user):
        conn.close()
        flash("Account not found or outside your management scope.", "danger")
        return redirect(url_for("admin.users"))

    roles = available_roles(conn)
    schools = managed_schools(conn, admin)
    assignments = assignment_lists(conn, admin)
    assigned_subject = conn.execute("""
        SELECT subject_id FROM teacher_subject_assignments
        WHERE teacher_id = ?
        ORDER BY assigned_at DESC LIMIT 1
    """, (user_id,)).fetchone()
    assigned_class = conn.execute("""
        SELECT class_id FROM enrollments
        WHERE learner_id = ?
        ORDER BY enrolled_at DESC LIMIT 1
    """, (user_id,)).fetchone()
    allowed_role_names = {role["role_name"] for role in roles}

    if request.method == "POST":
        role_name = request.form.get("role_name", user["role_name"])
        school_id = int(request.form.get("school_id") or 0) or None
        errors = validate_account_form(request.form, creating=False)
        if errors:
            for error in errors:
                flash(error, "danger")
            conn.close()
            return redirect(url_for("admin.edit_user", user_id=user_id))
        if role_name not in allowed_role_names or not can_apply_school(admin, school_id):
            conn.close()
            flash("You do not have permission to apply that role or school.", "danger")
            return redirect(url_for("admin.edit_user", user_id=user_id))
        if user_id == session.get("user_id") and (
            role_name != user["role_name"]
            or normalize_status(request.form.get("account_status", "Active")) != user["account_status"]
        ):
            conn.close()
            flash("You cannot change your own role or account status from this screen.", "danger")
            return redirect(url_for("admin.edit_user", user_id=user_id))

        status = normalize_status(request.form.get("account_status", "Active"))
        security_level = normalize_security_level(role_name, request.form.get("security_level"), admin)
        try:
            conn.execute("""
                UPDATE users
                SET full_name = ?, email = ?, phone = ?, title = ?, role_id = ?, school_id = ?,
                    account_status = ?, security_level = ?, must_change_password = ?
                WHERE user_id = ?
            """, (
                request.form.get("full_name", "").strip(),
                request.form.get("email", "").strip() or None,
                request.form.get("phone", "").strip() or None,
                request.form.get("title", "").strip() or None,
                role_id_for(conn, role_name),
                school_id,
                status,
                security_level,
                1 if request.form.get("must_change_password") else 0,
                user_id,
            ))
            save_user_assignments(
                conn,
                user_id,
                role_name,
                school_id,
                int(request.form.get("subject_id") or 0) or None,
                int(request.form.get("class_id") or 0) or None,
            )
            audit(conn, "UPDATE_USER", "user", user_id, f"Edited account profile, status={status}, security_level={security_level}")
            conn.commit()
            conn.close()
            flash("Account updated.", "success")
            return redirect(url_for("admin.users"))
        except DatabaseIntegrityError:
            conn.rollback()
            conn.close()
            flash("Could not update account because that email is already used.", "danger")
            return redirect(url_for("admin.edit_user", user_id=user_id))

    conn.close()
    return render_template(
        "admin/user_form.html",
        user=user,
        roles=roles,
        schools=schools,
        subjects=assignments["subjects"],
        classes=assignments["classes"],
        assigned_subject_id=assigned_subject["subject_id"] if assigned_subject else None,
        assigned_class_id=assigned_class["class_id"] if assigned_class else None,
        statuses=ACCOUNT_STATUSES,
        defaults=ROLE_SECURITY_DEFAULTS,
    )


@admin_bp.route("/admin/users/<int:user_id>/reset-password", methods=["POST"])
@role_required("school_admin", "super_admin")
@csrf_protect
def reset_password(user_id):
    new_password = request.form.get("new_password") or "ChangeMe123!"
    if not password_meets_policy(new_password):
        flash("Temporary password must be at least 8 characters and include letters and numbers.", "danger")
        return redirect(url_for("admin.users"))
    conn = get_db()
    admin = current_admin(conn)
    user = conn.execute("""
        SELECT users.user_id, users.school_id, users.security_level, roles.role_name
        FROM users
        JOIN roles ON roles.role_id = users.role_id
        WHERE users.user_id = ?
    """, (user_id,)).fetchone()
    if user_id == session.get("user_id") or not can_manage_user(admin, user):
        conn.close()
        flash("Account not found or outside your management scope.", "danger")
        return redirect(url_for("admin.users"))
    conn.execute("""
        UPDATE users
        SET password_hash = ?, must_change_password = 1, failed_login_attempts = 0,
            locked_until = NULL, account_status = 'Active'
        WHERE user_id = ?
    """, (generate_password_hash(new_password), user_id))
    audit(conn, "RESET_PASSWORD", "user", user_id, "Password reset and account unlocked")
    conn.commit()
    conn.close()
    flash("Password reset. The user should change it after login.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/admin/users/<int:user_id>/status/<action>", methods=["POST"])
@role_required("school_admin", "super_admin")
@csrf_protect
def update_user_status(user_id, action):
    status_map = {
        "activate": "Active",
        "suspend": "Suspended",
        "lock": "Locked",
        "pending": "Pending",
    }
    if action not in status_map:
        flash("Unknown account action.", "danger")
        return redirect(url_for("admin.users"))
    conn = get_db()
    admin = current_admin(conn)
    user = conn.execute("""
        SELECT users.user_id, users.school_id, users.security_level, roles.role_name
        FROM users
        JOIN roles ON roles.role_id = users.role_id
        WHERE users.user_id = ?
    """, (user_id,)).fetchone()
    if user_id == session.get("user_id") or not can_manage_user(admin, user):
        conn.close()
        flash("Account not found or outside your management scope.", "danger")
        return redirect(url_for("admin.users"))
    locked_until = None
    if status_map[action] == "Locked":
        locked_until = (datetime.utcnow() + timedelta(days=1)).isoformat(timespec="seconds")
    conn.execute("""
        UPDATE users
        SET account_status = ?,
            locked_until = ?,
            failed_login_attempts = CASE WHEN ? = 'Active' THEN 0 ELSE failed_login_attempts END
        WHERE user_id = ?
    """, (status_map[action], locked_until, status_map[action], user_id))
    audit(conn, "UPDATE_STATUS", "user", user_id, f"Changed status to {status_map[action]}")
    conn.commit()
    conn.close()
    flash(f"Account marked {status_map[action]}.", "success")
    return redirect(url_for("admin.users"))


@admin_bp.route("/admin/users/<int:user_id>/report")
@role_required("school_admin", "super_admin")
def user_report(user_id):
    conn = get_db()
    admin = current_admin(conn)
    user = conn.execute("""
        SELECT users.*, roles.role_name, roles.display_name, schools.school_name
        FROM users
        JOIN roles ON users.role_id = roles.role_id
        LEFT JOIN schools ON users.school_id = schools.school_id
        WHERE users.user_id = ?
    """, (user_id,)).fetchone()
    if not can_manage_user(admin, user) and user_id != session.get("user_id"):
        conn.close()
        flash("Report not found or outside your management scope.", "danger")
        return redirect(url_for("admin.reports"))

    mastery = conn.execute("""
        SELECT subjects.subject_name, learning_outcomes.outcome_code, learning_outcomes.outcome_name,
               mastery_records.pretest_score, mastery_records.practice_score,
               mastery_records.posttest_score, mastery_records.mastery_score,
               mastery_records.mastery_level, mastery_records.mastery_status,
               mastery_records.updated_at
        FROM mastery_records
        JOIN learning_outcomes ON mastery_records.outcome_id = learning_outcomes.outcome_id
        JOIN competencies ON learning_outcomes.competency_id = competencies.competency_id
        JOIN subjects ON competencies.subject_id = subjects.subject_id
        WHERE mastery_records.learner_id = ?
        ORDER BY subjects.subject_name, learning_outcomes.sequence_order
    """, (user_id,)).fetchall()
    attempts = conn.execute("""
        SELECT assessments.assessment_type, assessments.assessment_title, assessment_attempts.score,
               assessment_attempts.weak_concepts, assessment_attempts.attempted_at
        FROM assessment_attempts
        JOIN assessments ON assessment_attempts.assessment_id = assessments.assessment_id
        WHERE assessment_attempts.learner_id = ?
        ORDER BY assessment_attempts.attempted_at DESC
        LIMIT 20
    """, (user_id,)).fetchall()
    recommendations = conn.execute("""
        SELECT recommendation_reason, recommendation_type, weak_concepts, strong_concepts,
               expected_mastery, teacher_status, created_at
        FROM recommendations
        WHERE learner_id = ?
        ORDER BY created_at DESC
        LIMIT 12
    """, (user_id,)).fetchall()
    interventions = conn.execute("""
        SELECT teacher_interventions.*, learner.full_name AS learner_name,
               learning_outcomes.outcome_code
        FROM teacher_interventions
        JOIN users AS learner ON learner.user_id = teacher_interventions.learner_id
        JOIN learning_outcomes ON learning_outcomes.outcome_id = teacher_interventions.outcome_id
        WHERE teacher_interventions.teacher_id = ? OR teacher_interventions.learner_id = ?
        ORDER BY teacher_interventions.created_at DESC
        LIMIT 20
    """, (user_id, user_id)).fetchall()
    evidence = conn.execute("""
        SELECT practical_evidence.*, learning_outcomes.outcome_code
        FROM practical_evidence
        JOIN learning_outcomes ON learning_outcomes.outcome_id = practical_evidence.outcome_id
        WHERE practical_evidence.learner_id = ?
        ORDER BY practical_evidence.created_at DESC
        LIMIT 20
    """, (user_id,)).fetchall()
    audit_rows = conn.execute("""
        SELECT action, entity_type, entity_id, details, created_at
        FROM audit_logs
        WHERE actor_id = ? OR entity_id = ?
        ORDER BY created_at DESC
        LIMIT 25
    """, (user_id, str(user_id))).fetchall()
    conn.close()
    return render_template(
        "admin/user_report.html",
        user=user,
        mastery=mastery,
        attempts=attempts,
        recommendations=recommendations,
        interventions=interventions,
        evidence=evidence,
        audit_rows=audit_rows,
    )


@admin_bp.route("/admin/schools/<int:school_id>/report")
@role_required("school_admin", "super_admin")
def school_report(school_id):
    conn = get_db()
    admin = current_admin(conn)
    if not can_apply_school(admin, school_id):
        conn.close()
        flash("School report outside your management scope.", "danger")
        return redirect(url_for("admin.reports"))
    school = conn.execute("SELECT * FROM schools WHERE school_id = ?", (school_id,)).fetchone()
    if not school:
        conn.close()
        flash("School report not found.", "danger")
        return redirect(url_for("admin.reports"))
    role_counts = conn.execute("""
        SELECT roles.display_name, COUNT(users.user_id) AS total
        FROM roles
        LEFT JOIN users ON users.role_id = roles.role_id AND users.school_id = ?
        GROUP BY roles.role_id
        ORDER BY roles.role_name
    """, (school_id,)).fetchall()
    mastery = conn.execute("""
        SELECT subjects.subject_name, ROUND(CAST(AVG(mastery_records.mastery_score) AS NUMERIC), 1) AS avg_mastery,
               COUNT(mastery_records.mastery_id) AS records,
               SUM(CASE WHEN mastery_records.mastery_status='Mastered' THEN 1 ELSE 0 END) AS mastered
        FROM subjects
        LEFT JOIN competencies ON competencies.subject_id = subjects.subject_id
        LEFT JOIN learning_outcomes ON learning_outcomes.competency_id = competencies.competency_id
        LEFT JOIN mastery_records ON mastery_records.outcome_id = learning_outcomes.outcome_id
             AND mastery_records.learner_id IN (SELECT user_id FROM users WHERE school_id = ?)
        GROUP BY subjects.subject_id
        ORDER BY subjects.subject_name
    """, (school_id,)).fetchall()
    users = conn.execute("""
        SELECT users.user_id, users.full_name, users.username, users.account_status,
               users.security_level, roles.role_name, roles.display_name
        FROM users
        JOIN roles ON roles.role_id = users.role_id
        WHERE users.school_id = ?
        ORDER BY users.security_level DESC, users.full_name
    """, (school_id,)).fetchall()
    conn.close()
    return render_template("admin/school_report.html", school=school, role_counts=role_counts, mastery=mastery, users=users)


@admin_bp.route("/admin/schools", methods=["GET", "POST"])
@role_required("school_admin", "super_admin")
@csrf_protect
def schools():
    conn = get_db()
    admin = current_admin(conn)
    if request.method == "POST":
        if admin["role_name"] != "super_admin":
            conn.close()
            flash("Only the Super Administrator can add schools.", "danger")
            return redirect(url_for("admin.schools"))
        school_name = request.form.get("school_name", "").strip()
        if school_name:
            conn.execute("INSERT INTO schools (school_name) VALUES (?) ON CONFLICT DO NOTHING", (school_name,))
            audit(conn, "CREATE_SCHOOL", "school", school_name, "Added school")
            conn.commit()
            flash("School saved.", "success")
        conn.close()
        return redirect(url_for("admin.schools"))
    scope = school_scope_for(conn, admin)
    params = []
    where = ""
    if scope is not None:
        where = "WHERE schools.school_id = ?"
        params.append(scope)
    rows = conn.execute(f"""
        SELECT schools.school_id, schools.school_name,
               COUNT(DISTINCT classes.class_id) AS classes,
               COUNT(DISTINCT users.user_id) AS users
        FROM schools
        LEFT JOIN classes ON classes.school_id = schools.school_id
        LEFT JOIN users ON users.school_id = schools.school_id
        {where}
        GROUP BY schools.school_id
        ORDER BY schools.school_name
    """, params).fetchall()
    conn.close()
    return render_template("admin/schools.html", schools=rows, can_add_school=admin["role_name"] == "super_admin")


@admin_bp.route("/admin/roles")
@role_required("school_admin", "super_admin")
def roles():
    conn = get_db()
    rows = conn.execute("""
        SELECT roles.display_name, roles.role_name,
               COUNT(users.user_id) AS users
        FROM roles
        LEFT JOIN users ON users.role_id = roles.role_id
        GROUP BY roles.role_id
        ORDER BY CASE roles.role_name
            WHEN 'super_admin' THEN 1
            WHEN 'school_admin' THEN 2
            WHEN 'teacher' THEN 3
            ELSE 4
        END
    """).fetchall()
    permissions = {
        "super_admin": "Manage schools, administrators, curriculum, AI configuration, analytics, audit logs, backups and global settings.",
        "school_admin": "Manage school users, teachers, learners, school reports, password resets and school analytics.",
        "teacher": "Manage learner support, resources, question banks, practical evidence, AI reviews, remediation and class analytics.",
        "learner": "Complete adaptive learning, assessments, reflections, evidence uploads and competency portfolio work.",
    }
    conn.close()
    return render_template("admin/roles.html", roles=rows, permissions=permissions)


@admin_bp.route("/admin/backups", methods=["GET", "POST"])
@role_required("school_admin", "super_admin")
@csrf_protect
def backups():
    conn = get_db()
    admin = current_admin(conn)
    if request.method == "POST":
        if admin["role_name"] != "super_admin":
            conn.close()
            flash("Only the Super Administrator can create backup records.", "danger")
            return redirect(url_for("admin.backups"))
        backup_name = request.form.get("backup_name") or "Manual SQLite backup record"
        conn.execute("""
            INSERT INTO backups (backup_name, backup_type, backup_status, file_path, created_by)
            VALUES (?, 'manual', 'Recorded', ?, ?)
        """, (backup_name, "learn2master.db", session.get("user_id")))
        audit(conn, "CREATE_BACKUP_RECORD", "backup", "manual", backup_name)
        conn.commit()
        flash("Backup record created. Copy the SQLite file using your deployment backup process.", "success")
        return redirect(url_for("admin.backups"))
    rows = conn.execute("SELECT * FROM backups ORDER BY created_at DESC").fetchall()
    cached = conn.execute("SELECT * FROM cached_resources ORDER BY created_at DESC").fetchall()
    sync = conn.execute("SELECT * FROM offline_sync_queue ORDER BY created_at DESC LIMIT 50").fetchall()
    conn.close()
    return render_template("admin/backups.html", backups=rows, cached=cached, sync=sync, can_create_backup=admin["role_name"] == "super_admin")


@admin_bp.route("/admin/curriculum", methods=["GET", "POST"])
@role_required("school_admin", "super_admin")
@csrf_protect
def curriculum():
    conn = get_db()
    admin = current_admin(conn)
    if request.method == "POST":
        if admin["role_name"] != "super_admin":
            conn.close()
            flash("Only the Super Administrator can change system-wide curriculum.", "danger")
            return redirect(url_for("admin.curriculum"))
        action = request.form.get("curriculum_action")
        if action == "add_subject":
            subject_name = request.form.get("subject_name", "").strip()
            if subject_name:
                conn.execute("INSERT INTO subjects (subject_name) VALUES (?) ON CONFLICT DO NOTHING", (subject_name,))
                audit(conn, "CURRICULUM_ADD_SUBJECT", "subject", subject_name, "Added curriculum subject")
        elif action == "add_topic":
            conn.execute("""
                INSERT INTO topics (subject_id, term_id, topic_title, class_level, curriculum_source, topic_description)
                VALUES (?, ?, ?, ?, 'Uganda NCDC CBC', ?)
            """, (
                request.form.get("subject_id"),
                request.form.get("term_id") or None,
                request.form.get("topic_title", "").strip(),
                request.form.get("class_level", "Senior One"),
                request.form.get("topic_description", "").strip(),
            ))
            audit(conn, "CURRICULUM_ADD_TOPIC", "topic", request.form.get("topic_title"), "Added CBC topic")
        elif action == "add_outcome":
            conn.execute("""
                INSERT INTO learning_outcomes
                (competency_id, topic_id, outcome_code, outcome_name, outcome_description,
                 mastery_threshold, practical_required, teacher_review_required, sequence_order)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                request.form.get("competency_id"),
                request.form.get("topic_id") or None,
                request.form.get("outcome_code", "").strip(),
                request.form.get("outcome_name", "").strip(),
                request.form.get("outcome_description", "").strip(),
                int(request.form.get("mastery_threshold") or 80),
                1 if request.form.get("practical_required") else 0,
                1 if request.form.get("teacher_review_required") else 0,
                int(request.form.get("sequence_order") or 1),
            ))
            audit(conn, "CURRICULUM_ADD_OUTCOME", "learning_outcome", request.form.get("outcome_code"), "Added CBC learning outcome")
        elif action == "add_indicator":
            conn.execute("""
                INSERT INTO performance_indicators (outcome_id, indicator_text)
                VALUES (?, ?)
            """, (request.form.get("outcome_id"), request.form.get("indicator_text", "").strip()))
            audit(conn, "CURRICULUM_ADD_INDICATOR", "learning_outcome", request.form.get("outcome_id"), "Added performance indicator")
        elif action == "add_success_criterion":
            conn.execute("""
                INSERT INTO success_criteria (outcome_id, criteria_text)
                VALUES (?, ?)
            """, (request.form.get("outcome_id"), request.form.get("criteria_text", "").strip()))
            audit(conn, "CURRICULUM_ADD_SUCCESS_CRITERION", "learning_outcome", request.form.get("outcome_id"), "Added success criterion")
        conn.commit()
        conn.close()
        flash("Curriculum update saved and audited.", "success")
        return redirect(url_for("admin.curriculum"))

    rows = conn.execute("""
        SELECT subjects.subject_name, courses.course_title, competencies.competency_code,
               competencies.competency_name, learning_outcomes.outcome_code,
               learning_outcomes.outcome_name, learning_outcomes.mastery_threshold,
               learning_outcomes.sequence_order, learning_outcomes.practical_required,
               learning_outcomes.teacher_review_required,
               COUNT(DISTINCT performance_indicators.indicator_id) AS indicators,
               COUNT(DISTINCT success_criteria.criteria_id) AS success_criteria
        FROM learning_outcomes
        JOIN competencies ON learning_outcomes.competency_id = competencies.competency_id
        JOIN subjects ON competencies.subject_id = subjects.subject_id
        LEFT JOIN lessons ON lessons.outcome_id = learning_outcomes.outcome_id
        LEFT JOIN courses ON lessons.course_id = courses.course_id
        LEFT JOIN performance_indicators ON performance_indicators.outcome_id = learning_outcomes.outcome_id
        LEFT JOIN success_criteria ON success_criteria.outcome_id = learning_outcomes.outcome_id
        GROUP BY learning_outcomes.outcome_id
        ORDER BY subjects.subject_name, learning_outcomes.sequence_order
    """).fetchall()
    subjects = conn.execute("SELECT * FROM subjects ORDER BY subject_name").fetchall()
    terms = conn.execute("SELECT * FROM terms ORDER BY sequence_order").fetchall()
    topics = conn.execute("SELECT topics.*, subjects.subject_name FROM topics JOIN subjects ON topics.subject_id=subjects.subject_id ORDER BY subjects.subject_name, topic_title").fetchall()
    competencies = conn.execute("SELECT competencies.*, subjects.subject_name FROM competencies JOIN subjects ON competencies.subject_id=subjects.subject_id ORDER BY subjects.subject_name, competency_code").fetchall()
    outcomes = conn.execute("SELECT outcome_id, outcome_code, outcome_name FROM learning_outcomes ORDER BY outcome_code").fetchall()
    conn.close()
    return render_template(
        "admin/curriculum.html",
        rows=rows,
        subjects=subjects,
        terms=terms,
        topics=topics,
        competencies=competencies,
        outcomes=outcomes,
        can_edit=admin["role_name"] == "super_admin",
    )


@admin_bp.route("/admin/competencies")
@role_required("school_admin", "super_admin")
def competencies():
    conn = get_db()
    rows = conn.execute("""
        SELECT subjects.subject_name, competencies.competency_code, competencies.competency_name,
               competencies.competency_description, COUNT(learning_outcomes.outcome_id) AS outcomes
        FROM competencies
        JOIN subjects ON competencies.subject_id = subjects.subject_id
        LEFT JOIN learning_outcomes ON learning_outcomes.competency_id = competencies.competency_id
        GROUP BY competencies.competency_id
        ORDER BY subjects.subject_name, competencies.competency_code
    """).fetchall()
    conn.close()
    return render_template("admin/competencies.html", rows=rows)


@admin_bp.route("/admin/teachers")
@role_required("school_admin", "super_admin")
def teachers():
    return redirect(url_for("admin.users", role="teacher"))


@admin_bp.route("/admin/learners")
@role_required("school_admin", "super_admin")
def learners():
    return redirect(url_for("admin.users", role="learner"))


@admin_bp.route("/admin/learning-resources")
@role_required("school_admin", "super_admin")
def learning_resources():
    conn = get_db()
    rows = conn.execute("""
        SELECT lr.*, lo.outcome_code, lo.outcome_name, subjects.subject_name
        FROM learning_resources lr
        JOIN learning_outcomes lo ON lo.outcome_id=lr.outcome_id
        JOIN competencies c ON c.competency_id=lo.competency_id
        JOIN subjects ON subjects.subject_id=c.subject_id
        ORDER BY subjects.subject_name, lo.sequence_order, lr.resource_type, lr.resource_title
        LIMIT 250
    """).fetchall()
    conn.close()
    return render_template("admin/learning_resources.html", rows=rows)


@admin_bp.route("/admin/rubrics")
@role_required("school_admin", "super_admin")
def rubrics():
    conn = get_db()
    rows = conn.execute("""
        SELECT rc.*, lo.outcome_code, lo.outcome_name, subjects.subject_name
        FROM rubric_criteria rc
        JOIN learning_outcomes lo ON lo.outcome_id=rc.outcome_id
        JOIN competencies c ON c.competency_id=lo.competency_id
        JOIN subjects ON subjects.subject_id=c.subject_id
        ORDER BY subjects.subject_name, lo.sequence_order,
                 CASE rc.level
                    WHEN 'Beginning' THEN 1
                    WHEN 'Developing' THEN 2
                    WHEN 'Proficient' THEN 3
                    WHEN 'Advanced' THEN 4
                    ELSE 5
                 END
    """).fetchall()
    conn.close()
    return render_template("admin/rubrics.html", rows=rows)


@admin_bp.route("/admin/questions", endpoint="questions")
@admin_bp.route("/admin/question-bank")
@role_required("school_admin", "super_admin")
def question_bank():
    conn = get_db()
    rows = conn.execute("""
        SELECT questions.question_id, subjects.subject_name, assessments.assessment_type,
               assessments.assessment_title, lo.outcome_code, lo.outcome_name,
               questions.question_text, questions.concept_tag, questions.question_type,
               questions.difficulty_level, questions.bloom_level, questions.feedback,
               questions.resource_link, questions.estimated_time, questions.marks,
               COUNT(question_options.option_id) AS options
        FROM questions
        JOIN assessments ON questions.assessment_id = assessments.assessment_id
        JOIN lessons ON assessments.lesson_id = lessons.lesson_id
        JOIN learning_outcomes lo ON lo.outcome_id=lessons.outcome_id
        JOIN courses ON lessons.course_id = courses.course_id
        JOIN subjects ON courses.subject_id = subjects.subject_id
        LEFT JOIN question_options ON question_options.question_id=questions.question_id
        GROUP BY questions.question_id
        ORDER BY subjects.subject_name, assessments.assessment_type, questions.concept_tag, questions.question_id
        LIMIT 200
    """).fetchall()
    conn.close()
    return render_template("admin/question_bank.html", rows=rows)


@admin_bp.route("/admin/question-bank/create", methods=["GET", "POST"])
@role_required("school_admin", "super_admin")
@csrf_protect
def create_question():
    conn = get_db()
    if request.method == "POST":
        assessment_id = request.form.get("assessment_id")
        concept_tag = request.form.get("concept_tag", "").strip()
        meta = metadata_for_assessment(conn, assessment_id, concept_tag)
        if not meta:
            conn.close()
            flash("Select a valid assessment before saving the question.", "danger")
            return redirect(url_for("admin.create_question"))
        question_type = request.form.get("question_type") or "multiple_choice"
        if question_type not in QUESTION_TYPES:
            question_type = "multiple_choice"
        bloom_level = request.form.get("bloom_level") or "Understand"
        if bloom_level not in BLOOM_LEVELS:
            bloom_level = "Understand"
        cur = conn.execute("""
            INSERT INTO questions
            (assessment_id, subject_id, topic_id, learning_outcome_id, competency_id, concept_id,
             question_text, concept_tag, difficulty_level, question_type, marks, correct_answer,
             bloom_level, explanation, feedback, resource_link, resource_hint,
             estimated_time_minutes, estimated_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            assessment_id,
            meta["subject_id"],
            meta["topic_id"],
            meta["learning_outcome_id"],
            meta["competency_id"],
            meta["concept_id"],
            request.form.get("question_text", "").strip(),
            concept_tag,
            request.form.get("difficulty_level") or "standard",
            question_type,
            int(request.form.get("marks") or 1),
            request.form.get("correct_answer", "").strip(),
            bloom_level,
            request.form.get("explanation", "").strip(),
            request.form.get("feedback", "").strip(),
            request.form.get("resource_link", "").strip(),
            request.form.get("resource_link", "").strip(),
            int(request.form.get("estimated_time") or 2),
            int(request.form.get("estimated_time") or 2),
        ))
        question_id = cur.lastrowid
        if question_type == "multiple_choice":
            save_question_options(conn, question_id, request.form)
        audit(conn, "CREATE_QUESTION", "question", question_id, "Created metadata-rich CBC question bank item")
        conn.commit()
        conn.close()
        flash("Question created with CBC/AI metadata.", "success")
        return redirect(url_for("admin.question_bank"))
    lists = question_form_lists(conn)
    conn.close()
    return render_template("admin/question_form.html", question=None, **lists)


@admin_bp.route("/admin/question-bank/<int:question_id>/edit", methods=["GET", "POST"])
@role_required("school_admin", "super_admin")
@csrf_protect
def edit_question(question_id):
    conn = get_db()
    question = conn.execute("SELECT * FROM questions WHERE question_id=?", (question_id,)).fetchone()
    if not question:
        conn.close()
        flash("Question was not found.", "warning")
        return redirect(url_for("admin.question_bank"))
    if request.method == "POST":
        assessment_id = request.form.get("assessment_id")
        concept_tag = request.form.get("concept_tag", "").strip()
        meta = metadata_for_assessment(conn, assessment_id, concept_tag)
        if not meta:
            conn.close()
            flash("Select a valid assessment before saving the question.", "danger")
            return redirect(url_for("admin.edit_question", question_id=question_id))
        conn.execute("""
            UPDATE questions
            SET assessment_id=?, subject_id=?, topic_id=?, learning_outcome_id=?,
                competency_id=?, concept_id=?, question_text=?, concept_tag=?,
                difficulty_level=?, question_type=?, marks=?, correct_answer=?,
                bloom_level=?, explanation=?, feedback=?, resource_link=?,
                resource_hint=?, estimated_time_minutes=?, estimated_time=?
            WHERE question_id=?
        """, (
            assessment_id,
            meta["subject_id"],
            meta["topic_id"],
            meta["learning_outcome_id"],
            meta["competency_id"],
            meta["concept_id"],
            request.form.get("question_text", "").strip(),
            concept_tag,
            request.form.get("difficulty_level") or "standard",
            request.form.get("question_type") or "multiple_choice",
            int(request.form.get("marks") or 1),
            request.form.get("correct_answer", "").strip(),
            request.form.get("bloom_level") or "Understand",
            request.form.get("explanation", "").strip(),
            request.form.get("feedback", "").strip(),
            request.form.get("resource_link", "").strip(),
            request.form.get("resource_link", "").strip(),
            int(request.form.get("estimated_time") or 2),
            int(request.form.get("estimated_time") or 2),
            question_id,
        ))
        if request.form.get("question_type") == "multiple_choice":
            save_question_options(conn, question_id, request.form)
        audit(conn, "EDIT_QUESTION", "question", question_id, "Updated CBC question bank metadata")
        conn.commit()
        conn.close()
        flash("Question updated.", "success")
        return redirect(url_for("admin.question_bank"))
    lists = question_form_lists(conn)
    options = conn.execute("""
        SELECT option_text, is_correct
        FROM question_options
        WHERE question_id=?
        ORDER BY option_id
    """, (question_id,)).fetchall()
    conn.close()
    return render_template("admin/question_form.html", question=question, options=options, **lists)


@admin_bp.route("/admin/settings", methods=["GET", "POST"])
@role_required("school_admin", "super_admin")
@csrf_protect
def settings():
    conn = get_db()
    admin = current_admin(conn)
    ensure_system_settings(conn)

    if request.method == "POST":
        if admin["role_name"] != "super_admin":
            conn.close()
            flash("Only the Super Administrator can change global system settings.", "danger")
            return redirect(url_for("admin.settings"))

        action = request.form.get("settings_action", "update_system_settings")
        if action == "update_system_settings":
            updated_keys = []
            try:
                for group, setting in setting_specs():
                    if setting["key"] not in request.form:
                        continue
                    value = validate_setting_value(setting, request.form.get(setting["key"]))
                    conn.execute("""
                        UPDATE system_settings
                        SET setting_value = ?,
                            setting_description = ?,
                            setting_category = ?,
                            setting_type = ?,
                            updated_by = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE setting_key = ?
                    """, (
                        value,
                        setting["description"],
                        group["title"],
                        setting["type"],
                        session.get("user_id"),
                        setting["key"],
                    ))
                    updated_keys.append(setting["key"])
            except ValueError as exc:
                conn.close()
                flash(str(exc), "danger")
                return redirect(url_for("admin.settings"))

            if updated_keys:
                audit(conn, "UPDATE_SYSTEM_SETTINGS", "system_settings", "global", f"Updated settings: {', '.join(updated_keys)}")
                conn.commit()
                flash("System settings updated and recorded in the audit trail.", "success")
            else:
                flash("No settings were changed.", "warning")
            conn.close()
            return redirect(url_for("admin.settings"))

        if action == "restore_defaults":
            for group, setting in setting_specs():
                conn.execute("""
                    UPDATE system_settings
                    SET setting_value = ?,
                        setting_description = ?,
                        setting_category = ?,
                        setting_type = ?,
                        updated_by = ?,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE setting_key = ?
                """, (
                    str(setting["default"]),
                    setting["description"],
                    group["title"],
                    setting["type"],
                    session.get("user_id"),
                    setting["key"],
                ))
            audit(conn, "RESTORE_SYSTEM_SETTINGS", "system_settings", "global", "Restored default CBC/AI configuration")
            conn.commit()
            conn.close()
            flash("Default settings restored.", "success")
            return redirect(url_for("admin.settings"))

        if action == "update_threshold":
            outcome_id = request.form.get("outcome_id")
            try:
                threshold = int(request.form.get("mastery_threshold", "80"))
            except ValueError:
                conn.close()
                flash("Mastery threshold must be a number.", "danger")
                return redirect(url_for("admin.settings"))
            if threshold < 50 or threshold > 100:
                conn.close()
                flash("Mastery threshold must be between 50 and 100.", "danger")
                return redirect(url_for("admin.settings"))
            conn.execute("""
                UPDATE learning_outcomes
                SET mastery_threshold = ?
                WHERE outcome_id = ?
            """, (threshold, outcome_id))
            audit(conn, "UPDATE_MASTERY_THRESHOLD", "learning_outcome", outcome_id, f"Set mastery threshold to {threshold}%")
            conn.commit()
            conn.close()
            flash("Outcome mastery threshold updated.", "success")
            return redirect(url_for("admin.settings"))

    thresholds = conn.execute("""
        SELECT subjects.subject_name, learning_outcomes.outcome_id, learning_outcomes.outcome_code, learning_outcomes.outcome_name,
               learning_outcomes.mastery_threshold
        FROM learning_outcomes
        JOIN competencies ON learning_outcomes.competency_id=competencies.competency_id
        JOIN subjects ON competencies.subject_id=subjects.subject_id
        ORDER BY subjects.subject_name, learning_outcomes.sequence_order
    """).fetchall()
    settings_groups = grouped_settings(conn)
    conn.close()
    return render_template(
        "admin/settings.html",
        thresholds=thresholds,
        settings_groups=settings_groups,
        can_edit_settings=admin["role_name"] == "super_admin",
    )


@admin_bp.route("/admin/ai-configuration")
@role_required("school_admin", "super_admin")
def ai_configuration():
    conn = get_db()
    ensure_system_settings(conn)
    settings_rows = conn.execute("""
        SELECT *
        FROM system_settings
        WHERE setting_category LIKE 'AI%'
           OR setting_key IN ('bkt_model', 'at_risk_threshold', 'teacher_review_required')
        ORDER BY setting_category, setting_key
    """).fetchall()
    bkt = conn.execute("""
        SELECT
            ROUND(CAST(AVG(prior_mastery_probability) AS NUMERIC), 3) AS avg_prior,
            ROUND(CAST(AVG(learn_probability) AS NUMERIC), 3) AS avg_learn,
            ROUND(CAST(AVG(guess_probability) AS NUMERIC), 3) AS avg_guess,
            ROUND(CAST(AVG(slip_probability) AS NUMERIC), 3) AS avg_slip,
            ROUND(CAST(AVG(probability_mastery) * 100 AS NUMERIC), 1) AS avg_mastery,
            ROUND(CAST(AVG(confidence_score) AS NUMERIC), 1) AS avg_confidence,
            COUNT(*) AS records
        FROM bkt_mastery
    """).fetchone()
    recommendations = conn.execute("""
        SELECT recommendation_type, teacher_status, COUNT(*) AS total,
               ROUND(CAST(AVG(confidence_score) AS NUMERIC), 1) AS avg_confidence
        FROM recommendations
        GROUP BY recommendation_type, teacher_status
        ORDER BY total DESC
    """).fetchall()
    conn.close()
    return render_template(
        "admin/ai_configuration.html",
        settings_rows=settings_rows,
        bkt=bkt,
        recommendations=recommendations,
    )


@admin_bp.route("/admin/logs")
@role_required("school_admin", "super_admin")
def logs():
    conn = get_db()
    admin = current_admin(conn)
    scope = school_scope_for(conn, admin)
    activity_where = ""
    activity_params = []
    if scope is not None:
        activity_where = "WHERE users.school_id = ?"
        activity_params.append(scope)
    activity = conn.execute("""
        SELECT activity_logs.*, users.full_name
        FROM activity_logs
        JOIN users ON activity_logs.learner_id = users.user_id
        """ + activity_where + """
        ORDER BY activity_logs.created_at DESC
        LIMIT 100
    """, activity_params).fetchall()
    audit_where = ""
    audit_params = []
    if scope is not None:
        audit_where = """
        WHERE actor.school_id = ?
           OR target.school_id = ?
        """
        audit_params.extend([scope, scope])
    audit_rows = conn.execute("""
        SELECT audit_logs.*, actor.full_name AS actor_name
        FROM audit_logs
        LEFT JOIN users AS actor ON audit_logs.actor_id = actor.user_id
        LEFT JOIN users AS target ON audit_logs.entity_type = 'user'
             AND CAST(audit_logs.entity_id AS INTEGER) = target.user_id
        """ + audit_where + """
        ORDER BY audit_logs.created_at DESC
        LIMIT 100
    """, audit_params).fetchall()
    sync = conn.execute("SELECT * FROM offline_sync_queue ORDER BY created_at DESC LIMIT 50").fetchall()
    conn.close()
    return render_template("admin/logs.html", activity=activity, audit_rows=audit_rows, sync=sync)


@admin_bp.route("/admin/reports")
@role_required("school_admin", "super_admin")
def reports():
    conn = get_db()
    admin = current_admin(conn)
    scope = school_scope_for(conn, admin)
    summary = admin_summary(conn, scope)
    user_where = ""
    params = []
    if scope is not None:
        user_where = "WHERE users.school_id = ? AND roles.role_name IN ('learner', 'teacher')"
        params.append(scope)
    report_users = conn.execute(f"""
        SELECT users.user_id, users.full_name, users.username, users.account_status,
               users.security_level, roles.role_name, roles.display_name, schools.school_name
        FROM users
        JOIN roles ON users.role_id = roles.role_id
        LEFT JOIN schools ON users.school_id = schools.school_id
        {user_where}
        ORDER BY users.security_level DESC, roles.role_name, users.full_name
    """, params).fetchall()
    school_params = []
    school_where = ""
    if scope is not None:
        school_where = "WHERE schools.school_id = ?"
        school_params.append(scope)
    schools = conn.execute(f"SELECT * FROM schools {school_where} ORDER BY school_name", school_params).fetchall()
    mastery = conn.execute("""
        SELECT subjects.subject_name, COUNT(mastery_records.mastery_id) AS records,
               SUM(CASE WHEN mastery_records.mastery_status='Mastered' THEN 1 ELSE 0 END) AS mastered,
               ROUND(CAST(AVG(mastery_records.mastery_score) AS NUMERIC), 1) AS avg_mastery
        FROM subjects
        LEFT JOIN competencies ON competencies.subject_id = subjects.subject_id
        LEFT JOIN learning_outcomes ON learning_outcomes.competency_id = competencies.competency_id
        LEFT JOIN mastery_records ON mastery_records.outcome_id = learning_outcomes.outcome_id
             """ + ("AND mastery_records.learner_id IN (SELECT user_id FROM users WHERE school_id = ?)" if scope is not None else "") + """
        GROUP BY subjects.subject_id
        ORDER BY subjects.subject_name
    """, (scope,) if scope is not None else ()).fetchall()
    conn.close()
    return render_template(
        "admin/reports.html",
        summary=summary,
        mastery=mastery,
        report_users=report_users,
        schools=schools,
    )



@admin_bp.route("/admin/headteacher/create", methods=["GET", "POST"])
@role_required("super_admin")
@csrf_protect
def create_headteacher():
    conn = get_db()
    if request.method == "POST":
        username = request.form.get("username")
        full_name = request.form.get("full_name")
        email = request.form.get("email")
        password = request.form.get("password")
        school_id = request.form.get("school_id")

        role = conn.execute("SELECT role_id FROM roles WHERE role_name = 'school_admin'").fetchone()

        try:
            conn.execute("""
                INSERT INTO users (full_name, username, email, password_hash, role_id, school_id, account_status, security_level)
                VALUES (?, ?, ?, ?, ?, ?, 'Active', 4)
            """, (full_name, username, email, generate_password_hash(password), role['role_id'], school_id))
            conn.commit()
            flash("School Admin created successfully.", "success")
            return redirect(url_for("admin.users"))
        except Exception as e:
            flash(f"Error creating School Admin: {e}", "danger")

    schools = conn.execute("SELECT * FROM schools").fetchall()
    conn.close()
    return render_template("admin/headteacher_form.html", schools=schools)

@admin_bp.route("/admin/kb/upload", methods=["GET", "POST"])
@role_required("super_admin")
@csrf_protect
def admin_kb_upload():
    kb = get_kb()
    if request.method == "POST":
        file = request.files.get("file")
        if file and file.filename:
            filename = secure_filename(file.filename)
            ext = os.path.splitext(filename)[1].lower()
            if ext not in {'.txt', '.md', '.json', '.pdf'}:
                flash("Unsupported file type. Use .txt, .md, .json, or .pdf", "danger")
                return redirect(url_for("admin.admin_kb_upload"))

            filepath = kb.directory / filename
            file.save(str(filepath))

            # Use unified processing method
            success, _ = kb.process_file(str(filepath))

            if success:
                conn = get_db()
                audit(conn, "KB_UPLOAD", "knowledge_base", filename, f"Uploaded and processed {filename}")
                conn.commit()
                conn.close()
                flash(f"File {filename} uploaded and KB updated.", "success")
            else:
                filepath.unlink(missing_ok=True)
                flash(f"Error processing {filename}.", "danger")

            return redirect(url_for("admin.admin_kb_upload"))

    files = []
    if kb.directory.exists():
        files = [f for f in os.listdir(kb.directory) if not f.startswith('_')]
    return render_template("admin_kb_upload.html", files=files)
