import subprocess

import engine
from conftest import login
from engine import KnowledgeBase
from routes.learning import get_required_concepts


def test_required_concepts_query_is_postgres_safe():
    class Result:
        @staticmethod
        def fetchall():
            return [{"concept_tag": "electric_current"}]

    class StrictPostgresConnection:
        @staticmethod
        def execute(sql, parameters):
            normalized = " ".join(sql.split())
            assert parameters == (5,)
            assert "SELECT DISTINCT" not in normalized
            assert "GROUP BY concept_tag" in normalized
            assert "ORDER BY MIN(priority), concept_tag" in normalized
            return Result()

    assert get_required_concepts(StrictPostgresConnection(), 5) == ["electric_current"]


def test_teacher_upload_page_does_not_initialize_knowledge_base(client, monkeypatch):
    def fail_if_called():
        raise AssertionError("GET upload page must not process knowledge-base files")

    monkeypatch.setattr("routes.teacher.get_kb", fail_if_called)
    login(client, "teacher", "12345")

    assert client.get("/teacher/kb/upload").status_code == 200


def test_pdf_timeout_is_remembered_without_retry(monkeypatch, tmp_path):
    kb = KnowledgeBase(directory=str(tmp_path))
    pdf = tmp_path / "complex-study.pdf"
    pdf.write_bytes(b"%PDF-1.7 complex test content")
    calls = []

    def timeout(*args, **kwargs):
        calls.append(args)
        raise subprocess.TimeoutExpired(cmd="pdftotext", timeout=8)

    monkeypatch.setattr(engine.subprocess, "run", timeout)

    assert kb.process_file(str(pdf), summarize=True) == (False, 0)
    assert kb.process_file(str(pdf), summarize=True) == (False, 0)
    assert len(calls) == 1
    assert kb._processed_files[pdf.name].startswith("failed:")
