# DockIntel API

Document processing and extraction platform. Upload a PDF or an image, and DockIntel extracts the text, pulls structured fields from invoices and resumes, tracks processing status, and makes the result searchable and downloadable as JSON.

https://github.com/sKumari-01/dockintel-api

## What it does

- Accepts PDF and image uploads (`png`, `jpeg`, `tiff`, `bmp`, `webp`)
- Processes each file in the background with Celery
- Reads digital PDF text with PyMuPDF, and uses Tesseract OCR for images and scanned pages
- Turns invoices and resumes into structured JSON
- Tracks status from `queued` through `extracting`, `parsing`, `indexing`, and `done`
- Searches extracted text
- Downloads the full result as a JSON file

Structured extraction is heuristic. It looks for labels, section headers, dates, and amounts. It does not call a language model. Fields it cannot find are `null` and are left out of `fields_found`.

## Architecture

```mermaid
flowchart LR
  Client --> API[FastAPI]
  API --> PG[(PostgreSQL)]
  API --> Redis
  API --> Disk[File storage]
  Redis --> Worker[Celery worker]
  Worker --> Disk
  Worker --> PG
  Worker --> Extract[PyMuPDF and Tesseract]
```

The API stores the file, writes a `pending` row, and enqueues `documents.process`. The worker extracts text, chooses a parser, saves the structured payload, and marks the row `completed` or `failed`. The API and the worker share the same storage directory.

## Stack

FastAPI, PostgreSQL, Redis, Celery, PyMuPDF, Tesseract OCR, SQLAlchemy, Alembic.

## Quick start

Docker Compose starts PostgreSQL, Redis, the API, and the Celery worker. The API container runs migrations before it serves traffic.

```bash
docker compose up --build
```

The API is at http://localhost:8000 and the interactive docs are at http://localhost:8000/docs.

Upload an invoice:

```bash
curl -s -F "file=@invoice.pdf" -F "doc_type=invoice" \
  http://localhost:8000/api/v1/documents
```

The response is `202` with an `id`. Poll until `status` is `completed`:

```bash
curl -s http://localhost:8000/api/v1/documents/<id>/status
```

Download the JSON result:

```bash
curl -s -OJ http://localhost:8000/api/v1/documents/<id>/json
```

Search extracted text:

```bash
curl -s "http://localhost:8000/api/v1/search?q=INV-2026-0142"
```

## Local development

