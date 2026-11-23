import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def as_value(value):
    """Return the stored value for enums and pass other values through."""
    if isinstance(value, enum.Enum):
        return value.value
    return value


class Base(DeclarativeBase):
    pass


class DocumentStatus(str, enum.Enum):
    pending = "pending"
    processing = "processing"
    completed = "completed"
    failed = "failed"


class DocumentStage(str, enum.Enum):
    queued = "queued"
    extracting = "extracting"
    parsing = "parsing"
    indexing = "indexing"
    done = "done"
    failed = "failed"


class SourceHint(str, enum.Enum):
    auto = "auto"
    invoice = "invoice"
    resume = "resume"


StructuredJSON = JSON().with_variant(JSONB(), "postgresql")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename: Mapped[str] = mapped_column(String(512), nullable=False)
    content_type: Mapped[str] = mapped_column(String(128), nullable=False)
    source_hint: Mapped[str] = mapped_column(String(32), nullable=False, default=SourceHint.auto.value)
    doc_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    detected_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default=DocumentStatus.pending.value, index=True)
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default=DocumentStage.queued.value)
    storage_path: Mapped[str] = mapped_column(String(1024), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    extraction_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    raw_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    structured: Mapped[dict | None] = mapped_column(StructuredJSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
