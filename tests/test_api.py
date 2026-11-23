import io
import json
from pathlib import Path

import fitz
import pytest
from PIL import Image

from app.config import get_settings
from app.services.extraction import ExtractionError, extract_file
from tests.pdfutil import write_pdf
from tests.samples import GENERIC_TEXT, INVOICE_TEXT, RESUME_TEXT


def _pdf_bytes(text: str, name: str = "document.pdf") -> tuple[str, bytes, str]:
    buffer = io.BytesIO()
    document = fitz.open()
    page = document.new_page()
    y = 72
    for line in text.splitlines():
        page.insert_text((72, y), line if line else " ", fontsize=11)
        y += 14
    document.save(buffer)
    document.close()
    return name, buffer.getvalue(), "application/pdf"


def _upload(client, filename: str, data: bytes, content_type: str, doc_type: str = "auto"):
    return client.post(
        "/api/v1/documents",
        files={"file": (filename, data, content_type)},
        data={"doc_type": doc_type},
    )


def test_health_and_root(client):
    assert client.get("/health").json()["status"] == "ok"
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["docs"] == "/docs"


def test_ready_reports_database(client):
    response = client.get("/ready")
    body = response.json()
    assert body["database"] == "ok"
    assert body["redis"] in {"ok", "unavailable"}
    expected = 200 if body["redis"] == "ok" else 503
    assert response.status_code == expected


def test_upload_invoice_pdf_extracts_structured_json(client, tmp_path: Path):
    pdf_path = tmp_path / "invoice.pdf"
    write_pdf(pdf_path, INVOICE_TEXT)
    response = _upload(client, "invoice.pdf", pdf_path.read_bytes(), "application/pdf", "invoice")

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "completed"
    assert body["stage"] == "done"
    assert body["doc_type"] == "invoice"
    assert body["extraction_method"] == "text-layer"
    assert body["structured"]["invoice_number"] == "INV-2026-0142"
    assert body["structured"]["total"] == "70.74"
    assert body["structured"]["vendor_name"] == "ACME SUPPLIES INC"
    assert body["text_characters"] > 0

    document_id = body["id"]
    status = client.get(f"/api/v1/documents/{document_id}/status")
    assert status.json()["status"] == "completed"

    exported = client.get(f"/api/v1/documents/{document_id}/json")
    assert exported.status_code == 200
    assert exported.headers["content-disposition"] == 'attachment; filename="invoice.json"'
    payload = json.loads(exported.content)
    assert payload["structured"]["line_items"][0]["description"] == "Widget A"
    assert "INV-2026-0142" in payload["extracted_text"]


def test_upload_resume_and_search_extracted_text(client):
    filename, data, content_type = _pdf_bytes(RESUME_TEXT, "jane-resume.pdf")
    created = _upload(client, filename, data, content_type, "auto")
    assert created.status_code == 202
    body = created.json()
    assert body["detected_type"] == "resume"
    assert body["doc_type"] == "resume"
    assert body["structured"]["email"] == "jane.doe@example.com"
    assert "FastAPI" in body["structured"]["skills"]

    search = client.get("/api/v1/search", params={"q": "Northwind"})
    assert search.status_code == 200
    assert search.json()["total"] == 0

    found = client.get("/api/v1/search", params={"q": "Contoso"})
    assert found.status_code == 200
    payload = found.json()
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == body["id"]
    assert "Contoso" in payload["items"][0]["snippet"]

    listed = client.get("/api/v1/documents", params={"q": "jane.doe@example.com", "doc_type": "resume"})
    assert listed.json()["total"] == 1


def test_generic_document_has_no_structured_kind_mismatch(client):
    filename, data, content_type = _pdf_bytes(GENERIC_TEXT, "notes.pdf")
    response = _upload(client, filename, data, content_type, "auto")
    body = response.json()
    assert body["doc_type"] == "generic"
    assert body["structured"]["kind"] == "generic"