Install Tesseract so image and scanned-PDF jobs can run, then install Python dependencies. PostgreSQL and Redis still need to be running unless you only execute the test suite.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload
```

In another shell, start the worker with the same environment:

```bash
source .venv/bin/activate
celery -A app.celery_app.celery worker --loglevel=info
```

The API and the worker must use the same `STORAGE_DIR`. In Compose that directory is the `document_storage` volume mounted at `/app/storage`.

## API

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Process is up |
| `GET` | `/ready` | Database and Redis are reachable |
| `POST` | `/api/v1/documents` | Upload a file. Form fields: `file`, `doc_type` (`auto`, `invoice`, or `resume`) |
| `GET` | `/api/v1/documents` | List documents. Filters: `q`, `status`, `doc_type`, `limit`, `offset` |
| `GET` | `/api/v1/documents/{id}` | Metadata, extracted text, and structured fields |
| `GET` | `/api/v1/documents/{id}/status` | Status poll |
| `GET` | `/api/v1/documents/{id}/json` | Download the result JSON |
| `POST` | `/api/v1/documents/{id}/reprocess` | Run extraction again |
| `DELETE` | `/api/v1/documents/{id}` | Delete the row and the stored file |
| `GET` | `/api/v1/search?q=` | Search extracted text |

Upload limits are 20 MB by default. The extension and the file signature both have to match. The stored name is the base filename, so a path in the uploaded name cannot escape the storage directory.

`doc_type=auto` classifies the text after extraction. `invoice` or `resume` forces that parser. `detected_type` still records the classifier's guess.

JSON download returns `409` while the document is `pending` or `processing`. A `failed` document can still be downloaded so the error is visible.

### Status

| status | stage | Meaning |
| --- | --- | --- |
| `pending` | `queued` | Accepted, waiting for a worker |
| `processing` | `extracting` | Reading the PDF text layer or running OCR |
| `processing` | `parsing` | Building the structured payload |
| `processing` | `indexing` | Saving text so it can be searched |
| `completed` | `done` | Result is ready |
| `failed` | `failed` | `error_message` explains the failure |

### Invoice JSON

Money values are decimal strings. Dates that match a known format are normalized to `YYYY-MM-DD`.

```json
{
  "kind": "invoice",
  "vendor_name": "ACME SUPPLIES INC",
  "invoice_number": "INV-2026-0142",
  "invoice_date": "2026-03-01",
  "due_date": "2026-03-31",
  "currency": null,
  "bill_to": "Northwind Labs\n88 Harbor Ave",
  "line_items": [
    {"description": "Widget A", "quantity": 2, "unit_price": "25.00", "amount": "50.00"}
  ],
  "subtotal": "65.50",
  "tax": "5.24",
  "total": "70.74",
  "fields_found": ["vendor_name", "invoice_number", "total"]
}
```

### Resume JSON

```json
{
  "kind": "resume",
  "name": "Jane Doe",
  "email": "jane.doe@example.com",
  "phone": "(512) 555-0199",
  "location": "Austin, TX",
  "summary": "Backend engineer focused on data platforms.",
  "skills": ["Python", "FastAPI", "PostgreSQL", "Redis"],
  "experience": [
    {
      "title": "Software Engineer",
      "company": "Contoso",
      "dates": "Jan 2022 - Present",
      "description": "Built document pipelines."
    }
  ],
  "education": [
    {"degree": "B.S. Computer Science", "institution": "State University", "dates": "2018 - 2022"}
  ],
  "links": ["https://github.com/janedoe"],
  "fields_found": ["name", "email", "skills"]
}
```

Text that does not look like an invoice or a resume is stored as `kind: "generic"`.

## Search

PostgreSQL searches with English full-text (`to_tsvector` / `plainto_tsquery`) and a substring match. The substring match is what makes invoice numbers and email addresses reliable. A GIN index on the full-text expression is created by the migration. The list endpoint accepts the same `q` parameter.

## Configuration

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://dockintel:dockintel@localhost:5432/dockintel` | SQLAlchemy URL |
| `REDIS_URL` | `redis://localhost:6379/0` | Celery broker and result backend |
| `STORAGE_DIR` | `storage` | Where uploaded files are written |
| `MAX_UPLOAD_BYTES` | `20971520` | Upload limit |
| `CELERY_EAGER` | `false` | Run tasks in-process. The test suite turns this on |

## Tests

```bash
pytest
```

The tests use SQLite and Celery's eager mode, so PostgreSQL and Redis are not required. OCR calls are stubbed except where a digital PDF can be read from its text layer. A machine that runs image jobs outside the tests needs the `tesseract` binary on `PATH`.

## Project layout

```text
app/
  main.py                 FastAPI app
  api/routes/             Upload, status, search, health
  services/extraction.py  PyMuPDF and Tesseract
  services/parsing.py     Invoice and resume parsers
  tasks.py                Celery task
alembic/                  PostgreSQL schema
docker-compose.yml        API, worker, PostgreSQL, Redis
tests/                    Parser, extraction, and API tests
```

## Limitations

- Version 0.1 has no authentication. Put it behind a gateway before exposing it.
- Parsers expect reasonably labeled invoices and sectioned resumes. Unusual layouts return fewer `fields_found` entries instead of guessing.
- US month/day/year numeric dates are assumed when a date is not already ISO.
- Files live on the local disk shared by the API and the worker, not in object storage.
- A PDF page is sent to OCR when its text layer has fewer than 20 alphanumeric characters.
