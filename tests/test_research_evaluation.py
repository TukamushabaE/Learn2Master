from conftest import csrf_token, login


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
