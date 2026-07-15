from conftest import assessment_id, correct_answers, csrf_token, login, outcome_id


def test_research_required_routes_open_for_admin(client):
    login(client, "admin", "12345")
    routes = [
        "/research/dashboard",
        "/research/participants",
        "/research/participants/create",
        "/research/pre-post-results",
        "/research/pre-test-results",
        "/research/post-test-results",
        "/research/learning-gain",
        "/research/mastery-attainment",
        "/research/teacher-oversight",
        "/research/questionnaires",
        "/research/questionnaires/create",
        "/research/questionnaire-results",
        "/research/system-logs",
        "/research/chapter-guide",
        "/research/chapter-four-report",
        "/research/chapter-five-insights",
    ]
    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, route


def test_research_exports_return_csv_and_audit(client, db):
    login(client, "admin", "12345")
    routes = [
        "/research/export/pre-post",
        "/research/export/learning-gain",
        "/research/export/mastery",
        "/research/export/questionnaires",
        "/research/export/full-dataset",
    ]
    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, route
        assert response.mimetype == "text/csv"

    audit = db.execute("""
        SELECT COUNT(*) AS total
        FROM audit_logs
        WHERE action='EXPORT_GENERATED'
    """).fetchone()
    assert audit["total"] >= len(routes)


def test_questionnaire_response_records_likert_scores(client, db):
    questionnaire = db.execute("""
        SELECT id FROM research_questionnaires
        WHERE respondent_role='learner'
        ORDER BY id LIMIT 1
    """).fetchone()
    assert questionnaire is not None
    items = db.execute("""
        SELECT id FROM research_questionnaire_items
        WHERE questionnaire_id=?
        ORDER BY display_order
    """, (questionnaire["id"],)).fetchall()
    assert items

    login(client, "elijah", "12345")
    payload = {"csrf_token": csrf_token(client)}
    for item in items:
        payload[f"score_{item['id']}"] = "5"

    response = client.post(
        f"/research/questionnaires/{questionnaire['id']}/respond",
        data=payload,
        follow_redirects=False,
    )
    assert response.status_code == 302

    saved = db.execute("""
        SELECT COUNT(*) AS total
        FROM research_questionnaire_answers
    """).fetchone()
    assert saved["total"] >= len(items)


def test_research_seeded_participants_and_questionnaires(db):
    participants = db.execute("SELECT COUNT(*) AS total FROM research_participants").fetchone()
    questionnaires = db.execute("SELECT COUNT(*) AS total FROM research_questionnaires").fetchone()
    items = db.execute("SELECT COUNT(*) AS total FROM research_questionnaire_items").fetchone()

    assert participants["total"] >= 2
    assert questionnaires["total"] >= 2
    assert items["total"] >= 20


def test_assessment_timing_gain_chart_and_consent_filter(client, db):
    login(client, "elijah", "12345")
    learning_outcome_id = outcome_id(db, "ICT-LO1")
    pretest_id = assessment_id(db, "ICT-LO1", "pretest")
    assert client.get(f"/outcome/{learning_outcome_id}").status_code == 200

    payload = correct_answers(db, pretest_id)
    payload["csrf_token"] = csrf_token(client)
    response = client.post(f"/assessment/{pretest_id}/submit", data=payload, follow_redirects=False)
    assert response.status_code == 302

    timing = db.execute("""
        SELECT started_at, completed_at, time_spent_seconds
        FROM assessment_attempts
        WHERE assessment_id=?
        ORDER BY attempt_id DESC LIMIT 1
    """, (pretest_id,)).fetchone()
    assert timing["started_at"]
    assert timing["completed_at"]
    assert timing["time_spent_seconds"] >= 0

    client.get("/logout")
    login(client, "admin", "12345")
    results = client.get("/research/pre-post-results")
    gain = client.get("/research/learning-gain")
    assert b"L001" in results.data
    assert b"Participant Pre-test vs Post-test" in gain.data

    db.execute("""
        UPDATE research_participants
        SET consent_status='Declined'
        WHERE participant_code='L001'
    """)
    db.commit()
    filtered = client.get("/research/pre-post-results")
    assert b"L001" not in filtered.data
