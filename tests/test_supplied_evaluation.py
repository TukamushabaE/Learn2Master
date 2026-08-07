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
    assert b"six-month participant evaluation" in page.data

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
    assert b"Automatically Updated Portal Evidence" in chapter_four.data

    chapter_five = client.get("/research/chapter-five-insights")
    assert chapter_five.status_code == 200
    assert b"Connected Discussion and Insights" in chapter_five.data
    assert b"Dataset 5 records show a mean increase" in chapter_five.data

    connected_export = client.get("/research/export/full-dataset")
    assert connected_export.status_code == 200
    assert b"record_source,capture_mode,record_type" in connected_export.data
    assert b"Dataset 5 research evaluation" in connected_export.data
    assert b"KTHS-L001" in connected_export.data


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
