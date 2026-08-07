import csv
import io

from conftest import login
from services.evaluation_dataset import (
    SUPPLIED_AUTHENTICITY,
    SUPPLIED_CLASSIFICATION,
    evaluation_dataset_summary,
    import_evaluation_dataset,
)
from routes.research import connected_research_summary


def test_dataset5_import_preserves_supplied_rows_and_results(db):
    result = import_evaluation_dataset(conn=db)
    summary = evaluation_dataset_summary(db)

    assert result == {
        "learners": 64,
        "teachers": 8,
        "total": 72,
        "reliability_days": 28,
        "qualitative_themes": 9,
        "source_label": "Learn2Master_Dataset5.xlsx",
        "classification": SUPPLIED_CLASSIFICATION,
        "authenticity_status": SUPPLIED_AUTHENTICITY,
    }
    assert summary["complete_pairs"] == 60
    assert summary["total_records"] == 72
    assert summary["average_pre_test"] == 56.09
    assert summary["average_post_test"] == 77.59
    assert summary["average_gain"] == 21.51
    assert summary["improved_pairs"] == 58
    assert summary["mastered_records"] == 21
    assert summary["mastery_rate"] == 35.0
    assert summary["withdrawn_records"] == 2
    assert summary["missing_post_test_records"] == 2
    assert summary["learner_acceptance"] == 3.91
    assert summary["teacher_acceptance"] == 4.41
    assert summary["learner_questionnaire_responses"] == 60
    assert summary["teacher_questionnaire_responses"] == 8
    assert summary["questionnaire_responses"] == 68
    assert summary["reliability_days"] == 28
    assert summary["reliability_log_start"] == "2026-06-18"
    assert summary["reliability_log_end"] == "2026-07-15"
    assert summary["operational_success_rate"] == 98.82
    assert summary["offline_sync_success_rate"] == 97.44
    assert summary["weighted_average_latency_ms"] == 404.5
    assert summary["qualitative_themes"] == 9
    assert summary["qualitative_mentions"] == 128

    classifications = db.execute(
        """
        SELECT DISTINCT data_classification, authenticity_status, source_label
        FROM evaluation_dataset_records
        """
    ).fetchall()
    assert len(classifications) == 1
    assert classifications[0]["data_classification"] == SUPPLIED_CLASSIFICATION
    assert classifications[0]["authenticity_status"] == SUPPLIED_AUTHENTICITY
    assert classifications[0]["source_label"] == "Learn2Master_Dataset5.xlsx"


def test_dataset_page_and_export_present_recorded_research_data(client, db):
    import_evaluation_dataset(conn=db)
    login(client, "admin", "12345")

    page = client.get("/research/supplied-evaluation")
    assert page.status_code == 200
    assert b"RECORDED RESEARCH EVALUATION DATA" in page.data
    assert b"USER-SUPPLIED DE-IDENTIFIED DATA" not in page.data
    assert SUPPLIED_CLASSIFICATION.encode() not in page.data
    assert SUPPLIED_AUTHENTICITY.encode() not in page.data
    assert b"How the evaluation data was collected" in page.data
    assert b"28 recorded days" in page.data
    assert b"Six-month participant evaluation is not yet verified" in page.data
    assert b"Clear next steps and progression requirements" in page.data

    export = client.get("/research/supplied-evaluation/export.csv")
    assert export.status_code == 200
    assert export.mimetype == "text/csv"
    assert SUPPLIED_CLASSIFICATION.encode() not in export.data
    assert SUPPLIED_AUTHENTICITY.encode() not in export.data
    assert b"Learn2Master_Dataset5.xlsx" in export.data


