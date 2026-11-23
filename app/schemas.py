import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class DocumentStatusView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    stage: str
    doc_type: str | None
    error_message: str | None
    processed_at: datetime | None


class DocumentSummary(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    source_hint: str
    doc_type: str | None
    detected_type: str | None
    status: str
    stage: str
    file_size: int
    page_count: int | None
    extraction_method: str | None
    error_message: str | None
    task_id: str | None
    snippet: str = ""
    created_at: datetime
    updated_at: datetime
    processed_at: datetime | None


class DocumentDetail(DocumentSummary):
    extracted_text: str | None = None
    structured: dict | None = None
    text_characters: int = 0


class DocumentList(BaseModel):
    items: list[DocumentSummary]
    total: int
    limit: int
    offset: int


class DocumentExport(BaseModel):
    id: uuid.UUID
    filename: str
    content_type: str
    source_hint: str
    doc_type: str | None
    detected_type: str | None
    status: str
    stage: str
    page_count: int | None
    extraction_method: str | None
    extracted_text: str | None
    structured: dict | None
    error_message: str | None
    created_at: datetime
    processed_at: datetime | None


class SearchHit(BaseModel):
    id: uuid.UUID
    filename: str
    doc_type: str | None
    status: str
    snippet: str
    created_at: datetime


class SearchResults(BaseModel):
    query: str
    items: list[SearchHit]
    total: int
    limit: int = Field(ge=1)
    offset: int = Field(ge=0)
