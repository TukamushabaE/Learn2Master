from io import BytesIO

from conftest import login
from engine import KnowledgeBase


def test_teacher_action_pages_share_modern_shell(client, monkeypatch):
    class FakeKnowledgeBase:
        chunks = ["CBC mastery evidence"]

    monkeypatch.setattr("routes.teacher.get_kb", lambda: FakeKnowledgeBase())
    login(client, "teacher", "12345")

    for route in (
        "/teacher/students/pending",
        "/teacher/students/assign-subjects",
        "/teacher/students/create",
        "/teacher/kb/upload",
        "/teacher/kb",
    ):
        response = client.get(route)
        assert response.status_code == 200, route
        assert b'class="app-shell"' in response.data
        assert b"Teacher Portal" in response.data
        assert b'id="wrapper"' not in response.data


def test_password_pages_load_accessible_visibility_control(client):
    for route in ("/login", "/register"):
        response = client.get(route)
        assert response.status_code == 200
        assert b"password_visibility.js" in response.data

    script = client.get("/static/js/password_visibility.js")
    assert script.status_code == 200
    assert b'button.type = "button"' in script.data
    assert b'button.textContent = "Show"' in script.data
    assert b'"Hide"' in script.data
    assert b"aria-pressed" in script.data


def test_chapter_guide_explains_proposal_boundary_and_live_readiness(client):
    login(client, "teacher", "12345")
    response = client.get("/research/chapter-guide")

    assert response.status_code == 200
    assert b"ends after Chapter 3" in response.data
    assert b"without inventing" in response.data
    assert b"Readiness does not mean completeness" in response.data
    assert b"Discussion by objective" in response.data


def test_supabase_storage_upload_uses_private_teacher_path(tmp_path):
    uploaded = {}

    class Bucket:
        def upload(self, **kwargs):
            uploaded.update(kwargs)

        def remove(self, paths):
            uploaded["removed"] = paths

    class Storage:
        def from_(self, bucket):
            uploaded["bucket"] = bucket
            return Bucket()

    class Client:
        storage = Storage()

    document = tmp_path / "lesson notes.txt"
    document.write_text("Mastery learning notes", encoding="utf-8")
    kb = KnowledgeBase.__new__(KnowledgeBase)
    kb.supabase = Client()
    kb.storage_bucket = "knowledge-base"

    result = kb.upload_source_document(document, teacher_id=7, content_type="text/plain")

    assert uploaded["bucket"] == "knowledge-base"
    assert uploaded["path"].startswith("teachers/7/")
    assert uploaded["file_options"]["content-type"] == "text/plain"
    assert uploaded["file_options"]["upsert"] == "true"
    assert result["provider"] == "supabase"
    assert result["path"] == uploaded["path"]


def test_teacher_upload_records_supabase_metadata(client, db, monkeypatch, tmp_path):
    class FakeKnowledgeBase:
        directory = tmp_path

        @staticmethod
        def upload_source_document(filepath, teacher_id, content_type=None):
            return {
                "provider": "supabase",
                "bucket": "knowledge-base",
                "path": f"teachers/{teacher_id}/lesson.txt",
                "content_hash": "abc123",
                "mime_type": content_type,
            }

        @staticmethod
        def process_file(filepath, metadata=None, summarize=False):
            return True, 22

        @staticmethod
        def processed_text_for(filepath):
            return "Processed mastery text"

    monkeypatch.setattr("routes.teacher.supabase_storage_configured", lambda: True)
    monkeypatch.setattr("routes.teacher.get_kb", lambda: FakeKnowledgeBase())
    login(client, "teacher", "12345")

    response = client.post(
        "/teacher/kb/upload",
        data={"file": (BytesIO(b"mastery lesson"), "lesson.txt")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    row = db.execute("""
        SELECT storage_provider, storage_bucket, storage_path, storage_status, processed_text
        FROM teacher_kb_uploads WHERE filename='lesson.txt'
    """).fetchone()
    assert row["storage_provider"] == "supabase"
    assert row["storage_bucket"] == "knowledge-base"
    assert row["storage_path"].startswith("teachers/")
    assert "Supabase" in row["storage_status"]
    assert row["processed_text"] == "Processed mastery text"
