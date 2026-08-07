from conftest import login
from services.evaluation_dataset import (
    SUPPLIED_AUTHENTICITY,
    SUPPLIED_CLASSIFICATION,
    evaluation_dataset_summary,
    import_evaluation_dataset,
)


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


def test_supplied_dataset_page_and_export_keep_provenance_label(client, db):
    import_evaluation_dataset(conn=db)
    login(client, "admin", "12345")

    page = client.get("/research/supplied-evaluation")
    assert page.status_code == 200
    assert b"USER-SUPPLIED DE-IDENTIFIED DATA" in page.data
    assert SUPPLIED_CLASSIFICATION.encode() in page.data
    assert SUPPLIED_AUTHENTICITY.encode() in page.data
    assert b"six-month participant evaluation" in page.data

    export = client.get("/research/supplied-evaluation/export.csv")
    assert export.status_code == 200
    assert export.mimetype == "text/csv"
    assert SUPPLIED_CLASSIFICATION.encode() in export.data
    assert SUPPLIED_AUTHENTICITY.encode() in export.data
    assert b"Learn2Master_Dataset5.xlsx" in export.data


def test_supplied_rows_remain_separate_from_live_participants(client, db):
    live_before = db.execute("SELECT COUNT(*) AS total FROM research_participants").fetchone()["total"]
    import_evaluation_dataset(conn=db)
    live_after = db.execute("SELECT COUNT(*) AS total FROM research_participants").fetchone()["total"]

    assert live_after == live_before
    login(client, "admin", "12345")
    dashboard = client.get("/research/dashboard")
    assert dashboard.status_code == 200
    assert b"64 learner rows, 60 matched pairs and 8 teacher survey rows" in dashboard.data
    assert b"Dataset5 Summary Results" in dashboard.data
    assert b"Mean Gain" in dashboard.data
    assert b"+21.51" in dashboard.data
    assert b"Live Account-Generated Records" in dashboard.data
    assert b"Dataset5 Results" in dashboard.data

    chapter_four = client.get("/research/chapter-four-report")
    assert chapter_four.status_code == 200
    assert b"Dataset5 Evaluation Summary" in chapter_four.data
    assert b"Learn2Master_Dataset5.xlsx" in chapter_four.data
    assert b"KTHS-L001" in chapter_four.data
    assert b"Separate Live Account-Generated Evidence" in chapter_four.data
