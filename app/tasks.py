"""Background document processing."""

from __future__ import annotations

import logging
import uuid

import app.database as database
from app.celery_app import celery
from app.models import Document, DocumentStage, DocumentStatus, as_value, utcnow
from app.services.extraction import extract_file
from app.services.parsing import detect_doc_type, parse_structured
from app.services.storage import resolve_storage_path

logger = logging.getLogger(__name__)


@celery.task(name="documents.process", bind=True)
def process_document(self, document_id: str) -> None:
    database.init_engine()
    db = database.SessionLocal()
    try:
        doc = db.get(Document, uuid.UUID(document_id))
        if doc is None:
            logger.info("document %s no longer exists", document_id)
            return

        doc.status = DocumentStatus.processing.value
        doc.stage = DocumentStage.extracting.value
        doc.error_message = None
        doc.task_id = getattr(self.request, "id", None)
        doc.updated_at = utcnow()
        db.commit()

        path = resolve_storage_path(doc.storage_path)
        extracted = extract_file(path, as_value(doc.content_type))

        doc.raw_text = extracted.text
        doc.page_count = extracted.page_count
        doc.extraction_method = extracted.method
        doc.stage = DocumentStage.parsing.value
        doc.updated_at = utcnow()
        db.commit()

        detected = detect_doc_type(extracted.text)
        hint = as_value(doc.source_hint)
        chosen = hint if hint in {"invoice", "resume"} else detected
        doc.detected_type = detected
        doc.doc_type = chosen
        doc.structured = parse_structured(chosen, extracted.text)
        doc.stage = DocumentStage.indexing.value
        doc.updated_at = utcnow()
        db.commit()

        doc.status = DocumentStatus.completed.value
        doc.stage = DocumentStage.done.value
        doc.processed_at = utcnow()
        doc.updated_at = doc.processed_at
        db.commit()
    except Exception as exc:
        logger.exception("processing failed for document %s", document_id)
        db.rollback()
        _mark_failed(document_id, exc)
    finally:
        db.close()


def _mark_failed(document_id: str, exc: Exception) -> None:
    db = database.SessionLocal()
    try:
        doc = db.get(Document, uuid.UUID(document_id))
        if doc is None:
            return
        message = str(exc).strip() or "Processing failed"
        doc.status = DocumentStatus.failed.value
        doc.stage = DocumentStage.failed.value
        doc.error_message = message[:2000]
        doc.processed_at = utcnow()
        doc.updated_at = doc.processed_at
        db.commit()
    finally:
        db.close()