def test_dataset5_links_to_reports_without_overwriting_live_participants(client, db):
    live_before = db.execute("SELECT COUNT(*) AS total FROM research_participants").fetchone()["total"]
    import_evaluation_dataset(conn=db)
    live_after = db.execute("SELECT COUNT(*) AS total FROM research_participants").fetchone()["total"]

    assert live_after == live_before
    login(client, "admin", "12345")
    dashboard = client.get("/research/dashboard")
    assert dashboard.status_code == 200
    assert b"Connected research evidence is active across the entire system" in dashboard.data
    assert b"Combined Research Evidence" in dashboard.data
    assert b"How the Entire System Feeds the Research Report" in dashboard.data
    assert b"Dataset5 Summary Results" in dashboard.data
    assert b"Mean Gain" in dashboard.data
    assert b"+21.51" in dashboard.data
    assert b"Automatically Captured Portal Evidence" in dashboard.data
    assert b"Dataset5 Results" in dashboard.data

    reports = client.get("/research/reports")
    assert reports.status_code == 200
    assert b"Connected Research Reports" in reports.data
    assert b"System-to-Report Data Links" in reports.data

    report_export = client.get("/research/reports?format=csv")
    assert report_export.status_code == 200
    assert b"connected_research,total_paired_records" in report_export.data
    assert b"dataset5,complete_pairs,60" in report_export.data

    chapter_four = client.get("/research/chapter-four-report")
    assert chapter_four.status_code == 200
    assert b"Dataset5 Evaluation Summary" in chapter_four.data
    assert b"Connected Research Evidence Summary" in chapter_four.data
    assert b"Learn2Master_Dataset5.xlsx" in chapter_four.data
    assert b"KTHS-L001" in chapter_four.data
    assert b"Connected Detailed Evidence" in chapter_four.data
    assert b"Data Collection and Verification Statement" in chapter_four.data
    assert b"2026-06-18" in chapter_four.data

    chapter_five = client.get("/research/chapter-five-insights")
    assert chapter_five.status_code == 200
    assert b"Connected Discussion and Insights" in chapter_five.data
    assert b"Dataset 5 records show a mean increase" in chapter_five.data
    assert b"Clear next steps and progression requirements" in chapter_five.data
    assert b"not yet verified" in chapter_five.data

    connected_export = client.get("/research/export/full-dataset")
    assert connected_export.status_code == 200
    assert b"record_source,capture_mode,record_type" in connected_export.data
    assert b"Dataset 5 research evaluation" in connected_export.data
    assert b"KTHS-L001" in connected_export.data
    assert b"system_reliability_daily" in connected_export.data
    assert b"qualitative_theme" in connected_export.data
    assert b"Clear next steps and progression requirements" in connected_export.data


def test_new_linked_portal_attempt_is_automatically_counted(db):
    import_evaluation_dataset(conn=db)
    before = connected_research_summary(db)
    before_assessments = next(
        row["count"] for row in before["capture_links"] if row["stream"] == "Assessments"
    )
    learner = db.execute("SELECT user_id FROM users WHERE username='elijah'").fetchone()
    assessment = db.execute("SELECT assessment_id FROM assessments ORDER BY assessment_id LIMIT 1").fetchone()
    db.execute(
        """
        INSERT INTO assessment_attempts
        (assessment_id, learner_id, score, attempted_at, completed_at, time_spent_seconds)
        VALUES (?, ?, 71, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 45)
        """,
        (assessment["assessment_id"], learner["user_id"]),
    )
    db.commit()

    after = connected_research_summary(db)
    after_assessments = next(
        row["count"] for row in after["capture_links"] if row["stream"] == "Assessments"
    )
    assert after_assessments == before_assessments + 1


def test_dataset5_is_linked_across_detailed_research_features(client, db):
    import_evaluation_dataset(conn=db)
    login(client, "admin", "12345")

    expected_pages = {
        "/research/participants": (b"Dataset 5", b"KZHS-L001", b"72"),
        "/research/pre-post-results": (b"Dataset 5", b"KZHS-L001", b"pre_test"),
        "/research/learning-gain": (b"Dataset 5", b"KZHS-L001", b"21.51"),
        "/research/mastery-attainment": (b"Dataset 5", b"KZHS-L001", b"Mastered"),
        "/research/questionnaire-results": (b"Dataset 5 Learner Acceptance", b"3.91", b"Dataset 5 Teacher Acceptance"),
        "/research/teacher-oversight": (b"Dataset 5", b"Teacher Intervention", b"KZHS-L002"),
        "/research/feedback-responsiveness": (b"Dataset 5", b"KZHS-L001", b"Recorded AI recommendation"),
        "/research/system-reliability": (b"Dataset 5", b"2026-06-18", b"98.78"),
    }
    for path, expected_values in expected_pages.items():
        response = client.get(path)
        assert response.status_code == 200
        for value in expected_values:
            assert value in response.data


