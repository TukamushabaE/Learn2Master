from io import BytesIO

from conftest import assessment_id, correct_answers, csrf_token, login, outcome_id
from werkzeug.security import generate_password_hash


def test_login_and_role_redirects(client):
    response = login(client, "elijah", "12345")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/student/dashboard")

    client.get("/logout")
    response = login(client, "teacher", "12345")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/teacher")


def test_registration_always_creates_learner(client, db):
    client.get("/register")
    response = client.post(
        "/register",
        data={
            "full_name": "Role Escalation Attempt",
            "username": "intruder",
            "email": "intruder@example.com",
            "password": "StrongPass123",
            "school_name": "Kigezi High School",
            "role": "super_admin",
            "csrf_token": csrf_token(client),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    row = db.execute("""
        SELECT roles.role_name
        FROM users
        JOIN roles ON users.role_id = roles.role_id
        WHERE users.username = 'intruder'
    """).fetchone()
    assert row["role_name"] == "learner"


def test_admin_can_create_teacher_with_audit_and_role_security(client, db):
    login(client, "admin", "12345")
    response = client.post(
        "/admin/users/create",
        data={
            "full_name": "Managed Teacher",
            "username": "managed_teacher",
            "email": "managed.teacher@example.com",
            "phone": "+256700000000",
            "title": "Physics Teacher",
            "role_name": "teacher",
            "school_id": "1",
            "account_status": "Active",
            "security_level": "5",
            "password": "TeacherPass123",
            "must_change_password": "on",
            "csrf_token": csrf_token(client),
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    row = db.execute("""
        SELECT users.security_level, users.must_change_password, roles.role_name
        FROM users
        JOIN roles ON roles.role_id = users.role_id
        WHERE users.username = 'managed_teacher'
    """).fetchone()
    audit = db.execute("""
        SELECT COUNT(*) AS total
        FROM audit_logs
        WHERE action = 'CREATE_USER' AND details LIKE '%teacher%'
    """).fetchone()

    assert row["role_name"] == "teacher"
    assert row["security_level"] == 3
    assert row["must_change_password"] == 1
    assert audit["total"] >= 1


def test_school_admin_cannot_create_super_admin(client, db):
    login(client, "admin", "12345")
    response = client.post(
        "/admin/users/create",
        data={
            "full_name": "Privilege Escalation",
            "username": "fake_super",
            "email": "fake.super@example.com",
            "role_name": "super_admin",
            "school_id": "1",
            "account_status": "Active",
            "security_level": "5",
            "password": "SuperPass123",
            "csrf_token": csrf_token(client),
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    row = db.execute("SELECT user_id FROM users WHERE username = 'fake_super'").fetchone()
    assert row is None


def test_forced_password_change_blocks_navigation_and_clears_flag(client, db):
    teacher_role = db.execute("SELECT role_id FROM roles WHERE role_name = 'teacher'").fetchone()["role_id"]
    db.execute("""
        INSERT INTO users
        (full_name, username, email, password_hash, role_id, school_id,
         account_status, security_level, must_change_password)
        VALUES (?, ?, ?, ?, ?, 1, 'Active', 3, 1)
    """, (
        "Temporary Teacher",
        "tempteacher",
        "tempteacher@example.com",
        generate_password_hash("TempPass123"),
        teacher_role,
    ))
    db.commit()

    response = login(client, "tempteacher", "TempPass123")
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/change-password")

    blocked = client.get("/teacher", follow_redirects=False)
    assert blocked.status_code == 302
    assert blocked.headers["Location"].endswith("/change-password")

    changed = client.post(
        "/change-password",
        data={
            "current_password": "TempPass123",
            "new_password": "BetterPass123",
            "confirm_password": "BetterPass123",
            "csrf_token": csrf_token(client),
        },
        follow_redirects=False,
    )
    assert changed.status_code == 302
    assert changed.headers["Location"].endswith("/teacher")

    row = db.execute("SELECT must_change_password FROM users WHERE username = 'tempteacher'").fetchone()
    assert row["must_change_password"] == 0


def test_login_lockout_after_repeated_failed_attempts(client, db):
    for _ in range(5):
        client.post(
            "/login",
            data={"username": "elijah", "password": "wrong-password", "csrf_token": csrf_token(client)},
            follow_redirects=False,
        )

    row = db.execute("""
        SELECT account_status, failed_login_attempts, locked_until
        FROM users
        WHERE username = 'elijah'
    """).fetchone()

    assert row["account_status"] == "Locked"
    assert row["failed_login_attempts"] == 5
    assert row["locked_until"] is not None


def test_settings_page_exposes_cbc_ai_governance_sections(client):
    login(client, "admin", "12345")
    response = client.get("/admin/settings")

    assert response.status_code == 200
    assert b"AI &amp; Personalization Settings" in response.data
    assert b"CBC &amp; Mastery Configuration" in response.data
    assert b"Privacy, Safety &amp; Compliance" in response.data


def test_super_admin_can_update_system_settings_and_thresholds(client, db):
    login(client, "superadmin", "12345")
    response = client.post(
        "/admin/settings",
        data={
            "settings_action": "update_system_settings",
            "ai_adaptivity_level": "aggressive",
            "at_risk_threshold": "55",
            "csrf_token": csrf_token(client),
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    setting = db.execute("""
        SELECT setting_value
        FROM system_settings
        WHERE setting_key = 'ai_adaptivity_level'
    """).fetchone()
    alert = db.execute("""
        SELECT setting_value
        FROM system_settings
        WHERE setting_key = 'at_risk_threshold'
    """).fetchone()
    audit = db.execute("""
        SELECT COUNT(*) AS total
        FROM audit_logs
        WHERE action = 'UPDATE_SYSTEM_SETTINGS'
    """).fetchone()

    assert setting["setting_value"] == "aggressive"
    assert alert["setting_value"] == "55"
    assert audit["total"] >= 1

    outcome = outcome_id(db, "ICT-LO1")
    response = client.post(
        "/admin/settings",
        data={
            "settings_action": "update_threshold",
            "outcome_id": str(outcome),
            "mastery_threshold": "85",
            "csrf_token": csrf_token(client),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    threshold = db.execute(
        "SELECT mastery_threshold FROM learning_outcomes WHERE outcome_id = ?",
        (outcome,),
    ).fetchone()
    assert threshold["mastery_threshold"] == 85


def test_school_admin_cannot_update_global_settings(client, db):
    login(client, "admin", "12345")
    response = client.post(
        "/admin/settings",
        data={
            "settings_action": "update_system_settings",
            "ai_adaptivity_level": "aggressive",
            "csrf_token": csrf_token(client),
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    setting = db.execute("""
        SELECT setting_value
        FROM system_settings
        WHERE setting_key = 'ai_adaptivity_level'
    """).fetchone()
    assert setting["setting_value"] == "balanced"


def test_role_guard_blocks_learner_from_admin(client):
    login(client)
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["Location"].endswith("/dashboard")


def test_posttest_stays_locked_before_prerequisites(client, db):
    login(client)
    posttest_id = assessment_id(db, "ICT-LO1", "posttest")
    data = correct_answers(db, posttest_id)
    data["csrf_token"] = csrf_token(client)

    response = client.post(f"/assessment/{posttest_id}/submit", data=data, follow_redirects=False)
    assert response.status_code == 302

    attempts = db.execute(
        "SELECT COUNT(*) AS total FROM assessment_attempts WHERE assessment_id = ?",
        (posttest_id,),
    ).fetchone()["total"]
    assert attempts == 0


def test_assessment_flow_mastery_unlocks_next_outcome(client, db):
    login(client)
    ict_lo1 = outcome_id(db, "ICT-LO1")
    ict_lo2 = outcome_id(db, "ICT-LO2")

    for assessment_type in ("pretest", "practice"):
        aid = assessment_id(db, "ICT-LO1", assessment_type)
        data = correct_answers(db, aid)
        data["csrf_token"] = csrf_token(client)
        response = client.post(f"/assessment/{aid}/submit", data=data, follow_redirects=False)
        assert response.status_code == 302

    response = client.get(f"/outcome/{ict_lo1}")
    assert response.status_code == 200
    assert b"Complete Required Evidence" in response.data
    assert b"Reflection Required" in response.data
    assert b"No extra practice is required right now." in response.data
    assert b"Post-test Stage" not in response.data
    assert b"Evidence Portfolio Progress" in response.data

    learner = db.execute("SELECT user_id FROM users WHERE username = 'elijah'").fetchone()
    activity = db.execute(
        "SELECT activity_id FROM learning_activities WHERE outcome_id = ? ORDER BY activity_id LIMIT 1",
        (ict_lo1,),
    ).fetchone()
    response = client.post(
        f"/outcome/{ict_lo1}/evidence",
        data={
            "evidence_type": "activity",
            "activity_id": str(activity["activity_id"]),
            "evidence_title": "Concept map evidence",
            "evidence_description": "I completed the concept map and labelled the ICT process.",
            "evidence_file": (BytesIO(b"concept map evidence"), "concept-map.txt"),
            "csrf_token": csrf_token(client),
        },
        content_type="multipart/form-data",
        follow_redirects=False,
    )
    assert response.status_code == 302

    activity_submission = db.execute("""
        SELECT submission_text, evidence_path
        FROM activity_submissions
        WHERE learner_id = ? AND outcome_id = ? AND activity_id = ?
    """, (learner["user_id"], ict_lo1, activity["activity_id"])).fetchone()
    portfolio = db.execute("""
        SELECT COUNT(*) AS total
        FROM evidence_portfolio
        WHERE learner_id = ? AND outcome_id = ? AND evidence_type LIKE '%Evidence'
    """, (learner["user_id"], ict_lo1)).fetchone()
    assert activity_submission["submission_text"].startswith("I completed")
    assert activity_submission["evidence_path"]
    assert portfolio["total"] >= 1

    response = client.get(f"/outcome/{ict_lo1}")
    assert b"Submitted 1 time" in response.data

    response = client.post(
        f"/outcome/{ict_lo1}/reflection",
        data={
            "reflection_text": "I can explain ICT concepts clearly.",
            "confidence_level": "5",
            "csrf_token": csrf_token(client),
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    posttest_id = assessment_id(db, "ICT-LO1", "posttest")
    data = correct_answers(db, posttest_id)
    data["csrf_token"] = csrf_token(client)
    response = client.post(f"/assessment/{posttest_id}/submit", data=data, follow_redirects=False)
    assert response.status_code == 302

    mastery = db.execute(
        "SELECT mastery_status FROM mastery_records WHERE outcome_id = ?",
        (ict_lo1,),
    ).fetchone()
    unlocked = db.execute(
        "SELECT is_unlocked FROM mastery_records WHERE outcome_id = ?",
        (ict_lo2,),
    ).fetchone()

    assert mastery["mastery_status"] == "Mastered"
    assert unlocked["is_unlocked"] == 1


def test_service_worker_route(client):
    response = client.get("/service-worker.js")
    assert response.status_code == 200
    assert b"learn2master-offline" in response.data


def test_new_research_ai_portfolio_and_admin_routes_render(client):
    login(client, "superadmin", "12345")
    for path in (
        "/admin/roles",
        "/admin/curriculum",
        "/admin/backups",
        "/research/dashboard",
        "/research/reports",
        "/ai/explanations",
    ):
        response = client.get(path)
        assert response.status_code == 200

    csv_response = client.get("/research/reports?format=csv")
    assert csv_response.status_code == 200
    assert csv_response.mimetype == "text/csv"
    assert b"metric,value" in csv_response.data

    client.get("/logout")
    login(client, "elijah", "12345")
    assert client.get("/learner/ai-coach").status_code == 200
    assert client.get("/learner/portfolio").status_code == 200

    client.get("/logout")
    login(client, "teacher", "12345")
    assert client.get("/teacher/portfolio/1").status_code == 200
