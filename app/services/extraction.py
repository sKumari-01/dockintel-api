"""Turn uploaded PDFs and images into plain text."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz
import pytesseract
from PIL import Image

# A page with fewer alphanumeric characters than this is treated as scanned
# and sent through Tesseract. Short headers on an otherwise empty page still qualify.
MIN_PAGE_ALPHANUMERIC = 20
OCR_DPI = 200


class ExtractionError(Exception):
    """The file could not be read or OCR is unavailable."""


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    page_count: int
    method: str


def extract_file(path: Path, content_type: str) -> ExtractionResult:
    if content_type == "application/pdf" or path.suffix.lower() == ".pdf":
        return _extract_pdf(path)
    return _extract_image(path)


def _extract_pdf(path: Path) -> ExtractionResult:
    try:
        document = fitz.open(path)
    except Exception as exc:
        raise ExtractionError("Could not read the PDF") from exc

    page_text: list[str] = []
    methods: set[str] = set()
    try:
        for page in document:
            native = page.get_text("text") or ""
            if _has_enough_text(native):
                page_text.append(native)
                methods.add("text-layer")
                continue
            page_text.append(_ocr_pixmap(page))
            methods.add("ocr")
        page_count = document.page_count
    finally:
        document.close()

    if methods == {"text-layer"}:
        method = "text-layer"
    elif methods == {"ocr"}:
        method = "ocr"
    else:
        method = "mixed"
    return ExtractionResult(text=_clean_text("\n\n".join(page_text)), page_count=page_count, method=method)


def _extract_image(path: Path) -> ExtractionResult:
    try:
        image = Image.open(path)
        image.load()
    except Exception as exc:
        raise ExtractionError("Could not read the image") from exc
    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    text = _ocr_image(image)
    return ExtractionResult(text=_clean_text(text), page_count=1, method="ocr")


def _ocr_pixmap(page: fitz.Page) -> str:
    pixmap = page.get_pixmap(dpi=OCR_DPI, alpha=False)
    image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    return _ocr_image(image)


def _ocr_image(image: Image.Image) -> str:
    try:
        return pytesseract.image_to_string(image)
    except pytesseract.TesseractNotFoundError as exc:
        raise ExtractionError("Tesseract OCR is not installed or not on PATH") from exc


def _has_enough_text(text: str) -> bool:
    return sum(character.isalnum() for character in text) >= MIN_PAGE_ALPHANUMERIC


def _clean_text(text: str) -> str:
    text = text.replace("\x00", "")
    lines = [re.sub(r"[ \t]+", " ", line).rstrip() for line in text.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
