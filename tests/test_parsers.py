from app.services.parsing import detect_doc_type, parse_invoice, parse_resume, parse_structured
from tests.samples import GENERIC_TEXT, INVOICE_TEXT, RESUME_TEXT


def test_invoice_parser_extracts_header_totals_and_line_items():
    parsed = parse_invoice(INVOICE_TEXT)

    assert parsed["kind"] == "invoice"
    assert parsed["vendor_name"] == "ACME SUPPLIES INC"
    assert parsed["invoice_number"] == "INV-2026-0142"
    assert parsed["invoice_date"] == "2026-03-01"
    assert parsed["due_date"] == "2026-03-31"
    assert parsed["bill_to"] == "Northwind Labs\n88 Harbor Ave"
    assert parsed["subtotal"] == "65.50"
    assert parsed["tax"] == "5.24"
    assert parsed["total"] == "70.74"
    assert parsed["line_items"] == [
        {"description": "Widget A", "quantity": 2, "unit_price": "25.00", "amount": "50.00"},
        {"description": "Service fee", "quantity": 1, "unit_price": "15.50", "amount": "15.50"},
    ]
    assert "invoice_number" in parsed["fields_found"]
    assert "line_items" in parsed["fields_found"]


def test_invoice_normalizes_thousands_separator():
    parsed = parse_invoice("From: Globex\nInvoice Number: INV-1\nTotal: 1,250.00\n")
    assert parsed["vendor_name"] == "Globex"
    assert parsed["total"] == "1250.00"


def test_resume_parser_extracts_contact_history_and_skills():
    parsed = parse_resume(RESUME_TEXT)

    assert parsed["kind"] == "resume"
    assert parsed["name"] == "Jane Doe"
    assert parsed["email"] == "jane.doe@example.com"
    assert parsed["phone"] == "(512) 555-0199"
    assert parsed["location"] == "Austin, TX"
    assert "data platforms" in parsed["summary"]
    assert parsed["skills"] == ["Python", "FastAPI", "PostgreSQL", "Redis"]
    assert parsed["experience"] == [
        {
            "title": "Software Engineer",
            "company": "Contoso",
            "dates": "Jan 2022 - Present",
            "description": "Built document pipelines.",
        }
    ]
    assert parsed["education"] == [
        {
            "degree": "B.S. Computer Science",
            "institution": "State University",
            "dates": "2018 - 2022",
        }
    ]
    assert parsed["links"] == ["https://github.com/janedoe"]


def test_detects_invoice_resume_and_generic_text():
    assert detect_doc_type(INVOICE_TEXT) == "invoice"
    assert detect_doc_type(RESUME_TEXT) == "resume"
    assert detect_doc_type(GENERIC_TEXT) == "generic"
    assert parse_structured("generic", GENERIC_TEXT)["kind"] == "generic"
