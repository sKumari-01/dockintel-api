"""Search extracted document text.

PostgreSQL uses English full-text search plus a substring match so invoice
numbers and email addresses still hit. Other databases, including the SQLite
test database, use a substring match only.
"""

from __future__ import annotations

import re

from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.models import Document


def escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def apply_text_search(statement, db: Session, query: str):
    cleaned = query.strip()
    if not cleaned:
        return statement
    escaped = escape_like(cleaned)
    substring = Document.raw_text.ilike(f"%{escaped}%", escape="\\")
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql" and re.search(r"[A-Za-z0-9]", cleaned):
        vector = func.to_tsvector("english", func.coalesce(Document.raw_text, ""))
        full_text = vector.op("@@")(func.plainto_tsquery("english", cleaned))
        return statement.where(or_(full_text, substring))
    return statement.where(substring)


def snippet_around(text: str | None, query: str, window: int = 240) -> str:
    if not text:
        return ""
    needle = query.strip().lower()
    if not needle:
        return text[:window]
    index = text.lower().find(needle)
    if index < 0:
        return text[:window]
    start = max(0, index - 40)
    return text[start : start + window]

