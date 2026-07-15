from io import BytesIO

import pytest

import engine
from conftest import login
from engine import KnowledgeBase


def test_teacher_document_limits_and_format_catalog():
    assert engine.TEACHER_KB_STORAGE_LIMIT_BYTES == 1024 * 1024 * 1024
    assert engine.MAX_FILE_BYTES == 100 * 1024 * 1024
    assert {
        ".pdf", ".doc", ".docx", ".xlsx", ".pptx", ".odt", ".ods",
        ".odp", ".rtf", ".epub", ".eml", ".csv", ".json", ".xml",
    } <= engine.SUPPORTED_DOCUMENT_EXTENSIONS


def test_teacher_upload_page_explains_limits_and_formats(client):
    login(client, "teacher", "12345")

    response = client.get("/teacher/kb/upload")

    assert response.status_code == 200
    assert b"1 GB" in response.data
    assert b"100" in response.data and b"MB" in response.data
    assert b".docx" in response.data
    assert b"PowerPoint" in response.data


def test_teacher_can_upload_new_document_format(client, monkeypatch, tmp_path, db):
    class TestKnowledgeBase:
        directory = tmp_path

        @staticmethod
        def process_file(filepath, metadata=None, summarize=False):
            assert filepath.endswith("lesson-notes.docx")
            assert metadata and metadata.get("teacher_id")
            assert summarize is True
            return True, 42

    monkeypatch.setattr("routes.teacher.get_kb", lambda: TestKnowledgeBase())
    login(client, "teacher", "12345")

    response = client.post(
        "/teacher/kb/upload",
        data={"file": (BytesIO(b"safe document payload"), "lesson-notes.docx")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    upload = db.execute(
        "SELECT original_size_bytes, summary_size_bytes FROM teacher_kb_uploads WHERE filename = ?",
        ("lesson-notes.docx",),
    ).fetchone()
    assert upload is not None
    assert upload["original_size_bytes"] == len(b"safe document payload")
    assert upload["summary_size_bytes"] == 42


def test_teacher_upload_rejects_document_above_per_file_limit(client, monkeypatch, db):
    monkeypatch.setattr("routes.teacher.MAX_FILE_BYTES", 10)
    monkeypatch.setattr(
        "routes.teacher.get_kb",
        lambda: pytest.fail("Oversized documents must be rejected before KB initialization"),
    )
    login(client, "teacher", "12345")

    response = client.post(
        "/teacher/kb/upload",
        data={"file": (BytesIO(b"eleven-bytes"), "oversized.docx")},
        content_type="multipart/form-data",
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"each document is limited" in response.data
    assert db.execute(
        "SELECT 1 FROM teacher_kb_uploads WHERE filename = ?", ("oversized.docx",)
    ).fetchone() is None


def test_teacher_upload_has_friendly_request_size_error(app, client, monkeypatch):
    monkeypatch.setitem(app.config, "MAX_CONTENT_LENGTH", 100)
    login(client, "teacher", "12345")

    response = client.post(
        "/teacher/kb/upload",
        data={"file": (BytesIO(b"document"), "lesson.docx")},
        content_type="multipart/form-data",
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/teacher/kb/upload")


def test_common_rich_document_extractors(tmp_path):
    docx = pytest.importorskip("docx")
    openpyxl = pytest.importorskip("openpyxl")
    pptx = pytest.importorskip("pptx")

    word_path = tmp_path / "mastery.docx"
    word = docx.Document()
    word.add_paragraph("Mastery learning from Word")
    word.save(word_path)

    excel_path = tmp_path / "scores.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.append(["Learner", "Mastery score"])
    workbook.active.append(["Elijah", 85])
    workbook.save(excel_path)

    slides_path = tmp_path / "lesson.pptx"
    presentation = pptx.Presentation()
    slide = presentation.slides.add_slide(presentation.slide_layouts[5])
    slide.shapes.title.text = "CBC learning outcome"
    presentation.save(slides_path)

    rtf_path = tmp_path / "notes.rtf"
    rtf_path.write_text(r"{\rtf1\ansi Mastery notes from RTF}", encoding="utf-8")

    kb = KnowledgeBase(directory=str(tmp_path / "kb"))
    assert "Mastery learning from Word" in kb._extract_document_text(word_path)
    assert "Elijah" in kb._extract_document_text(excel_path)
    assert "CBC learning outcome" in kb._extract_document_text(slides_path)
    assert "Mastery notes from RTF" in kb._extract_document_text(rtf_path)