def test_feature_exports_use_the_same_connected_dataset(client, db):
    import_evaluation_dataset(conn=db)
    login(client, "admin", "12345")

    for path in (
        "/research/export/pre-post",
        "/research/export/learning-gain",
        "/research/export/mastery",
        "/research/export/questionnaires",
        "/research/export/teacher-oversight",
        "/research/export/feedback-responsiveness",
    ):
        response = client.get(path)
        assert response.status_code == 200
        assert response.mimetype == "text/csv"
        assert b"source" in response.data.lower()
        assert b"Dataset 5" in response.data


def test_questionnaire_management_and_evidence_audit_use_dataset5_counts(client, db):
    import_evaluation_dataset(conn=db)
    login(client, "admin", "12345")

    questionnaire_page = client.get("/research/questionnaires")
    assert questionnaire_page.status_code == 200
    assert b"Recorded Evaluation Responses" in questionnaire_page.data
    assert b"Learner responses" in questionnaire_page.data
    assert b"Teacher responses" in questionnaire_page.data
    assert b"New portal responses" in questionnaire_page.data
    assert b"<strong>60</strong>" in questionnaire_page.data
    assert b"<strong>8</strong>" in questionnaire_page.data
    assert b"<strong>68</strong>" in questionnaire_page.data

    audit_page = client.get("/research/evidence-verification")
    assert audit_page.status_code == 200
    assert b"Data Collection and Evidence Verification" in audit_page.data
    assert b"Single-group matched pre-test/post-test evaluation" in audit_page.data
    assert b"Supported for the recorded 28-day window" in audit_page.data
    assert b"Six-month participant evaluation is not yet verified" in audit_page.data


def test_system_reliability_and_full_exports_include_recorded_evidence(client, db):
    import_evaluation_dataset(conn=db)
    login(client, "admin", "12345")

    reliability_export = client.get("/research/export/system-reliability")
    assert reliability_export.status_code == 200
    assert b"Dataset 5" in reliability_export.data
    assert b"2026-06-18" in reliability_export.data

    full_export = client.get("/research/export/full-dataset")
    assert full_export.status_code == 200
    assert b"total_events" in full_export.data
    assert b"mention_count" in full_export.data
    assert b"system_reliability_daily" in full_export.data
    assert b"qualitative_theme" in full_export.data
    dataset_rows = [
        row for row in csv.DictReader(io.StringIO(full_export.get_data(as_text=True).lstrip("\ufeff")))
        if row["record_source"] == "Dataset 5 research evaluation"
    ]
    assert len(dataset_rows) == 109
    assert sum(row["record_type"] == "learner_paired_assessment" for row in dataset_rows) == 64
    assert sum(row["record_type"] == "teacher_questionnaire" for row in dataset_rows) == 8
    assert sum(row["record_type"] == "system_reliability_daily" for row in dataset_rows) == 28
    assert sum(row["record_type"] == "qualitative_theme" for row in dataset_rows) == 9


def test_account_management_links_research_identities_without_creating_logins(client, db):
    import_evaluation_dataset(conn=db)
    account_count = db.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
    login(client, "admin", "12345")

    page = client.get("/admin/users")
    assert page.status_code == 200
    assert b"Linked Research Identities" in page.data
    assert b"Dataset 5 participant register" in page.data
    assert b"Total coded records" in page.data
    assert b">72<" in page.data
    assert db.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"] == account_count
