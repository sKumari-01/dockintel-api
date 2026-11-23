from pathlib import Path

import fitz
import pytest

from app.services.extraction import ExtractionError, extract_file
from tests.pdfutil import write_pdf
from tests.samples import INVOICE_TEXT


def test_text_pdf_uses_the_text_layer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "invoice.pdf"
    write_pdf(path, INVOICE_TEXT)

    def fail_ocr(image):
        raise AssertionError("OCR should not run when the PDF has a text layer")

    monkeypatch.setattr("app.services.extraction.pytesseract.image_to_string", fail_ocr)
    result = extract_file(path, "application/pdf")

    assert result.method == "text-layer"
    assert result.page_count == 1
    assert "INV-2026-0142" in result.text
    assert "Northwind Labs" in result.text


def test_scanned_pdf_falls_back_to_ocr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    path = tmp_path / "scan.pdf"
    document = fitz.open()
    document.new_page()
    document.save(path)
    document.close()
    monkeypatch.setattr(
        "app.services.extraction.pytesseract.image_to_string",
        lambda image: "INVOICE\nInvoice Number: INV-9\nTotal: 10.00\n",
    )

    result = extract_file(path, "application/pdf")

    assert result.method == "ocr"
    assert "INV-9" in result.text


def test_image_uses_ocr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from PIL import Image

    path = tmp_path / "page.png"
    Image.new("RGB", (80, 40), "white").save(path)
    monkeypatch.setattr(
        "app.services.extraction.pytesseract.image_to_string",
        lambda image: "Jane Doe\njane.doe@example.com\n",
    )

    result = extract_file(path, "image/png")

    assert result.method == "ocr"
    assert result.page_count == 1
    assert "Jane Doe" in result.text


def test_corrupt_pdf_raises_extraction_error(tmp_path: Path):
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nthis is not a real pdf")
    with pytest.raises(ExtractionError, match="Could not read the PDF"):
        extract_file(path, "application/pdf")
