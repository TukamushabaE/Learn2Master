from io import BytesIO

from conftest import login


def test_learner_sidebar_database_routes_render(client):
    login(client, "elijah", "12345")

    assert client.get("/student/dashboard").status_code == 200
    assert client.get("/student/assessments").status_code == 200


def test_teacher_learner_list_and_material_upload_render(client):
    login(client, "teacher", "12345")

    assert client.get("/teacher/learners").status_code == 200
    assert client.get("/teacher/kb/upload").status_code == 200


def test_teacher_can_upload_study_material(client, monkeypatch, tmp_path, db):
    class TestKnowledgeBase:
        directory = tmp_path

        @staticmethod
        def process_file(filepath, metadata=None, summarize=False):
            assert metadata and metadata.get("teacher_id")
            assert summarize is True
            return True, 24

    monkeypatch.setattr("routes.teacher.get_kb", lambda: TestKnowledgeBase())
    login(client, "teacher", "12345")

    response = client.post(
        "/teacher/kb/upload",
        data={"file": (BytesIO(b"A short study guide."), "study-guide.txt")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    upload = db.execute(
        "SELECT filename, original_size_bytes, summary_size_bytes FROM teacher_kb_uploads "
        "WHERE filename = ?",
        ("study-guide.txt",),
    ).fetchone()
    assert upload is not None
    assert upload["original_size_bytes"] == len(b"A short study guide.")
    assert upload["summary_size_bytes"] == 24


def test_super_admin_can_upload_knowledge_base_material(client, monkeypatch, tmp_path):
    class TestKnowledgeBase:
        directory = tmp_path

        @staticmethod
        def process_file(filepath):
            assert (tmp_path / "curriculum-notes.md").read_text() == "# Curriculum notes"
            return True, 0

    monkeypatch.setattr("routes.admin.get_kb", lambda: TestKnowledgeBase())
    login(client, "superadmin", "12345")

    response = client.post(
        "/admin/kb/upload",
        data={"file": (BytesIO(b"# Curriculum notes"), "curriculum-notes.md")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302


def test_super_admin_curriculum_grouping_pages_render(client):
    login(client, "superadmin", "12345")

    assert client.get("/admin/curriculum").status_code == 200
    assert client.get("/admin/competencies").status_code == 200
    assert client.get("/admin/question-bank").status_code == 200