def test_image_upload_uses_ocr_text(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "app.services.extraction.pytesseract.image_to_string",
        lambda image: RESUME_TEXT,
    )
    buffer = io.BytesIO()
    Image.new("RGB", (120, 40), "white").save(buffer, format="PNG")
    response = _upload(client, "resume.png", buffer.getvalue(), "image/png", "resume")

    assert response.status_code == 202
    body = response.json()
    assert body["extraction_method"] == "ocr"
    assert body["structured"]["name"] == "Jane Doe"


def test_rejects_unsupported_empty_and_mismatched_files(client):
    rejected = _upload(client, "notes.txt", b"hello", "text/plain")
    assert rejected.status_code == 400

    empty = _upload(client, "empty.pdf", b"", "application/pdf")
    assert empty.status_code == 400

    fake = _upload(client, "fake.pdf", b"not a pdf", "application/pdf")
    assert fake.status_code == 400

    unknown_type = _upload(client, "invoice.pdf", b"%PDF-1.4", "application/pdf", "spreadsheet")
    assert unknown_type.status_code == 400


def test_rejects_files_over_the_configured_limit(client, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(get_settings(), "max_upload_bytes", 8)
    filename, data, content_type = _pdf_bytes(INVOICE_TEXT, "big.pdf")
    response = _upload(client, filename, data, content_type)
    assert response.status_code == 413


def test_filename_is_stored_as_a_basename(client):
    filename, data, content_type = _pdf_bytes(GENERIC_TEXT, "notes.pdf")
    response = _upload(client, "../../notes.pdf", data, content_type)
    assert response.status_code == 202
    assert response.json()["filename"] == "notes.pdf"


def test_json_download_waits_until_processing_finishes(client, monkeypatch: pytest.MonkeyPatch):
    class _Queued:
        id = "task-pending"

    monkeypatch.setattr("app.api.routes.documents.process_document.delay", lambda document_id: _Queued())
    filename, data, content_type = _pdf_bytes(INVOICE_TEXT, "invoice.pdf")
    created = _upload(client, filename, data, content_type, "invoice")
    assert created.status_code == 202
    assert created.json()["status"] == "pending"
    document_id = created.json()["id"]

    exported = client.get(f"/api/v1/documents/{document_id}/json")
    assert exported.status_code == 409

    again = client.post(f"/api/v1/documents/{document_id}/reprocess")
    assert again.status_code == 409


def test_processing_failure_is_recorded(client, monkeypatch: pytest.MonkeyPatch):
    def explode(path, content_type):
        raise ExtractionError("Could not read the PDF")

    monkeypatch.setattr("app.tasks.extract_file", explode)
    filename, data, content_type = _pdf_bytes(INVOICE_TEXT, "invoice.pdf")
    response = _upload(client, filename, data, content_type)
    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "failed"
    assert "Could not read the PDF" in body["error_message"]

    exported = client.get(f"/api/v1/documents/{body['id']}/json")
    assert exported.status_code == 200
    assert json.loads(exported.content)["status"] == "failed"


def test_reprocess_runs_extraction_again_and_delete_removes_it(client, monkeypatch: pytest.MonkeyPatch):
    calls = {"count": 0}
    original = extract_file

    def wrapped(path, content_type):
        calls["count"] += 1
        return original(path, content_type)

    monkeypatch.setattr("app.tasks.extract_file", wrapped)
    filename, data, content_type = _pdf_bytes(INVOICE_TEXT, "invoice.pdf")
    created = _upload(client, filename, data, content_type, "invoice")
    document_id = created.json()["id"]
    assert calls["count"] == 1

    reprocessed = client.post(f"/api/v1/documents/{document_id}/reprocess")
    assert reprocessed.status_code == 202
    assert reprocessed.json()["status"] == "completed"
    assert calls["count"] == 2

    deleted = client.delete(f"/api/v1/documents/{document_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/v1/documents/{document_id}").status_code == 404


def test_missing_document_returns_404(client):
    missing = "11111111-1111-1111-1111-111111111111"
    assert client.get(f"/api/v1/documents/{missing}").status_code == 404
