import csv
import io
from urllib.parse import parse_qs, urlparse

from conftest import login
from werkzeug.security import check_password_hash
from services.evaluation_dataset import (
    PUBLIC_RECORD_SOURCE,
    PUBLIC_SOURCE_LABEL,
    SUPPLIED_AUTHENTICITY,
    SUPPLIED_CLASSIFICATION,
    evaluation_dataset_summary,
    evaluation_account_map,
    evaluation_school_summaries,
    import_evaluation_dataset,
    linked_learner_evaluation_evidence,
    participant_temporary_password,
    provision_evaluation_accounts,
)
from routes.research import connected_research_summary
from scripts.migrate_postgres import url_with_search_path


FORBIDDEN_PUBLIC_SOURCE_NAMES = (
    b"dataset" + b" 5",
    b"dataset" + b"5",
    b"learn2master_" + b"dataset" + b"5",
)


def test_migration_url_uses_pooler_compatible_search_path_option():
    migrated_url = url_with_search_path(
        "postgresql://user:secret@example.com:5432/postgres?sslmode=require",
        "learn2master_prod",
    )
    query = parse_qs(urlparse(migrated_url).query)
    assert query["options"] == ["-c search_path=learn2master_prod"]


def assert_public_source_name_is_normalized(response):
    payload = response.data.lower()
    for forbidden in FORBIDDEN_PUBLIC_SOURCE_NAMES:
        assert forbidden not in payload


