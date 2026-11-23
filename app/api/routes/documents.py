import logging
import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Document, DocumentStage, DocumentStatus, as_value, utcnow
from app.schemas import (
    DocumentDetail,
    DocumentExport,
    DocumentList,
    DocumentStatusView,
    DocumentSummary,
    SearchHit,
    SearchResults,
)
from app.services.search import apply_text_search, snippet_around
from app.services.storage import UploadRejected, delete_stored_file, save_upload, validate_upload
from app.tasks import process_document

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])
search_router = APIRouter(tags=["search"])


@router.post("", response_model=DocumentDetail, status_code=202)
def upload_document(
    file: UploadFile = File(...),
    doc_type: str = Form("auto"),
    db: Session = Depends(get_db),
):
    """Accept a PDF or image and queue background extraction."""
    data = file.file.read()
    try:
        filename, content_type = validate_upload(file.filename, data)
    except UploadRejected as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc

    hint = doc_type.strip().lower()
    allowed = {item.value for item in SourceHint}
    if hint not in allowed:
        raise HTTPException(status_code=400, detail="doc_type must be auto, invoice, or resume")

    document_id = uuid.uuid4()
    path = save_upload(document_id, filename, data)
    doc = Document(
        id=document_id,
        filename=filename,
        content_type=content_type,
        source_hint=hint,
        doc_type=hint if hint in {"invoice", "resume"} else None,
        status=DocumentStatus.pending.value,
        stage=DocumentStage.queued.value,
        storage_path=str(path),
        file_size=len(data),
    )
    db.add(doc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        delete_stored_file(document_id)
        raise
    _enqueue(db, doc)
    db.refresh(doc)
    return _detail(doc)


@router.get("", response_model=DocumentList)
def list_documents(
    q: str | None = Query(default=None, max_length=200),
    status: DocumentStatus | None = None,
    doc_type: str | None = Query(default=None, pattern="^(invoice|resume|generic)$"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """List documents, optionally filtering by status, type, or extracted text."""
    statement = select(Document)
    if status is not None:
        statement = statement.where(Document.status == as_value(status))
    if doc_type is not None:
        statement = statement.where(Document.doc_type == doc_type)
    if q and q.strip():
        statement = apply_text_search(statement, db, q)
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    rows = db.scalars(statement.order_by(Document.created_at.desc()).limit(limit).offset(offset)).all()
    return DocumentList(
        items=[_summary(row, q or "") for row in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@search_router.get("/search", response_model=SearchResults)
def search_documents(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Search completed and in-progress extracted text."""
    statement = apply_text_search(select(Document), db, q)
    total = db.scalar(select(func.count()).select_from(statement.order_by(None).subquery())) or 0
    rows = db.scalars(statement.order_by(Document.created_at.desc()).limit(limit).offset(offset)).all()
    return SearchResults(
        query=q,
        total=total,
        limit=limit,
        offset=offset,
        items=[
            SearchHit(
                id=row.id,
                filename=row.filename,
                doc_type=row.doc_type,
                status=as_value(row.status),
                snippet=snippet_around(row.raw_text, q),
                created_at=row.created_at,
            )
            for row in rows
        ],
    )


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    """Return metadata, extracted text, and structured fields."""
    return _detail(_get_or_404(db, document_id))


@router.get("/{document_id}/status", response_model=DocumentStatusView)
def get_document_status(document_id: uuid.UUID, db: Session = Depends(get_db)):
    """Poll processing status without downloading the extracted body."""
    doc = _get_or_404(db, document_id)
    return DocumentStatusView(
        id=doc.id,
        status=as_value(doc.status),
        stage=as_value(doc.stage),
        doc_type=doc.doc_type,
        error_message=doc.error_message,
        processed_at=doc.processed_at,
    )


@router.get("/{document_id}/json", response_model=DocumentExport)
def download_document_json(document_id: uuid.UUID, db: Session = Depends(get_db)):
    """Download the extraction result as a JSON file."""
    doc = _get_or_404(db, document_id)
    status = as_value(doc.status)
    if status not in {DocumentStatus.completed.value, DocumentStatus.failed.value}:
        raise HTTPException(
            status_code=409,
            detail=f"Document is not ready. Current status: {status}.",
        )
    export = _export(doc)
    return Response(
        content=export.model_dump_json(indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{_download_name(doc.filename)}"'},
    )


@router.post("/{document_id}/reprocess", response_model=DocumentDetail, status_code=202)
def reprocess_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    """Queue the stored file for extraction again."""
    doc = _get_or_404(db, document_id)
    status = as_value(doc.status)
    if status in {DocumentStatus.pending.value, DocumentStatus.processing.value}:
        raise HTTPException(status_code=409, detail=f"Document is already {status}.")
    hint = as_value(doc.source_hint)
    doc.status = DocumentStatus.pending.value
    doc.stage = DocumentStage.queued.value
    doc.doc_type = hint if hint in {"invoice", "resume"} else None
    doc.detected_type = None
    doc.page_count = None
    doc.extraction_method = None
    doc.raw_text = None
    doc.structured = None
    doc.error_message = None
    doc.processed_at = None
    doc.updated_at = utcnow()
    db.commit()
    _enqueue(db, doc)
    db.refresh(doc)
    return _detail(doc)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: uuid.UUID, db: Session = Depends(get_db)):
    """Delete a document, its extracted data, and the stored file."""
    doc = _get_or_404(db, document_id)
    delete_stored_file(doc.id)
    db.delete(doc)
    db.commit()
    return Response(status_code=204)


def _enqueue(db: Session, doc: Document) -> None:
    try:
        result = process_document.delay(str(doc.id))
    except Exception as exc:
        logger.exception("failed to queue document %s", doc.id)
        doc.status = DocumentStatus.failed.value
        doc.stage = DocumentStage.failed.value
        doc.error_message = "Could not queue background processing."
        doc.processed_at = utcnow()
        doc.updated_at = doc.processed_at
        db.commit()
        raise HTTPException(status_code=503, detail="Could not queue background processing") from exc
    db.refresh(doc)
    doc.task_id = getattr(result, "id", None)
    db.commit()


def _get_or_404(db: Session, document_id: uuid.UUID) -> Document:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


def _summary(doc: Document, query: str = "") -> DocumentSummary:
    text = doc.raw_text or ""
    snippet = snippet_around(text, query) if query.strip() else text[:240]
    return DocumentSummary(
        id=doc.id,
        filename=doc.filename,
        content_type=doc.content_type,
        source_hint=as_value(doc.source_hint),
        doc_type=doc.doc_type,
        detected_type=doc.detected_type,
        status=as_value(doc.status),
        stage=as_value(doc.stage),
        file_size=doc.file_size,
        page_count=doc.page_count,
        extraction_method=doc.extraction_method,
        error_message=doc.error_message,
        task_id=doc.task_id,
        snippet=snippet,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
        processed_at=doc.processed_at,
    )


def _detail(doc: Document) -> DocumentDetail:
    summary = _summary(doc)
    return DocumentDetail(
        **summary.model_dump(),
        extracted_text=doc.raw_text,
        structured=doc.structured,
        text_characters=len(doc.raw_text or ""),
    )


def _export(doc: Document) -> DocumentExport:
    return DocumentExport(
        id=doc.id,
        filename=doc.filename,
        content_type=doc.content_type,
        source_hint=as_value(doc.source_hint),
        doc_type=doc.doc_type,
        detected_type=doc.detected_type,
        status=as_value(doc.status),
        stage=as_value(doc.stage),
        page_count=doc.page_count,
        extraction_method=doc.extraction_method,
        extracted_text=doc.raw_text,
        structured=doc.structured,
        error_message=doc.error_message,
        created_at=doc.created_at,
        processed_at=doc.processed_at,
    )


def _download_name(filename: str) -> str:
    stem = Path(filename).stem or "document"
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", stem)[:80] or "document"
    return f"{safe}.json"
