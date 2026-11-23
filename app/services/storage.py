"""Validate uploads and store them outside the database."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from app.config import get_settings

ALLOWED_EXTENSIONS = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".bmp": "image/bmp",
    ".webp": "image/webp",
}


class UploadRejected(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def validate_upload(filename: str | None, data: bytes) -> tuple[str, str]:
    """Return the sanitized filename and the content type derived from the bytes."""
    if not filename or not filename.strip():
        raise UploadRejected("A filename is required")
    safe_name = Path(filename).name
    extension = Path(safe_name).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise UploadRejected("Unsupported file type. Upload a PDF or an image (png, jpeg, tiff, bmp, webp).")
    if not data:
        raise UploadRejected("The file is empty")
    limit = get_settings().max_upload_bytes
    if len(data) > limit:
        raise UploadRejected(f"File exceeds the {limit} byte upload limit", status_code=413)
    if not _matches_signature(extension, data):
        raise UploadRejected("File content does not match its extension")
    return safe_name[:512], ALLOWED_EXTENSIONS[extension]


def save_upload(document_id: uuid.UUID, filename: str, data: bytes) -> Path:
    extension = Path(filename).suffix.lower()
    destination_dir = storage_root() / str(document_id)
    destination_dir.mkdir(parents=True, exist_ok=True)
    path = destination_dir / f"original{extension}"
    path.write_bytes(data)
    return path


def delete_stored_file(document_id: uuid.UUID) -> None:
    directory = storage_root() / str(document_id)
    if directory.is_dir():
        shutil.rmtree(directory)


def resolve_storage_path(storage_path: str) -> Path:
    root = storage_root()
    path = Path(storage_path).resolve()
    if not path.is_relative_to(root):
        raise UploadRejected("Stored file path is outside the storage directory")
    return path


def storage_root() -> Path:
    root = Path(get_settings().storage_dir).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _matches_signature(extension: str, data: bytes) -> bool:
    if extension == ".pdf":
        return data.startswith(b"%PDF")
    if extension == ".png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if extension in {".jpg", ".jpeg"}:
        return data.startswith(b"\xff\xd8\xff")
    if extension == ".bmp":
        return data.startswith(b"BM")
    if extension in {".tif", ".tiff"}:
        return data.startswith((b"II*\x00", b"MM\x00*"))
    if extension == ".webp":
        return len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP"
    return False