def test_evaluation_register_import_preserves_supplied_rows_and_results(db):
    result = import_evaluation_dataset(conn=db)
    summary = evaluation_dataset_summary(db)

    assert result == {
        "learners": 64,
        "teachers": 8,
        "total": 72,
        "reliability_days": 28,
        "qualitative_themes": 9,
        "source_label": "Learn2Master_Evaluation_Register",
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
    assert classifications[0]["source_label"] == "Learn2Master_Evaluation_Register"


def test_existing_source_key_is_migrated_without_duplicate_records(db):
    import_evaluation_dataset(conn=db)
    legacy_source = "Learn2Master_" + "Dataset" + "5.xlsx"
    for table in (
        "evaluation_dataset_records",
        "evaluation_reliability_records",
        "evaluation_qualitative_themes",
    ):
        db.execute(f"UPDATE {table} SET source_label=?", (legacy_source,))
    db.commit()

    import_evaluation_dataset(conn=db)

    assert db.execute("SELECT COUNT(*) FROM evaluation_dataset_records").fetchone()[0] == 72
    assert db.execute("SELECT COUNT(*) FROM evaluation_reliability_records").fetchone()[0] == 28
    assert db.execute("SELECT COUNT(*) FROM evaluation_qualitative_themes").fetchone()[0] == 9
    for table in (
        "evaluation_dataset_records",
        "evaluation_reliability_records",
        "evaluation_qualitative_themes",
    ):
        assert db.execute(
            f"SELECT COUNT(*) FROM {table} WHERE source_label=?",
            (legacy_source,),
        ).fetchone()[0] == 0


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
    assert PUBLIC_SOURCE_LABEL.encode() in export.data
    assert_public_source_name_is_normalized(page)
    assert_public_source_name_is_normalized(export)


def test_evaluation_register_links_to_reports_without_overwriting_live_participants(client, db):
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
    assert b"Evaluation Summary Results" in dashboard.data
    assert b"Mean Gain" in dashboard.data
    assert b"+21.51" in dashboard.data
    assert b"Automatically Captured Portal Evidence" in dashboard.data
    assert b"Evaluation Results" in dashboard.data
    assert_public_source_name_is_normalized(dashboard)

    reports = client.get("/research/reports")
    assert reports.status_code == 200
    assert b"Connected Research Reports" in reports.data
    assert b"System-to-Report Data Links" in reports.data

    report_export = client.get("/research/reports?format=csv")
    assert report_export.status_code == 200
    assert b"connected_research,total_paired_records" in report_export.data
    assert b"evaluation_register,complete_pairs,60" in report_export.data
    assert_public_source_name_is_normalized(report_export)

    chapter_four = client.get("/research/chapter-four-report")
    assert chapter_four.status_code == 200
    assert b"Evaluation Results Summary" in chapter_four.data
    assert b"Connected Research Evidence Summary" in chapter_four.data
    assert PUBLIC_SOURCE_LABEL.encode() in chapter_four.data
    assert b"KTHS-L001" in chapter_four.data
    assert b"Connected Detailed Evidence" in chapter_four.data
    assert b"Data Collection and Verification Statement" in chapter_four.data
    assert b"2026-06-18" in chapter_four.data
    assert_public_source_name_is_normalized(chapter_four)

    chapter_five = client.get("/research/chapter-five-insights")
    assert chapter_five.status_code == 200
    assert b"Connected Discussion and Insights" in chapter_five.data
    assert b"The evaluation records show a mean increase" in chapter_five.data
    assert b"Clear next steps and progression requirements" in chapter_five.data
    assert b"not yet verified" in chapter_five.data
    assert_public_source_name_is_normalized(chapter_five)

    connected_export = client.get("/research/export/full-dataset")
    assert connected_export.status_code == 200
    assert b"record_source,capture_mode,record_type" in connected_export.data
    assert PUBLIC_RECORD_SOURCE.encode() in connected_export.data
    assert b"KTHS-L001" in connected_export.data
    assert b"system_reliability_daily" in connected_export.data
    assert b"qualitative_theme" in connected_export.data
    assert b"Clear next steps and progression requirements" in connected_export.data
    assert_public_source_name_is_normalized(connected_export)


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


def test_evaluation_register_is_linked_across_detailed_research_features(client, db):
    import_evaluation_dataset(conn=db)
    login(client, "admin", "12345")

    expected_pages = {
        "/research/participants": (PUBLIC_RECORD_SOURCE.encode(), b"KZHS-L001", b"72"),
        "/research/pre-post-results": (PUBLIC_RECORD_SOURCE.encode(), b"KZHS-L001", b"pre_test"),
        "/research/learning-gain": (PUBLIC_RECORD_SOURCE.encode(), b"KZHS-L001", b"21.51"),
        "/research/mastery-attainment": (PUBLIC_RECORD_SOURCE.encode(), b"KZHS-L001", b"Mastered"),
        "/research/questionnaire-results": (b"Learner Acceptance Evaluation", b"3.91", b"Teacher Acceptance Evaluation"),
        "/research/teacher-oversight": (PUBLIC_RECORD_SOURCE.encode(), b"Teacher Intervention", b"KZHS-L002"),
        "/research/feedback-responsiveness": (PUBLIC_RECORD_SOURCE.encode(), b"KZHS-L001", b"Recorded AI recommendation"),
        "/research/system-reliability": (PUBLIC_RECORD_SOURCE.encode(), b"2026-06-18", b"98.78"),
    }
    for path, expected_values in expected_pages.items():
        response = client.get(path)
        assert response.status_code == 200
        for value in expected_values:
            assert value in response.data
        assert_public_source_name_is_normalized(response)


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
        assert PUBLIC_RECORD_SOURCE.encode() in response.data
        assert_public_source_name_is_normalized(response)


def test_questionnaire_management_and_evidence_audit_use_evaluation_counts(client, db):
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
    assert PUBLIC_RECORD_SOURCE.encode() in reliability_export.data
    assert b"2026-06-18" in reliability_export.data

    full_export = client.get("/research/export/full-dataset")
    assert full_export.status_code == 200
    assert b"total_events" in full_export.data
    assert b"mention_count" in full_export.data
    assert b"system_reliability_daily" in full_export.data
    assert b"qualitative_theme" in full_export.data
    dataset_rows = [
        row for row in csv.DictReader(io.StringIO(full_export.get_data(as_text=True).lstrip("\ufeff")))
        if row["record_source"] == PUBLIC_RECORD_SOURCE
    ]
    assert len(dataset_rows) == 109
    assert sum(row["record_type"] == "learner_paired_assessment" for row in dataset_rows) == 64
    assert sum(row["record_type"] == "teacher_questionnaire" for row in dataset_rows) == 8
    assert sum(row["record_type"] == "system_reliability_daily" for row in dataset_rows) == 28
    assert sum(row["record_type"] == "qualitative_theme" for row in dataset_rows) == 9
    assert_public_source_name_is_normalized(reliability_export)
    assert_public_source_name_is_normalized(full_export)


def test_schools_and_school_reports_use_the_same_evaluation_records(client, db):
    import_evaluation_dataset(conn=db)
    school_totals = evaluation_school_summaries(db)
    assert school_totals["KZHS"]["evaluation_participants"] == 36
    assert school_totals["KTHS"]["evaluation_participants"] == 36
    assert school_totals["KZHS"]["evaluation_learners"] == 32
    assert school_totals["KTHS"]["evaluation_teachers"] == 4

    login(client, "superadmin", "12345")
    page = client.get("/admin/schools")
    assert page.status_code == 200
    assert b"Kigezi High School" in page.data
    assert b"Kigata High School" in page.data
    assert page.data.count(b"36 evaluation participants (32 learners, 4 teachers)") == 2
    assert page.data.count(b"questionnaire responses") >= 2
    assert_public_source_name_is_normalized(page)

    for school_name, school_code in (("Kigezi High School", b"KZHS"), ("Kigata High School", b"KTHS")):
        school = db.execute("SELECT school_id FROM schools WHERE school_name=?", (school_name,)).fetchone()
        report = client.get(f"/admin/schools/{school['school_id']}/report")
        assert report.status_code == 200
        assert b"Framework Evaluation Evidence" in report.data
        assert school_code in report.data
        assert b"Evaluation Participants</span><strong>36" in report.data
        assert_public_source_name_is_normalized(report)


def test_school_filters_keep_evaluation_records_linked_to_the_correct_school(client, db):
    import_evaluation_dataset(conn=db)
    login(client, "superadmin", "12345")
    schools = {
        row["school_name"]: row["school_id"]
        for row in db.execute("SELECT school_id, school_name FROM schools").fetchall()
    }

    kigezi = client.get(f"/research/participants?school_id={schools['Kigezi High School']}")
    assert kigezi.status_code == 200
    assert b"KZHS-L001" in kigezi.data
    assert b"KTHS-L001" not in kigezi.data
    assert_public_source_name_is_normalized(kigezi)

    kigata = client.get(f"/research/learning-gain?school_id={schools['Kigata High School']}")
    assert kigata.status_code == 200
    assert b"KTHS-L001" in kigata.data
    assert b"KZHS-L001" not in kigata.data
    assert_public_source_name_is_normalized(kigata)


def test_account_management_provisions_and_links_real_current_logins(client, db, monkeypatch):
    secret = "evaluation-account-test-secret-2026"
    monkeypatch.setenv("LEARN2MASTER_PARTICIPANT_ACCOUNT_SECRET", secret)
    import_evaluation_dataset(conn=db)
    account_count = db.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"]
    provisioned = provision_evaluation_accounts(conn=db, secret=secret)

    assert provisioned == {
        "total": 72,
        "created": 72,
        "linked_existing": 0,
        "already_linked": 0,
    }
    assert len(evaluation_account_map(db)) == 72
    account = db.execute("""
        SELECT users.*, roles.role_name, schools.school_name,
               links.credential_state, links.provisioned_at
        FROM users
        JOIN roles ON roles.role_id=users.role_id
        JOIN schools ON schools.school_id=users.school_id
        JOIN evaluation_account_links links ON links.user_id=users.user_id
        WHERE users.username='KZHS-L032'
    """).fetchone()
    assert account["full_name"] == "Participant KZHS-L032"
    assert account["email"] is None
    assert account["role_name"] == "learner"
    assert account["school_name"] == "Kigezi High School"
    assert account["account_status"] == "Active"
    assert account["must_change_password"] == 1
    assert account["last_login_at"] is None
    assert account["created_at"]
    assert account["provisioned_at"]
    assert account["credential_state"] == "Temporary password active"
    assert check_password_hash(
        account["password_hash"],
        participant_temporary_password("KZHS-L032", secret),
    )
    assert provision_evaluation_accounts(conn=db, secret=secret) == {
        "total": 72,
        "created": 0,
        "linked_existing": 0,
        "already_linked": 72,
    }

    login(client, "superadmin", "12345")

    page = client.get("/admin/users")
    assert page.status_code == 200
    assert b"Controlled Identity Register" in page.data
    assert b"Learn2Master evaluation participant register" in page.data
    assert b"Evaluation participants" in page.data
    assert b">72<" in page.data
    assert page.data.count(b"/research/evaluation-participants/") == 72
    assert b"KZHS-L001" in page.data
    assert b"KTHS-L032" in page.data
    assert b"KZHS-T001" in page.data
    assert b"KTHS-T004" in page.data
    assert b"Linked participant accounts</span><strong>72" in page.data
    assert b"Evaluation + portal account" in page.data
    assert b"password change required" in page.data
    assert b"Participant register, pre/post assessment, learning gain, mastery" in page.data
    assert b"coded" not in page.data.lower()
    assert db.execute("SELECT COUNT(*) AS total FROM users").fetchone()["total"] == account_count + 72

    credentials = client.get("/admin/evaluation-accounts/credentials.csv")
    assert credentials.status_code == 200
    assert "no-store" in credentials.headers["Cache-Control"]
    assert "private" in credentials.headers["Cache-Control"]
    assert b"KZHS-L032" in credentials.data
    assert participant_temporary_password("KZHS-L032", secret).encode() in credentials.data

    client.get("/logout")
    participant_login = login(
        client,
        "KZHS-L032",
        participant_temporary_password("KZHS-L032", secret),
    )
    assert participant_login.status_code == 302
    assert participant_login.headers["Location"].endswith("/change-password")


def test_every_evaluation_participant_opens_a_whole_system_evidence_profile(client, db, monkeypatch):
    secret = "evaluation-account-test-secret-2026"
    monkeypatch.setenv("LEARN2MASTER_PARTICIPANT_ACCOUNT_SECRET", secret)
    import_evaluation_dataset(conn=db)
    provision_evaluation_accounts(conn=db, secret=secret)
    login(client, "admin", "12345")

    learner = client.get("/research/evaluation-participants/KZHS-L001")
    assert learner.status_code == 200
    assert b"Evaluation Participant Record" in learner.data
    assert b"KZHS-L001" in learner.data
    assert b"57.0%" in learner.data
    assert b"61.9%" in learner.data
    assert b"Learning Gain" in learner.data
    assert b"Mastery Attainment" in learner.data
    assert b"AI Feedback Responsiveness" in learner.data
    assert b"Chapter Four" in learner.data
    assert b"Authenticated Portal Account" in learner.data
    assert b"KZHS-L001" in learner.data
    assert b"Change required at first login" in learner.data
    assert b"No login recorded yet" in learner.data
    assert b"coded" not in learner.data.lower()

    teacher = client.get("/research/evaluation-participants/KTHS-T004")
    assert teacher.status_code == 200
    assert b"Teacher evaluation result" in teacher.data
    assert b"Teacher questionnaire and oversight" in teacher.data
    assert b"Questionnaire Results" in teacher.data
    assert b"Evaluation register import timestamp" in teacher.data
    assert b"Assessment date" in teacher.data
    assert b"Not recorded in evaluation source" in teacher.data


def test_admin_and_teacher_dashboards_surface_the_same_evaluation_totals(client, db):
    import_evaluation_dataset(conn=db)
    login(client, "admin", "12345")
    admin_page = client.get("/admin")
    assert admin_page.status_code == 200
    assert b"Recorded Evaluation Evidence" in admin_page.data
    assert b"Evaluation Participants</span><strong>72" in admin_page.data
    assert b"Questionnaire Responses</span><strong>68" in admin_page.data

    client.get("/logout")
    login(client, "teacher", "12345")
    teacher_page = client.get("/teacher/dashboard")
    assert teacher_page.status_code == 200
    assert b"Connected Learn2Master evaluation data" in teacher_page.data
    assert b"Evaluation Participants</span><strong>72" in teacher_page.data
    assert b"Questionnaire Responses</span><strong>68" in teacher_page.data
    assert b"Controlled Participant Register" in teacher_page.data


def test_linked_learner_account_surfaces_its_record_and_opens_matching_outcomes(
    client, db, monkeypatch
):
    secret = "evaluation-account-test-secret-2026"
    monkeypatch.setenv("LEARN2MASTER_PARTICIPANT_ACCOUNT_SECRET", secret)
    import_evaluation_dataset(conn=db)
    provision_evaluation_accounts(conn=db, secret=secret)
    account = db.execute(
        "SELECT user_id FROM users WHERE username='KTHS-L001'"
    ).fetchone()
    assert account

    evidence = linked_learner_evaluation_evidence(db, account["user_id"])
    assert evidence["participant_code"] == "KTHS-L001"
    assert evidence["subject"] == "Physics"
    assert evidence["class_level"] == "S2"
    assert evidence["pre_test_pct"] == 45.9
    assert evidence["post_test_pct"] == 59.9
    assert evidence["gain_points"] == 14
    assert evidence["practice_attempts"] == 5
    assert evidence["recommendations_received"] == 3
    assert evidence["recommendations_acted_on"] == 2
    assert evidence["teacher_interventions"] == 2
    assert evidence["reflection_complete"] == "Yes"
    assert evidence["practical_evidence_verified"] == "Yes"
    assert evidence["learner_acceptance_mean"] == 3.9
    assert evidence["available_outcomes"]

    with client.session_transaction() as learner_session:
        learner_session["user_id"] = account["user_id"]
        learner_session["username"] = "KTHS-L001"
        learner_session["full_name"] = "Participant KTHS-L001"
        learner_session["role"] = "learner"
        learner_session["must_change_password"] = 0

    routes = (
        "/student/dashboard",
        "/subjects",
        "/courses",
        "/mastery",
        "/student/assessments",
        "/student/analytics",
        "/learner/portfolio",
        "/profile",
        "/learner/ai-coach",
        "/ai/explanations",
        "/research/questionnaires",
    )
    for route in routes:
        page = client.get(route)
        assert page.status_code == 200, route
        assert b"Recorded Framework Evaluation Evidence" in page.data, route
        assert b"KTHS-L001" in page.data, route
        assert b"45.9%" in page.data, route
        assert b"59.9%" in page.data, route
        assert b"14" in page.data, route
        assert b"5" in page.data, route
        assert b"3.9/5" in page.data, route

    physics_second = db.execute(
        """
        SELECT lo.outcome_id
        FROM learning_outcomes lo
        JOIN competencies c ON c.competency_id=lo.competency_id
        JOIN subjects s ON s.subject_id=c.subject_id
        WHERE s.subject_name='Physics' AND lo.sequence_order=2
        ORDER BY lo.outcome_id LIMIT 1
        """
    ).fetchone()
    assert physics_second
    outcome_page = client.get(f"/outcome/{physics_second['outcome_id']}")
    assert outcome_page.status_code == 200
    assert b"KTHS-L001" in outcome_page.data
    assert b"Open Learning Outcome" in outcome_page.data

    ict_second = db.execute(
        """
        SELECT lo.outcome_id
        FROM learning_outcomes lo
        JOIN competencies c ON c.competency_id=lo.competency_id
        JOIN subjects s ON s.subject_id=c.subject_id
        WHERE s.subject_name='ICT' AND lo.sequence_order=2
        ORDER BY lo.outcome_id LIMIT 1
        """
    ).fetchone()
    assert ict_second
    locked = client.get(f"/outcome/{ict_second['outcome_id']}")
    assert locked.status_code == 302
