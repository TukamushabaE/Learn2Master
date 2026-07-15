import sqlite3

import database
import init_db

from conftest import login, outcome_id
from services.research_analytics import learning_gain_summary


def test_legacy_schema_missing_activity_submissions_is_repaired_without_data_loss(app, client, db):
    """Reproduce the persistent-DB drift that made hosted /outcome/5 return 500."""
    school_count = db.execute("SELECT COUNT(*) FROM schools").fetchone()[0]
    db.execute("DROP TABLE activity_submissions")
    db.commit()

    missing = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='activity_submissions'"
    ).fetchone()
    assert missing is None

    init_db.ensure_current_schema(f"sqlite:///{database.DATABASE}")

    repaired = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='activity_submissions'"
    ).fetchone()
    assert repaired is not None
    assert db.execute("SELECT COUNT(*) FROM schools").fetchone()[0] == school_count
    versions = db.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    assert len(versions) == len(init_db.SCHEMA_MIGRATIONS)

    login(client, "elijah", "12345")
    assert client.get("/outcome/5").status_code == 200


def test_outcome_route_handles_invalid_and_incomplete_configuration(client, db):
    login(client, "elijah", "12345")
    assert client.get("/outcome/999999").status_code == 404

    physics_outcome = outcome_id(db, "PHY-LO1")
    lesson = db.execute("SELECT lesson_id FROM lessons WHERE outcome_id=?", (physics_outcome,)).fetchone()
    db.execute("DELETE FROM question_options WHERE question_id IN (SELECT question_id FROM questions WHERE assessment_id IN (SELECT assessment_id FROM assessments WHERE lesson_id=?))", (lesson["lesson_id"],))
    db.execute("DELETE FROM questions WHERE assessment_id IN (SELECT assessment_id FROM assessments WHERE lesson_id=?)", (lesson["lesson_id"],))
    db.commit()
    response = client.get(f"/outcome/{physics_outcome}")
    assert response.status_code == 200
    assert b"Something Went Wrong" not in response.data


def test_research_routes_filters_integrity_reliability_and_traceability(client):
    login(client, "admin", "12345")
    routes = (
        "/research/feedback-responsiveness",
        "/research/system-reliability",
        "/research/data-integrity",
        "/research/data-collection-readiness",
        "/research/proposal-traceability",
        "/research/pre-post-results?study_phase=Pilot&subject_id=1",
        "/research/export/feedback-responsiveness",
        "/research/export/teacher-oversight",
        "/research/export/system-reliability",
        "/version",
    )
    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, route


def test_duplicate_final_questionnaire_submission_is_blocked(client, db):
    questionnaire = db.execute("""
        SELECT id FROM research_questionnaires WHERE respondent_role='learner' ORDER BY id LIMIT 1
    """).fetchone()
    items = db.execute("SELECT id FROM research_questionnaire_items WHERE questionnaire_id=?", (questionnaire["id"],)).fetchall()
    login(client, "elijah", "12345")
    payload = {f"score_{item['id']}": "4" for item in items}
    first = client.post(f"/research/questionnaires/{questionnaire['id']}/respond", data=payload)
    assert first.status_code == 302
    answer_count = db.execute("SELECT COUNT(*) FROM research_questionnaire_answers").fetchone()[0]
    second = client.post(f"/research/questionnaires/{questionnaire['id']}/respond", data=payload)
    assert second.status_code == 302
    assert db.execute("SELECT COUNT(*) FROM research_questionnaire_answers").fetchone()[0] == answer_count


def test_sample_statistics_and_normalized_gain_edge_cases():
    rows = [
        {"pre_test": 0, "post_test": 10, "learning_gain": 10, "normalized_gain": 0.1},
        {"pre_test": 100, "post_test": 100, "learning_gain": 0, "normalized_gain": "Not applicable"},
        {"pre_test": 50, "post_test": 40, "learning_gain": -10, "normalized_gain": -0.2},
    ]
    summary = learning_gain_summary(rows)
    assert summary["valid_pairs"] == 3
    assert summary["positive_gain_count"] == 1
    assert summary["zero_gain_count"] == 1
    assert summary["negative_gain_count"] == 1
    assert summary["gain_sample_standard_deviation"] > 0
