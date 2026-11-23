"""Heuristic parsers for invoices and resumes.

These extractors use labels, section headers, and regular patterns. They do
not call a language model. When a field is missing, the value is null and the
field name is omitted from ``fields_found``.
"""

from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

INVOICE_HINTS = (
    "invoice",
    "bill to",
    "subtotal",
    "amount due",
    "invoice number",
    "tax",
)
RESUME_HINTS = (
    "experience",
    "education",
    "skills",
    "summary",
    "curriculum vitae",
    "work history",
)

EMAIL_RE = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.I)
PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]\d{4}")
URL_RE = re.compile(r"https?://[^\s<>]+|(?:linkedin|github)\.com/[^\s<>]+", re.I)
MONEY_RE = re.compile(r"(\d{1,3}(?:,\d{3})*\.\d{2})")
ITEM_RE = re.compile(
    r"^(?P<desc>.+?)\s+"
    r"(?P<qty>\d+(?:\.\d+)?)\s+"
    r"\$?(?P<price>\d{1,3}(?:,\d{3})*\.\d{2})\s+"
    r"\$?(?P<amount>\d{1,3}(?:,\d{3})*\.\d{2})\s*$"
)
INVOICE_NUMBER_RE = re.compile(
    r"invoice\s*(?:number|no\.?|#)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-/]+)",
    re.I,
)
DATE_LINE_RE = re.compile(
    r"(?i)\b(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?|\d{4})\b.+\b(?:present|current|\d{4})\b"
)
DEGREE_RE = re.compile(
    r"\b(?:b\.?\s?s\.?|b\.?\s?a\.?|m\.?\s?s\.?|m\.?\s?a\.?|ph\.?\s?d\.?|"
    r"bachelor|master|associate|diploma)\b",
    re.I,
)
LOCATION_RE = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s*[A-Z]{2})\b")
SECTION_RE = re.compile(
    r"^(summary|professional summary|profile|experience|work experience|"
    r"professional experience|education|skills|technical skills|core skills|"
    r"projects|certifications)\s*:?\s*$",
    re.I,
)
SECTION_CANON = {
    "professional summary": "summary",
    "profile": "summary",
    "work experience": "experience",
    "professional experience": "experience",
    "technical skills": "skills",
    "core skills": "skills",
}


def detect_doc_type(text: str) -> str:
    lowered = text.lower()
    invoice_score = sum(1 for hint in INVOICE_HINTS if hint in lowered)
    resume_score = sum(1 for hint in RESUME_HINTS if hint in lowered)
    if invoice_score < 2 and resume_score < 2:
        return "generic"
    if invoice_score > resume_score:
        return "invoice"
    if resume_score > invoice_score:
        return "resume"
    return "generic"


def parse_structured(kind: str, text: str) -> dict:
    if kind == "invoice":
        return parse_invoice(text)
    if kind == "resume":
        return parse_resume(text)
    return {
        "kind": "generic",
        "fields_found": [],
        "note": "No invoice or resume structure detected.",
    }


def parse_invoice(text: str) -> dict:
    lines = [line.strip() for line in text.splitlines()]
    data = {
        "kind": "invoice",
        "vendor_name": _vendor_name(text, lines),
        "invoice_number": _first_group(INVOICE_NUMBER_RE, text),
        "invoice_date": _normalize_date(_labeled_line(text, r"invoice\s*date")),
        "due_date": _normalize_date(_labeled_line(text, r"due\s*date")),
        "currency": _currency(text),
        "bill_to": _bill_to(text),
        "line_items": _line_items(lines),
        "subtotal": _labeled_money(lines, ("subtotal", "sub-total")),
        "tax": _labeled_money(lines, ("tax", "vat", "sales tax")),
        "total": _labeled_money(lines, ("amount due", "balance due", "total")),
    }
    data["fields_found"] = _present(
        data,
        (
            "vendor_name",
            "invoice_number",
            "invoice_date",
            "due_date",
            "currency",
            "bill_to",
            "line_items",
            "subtotal",
            "tax",
            "total",
        ),
    )
    return data


def parse_resume(text: str) -> dict:
    sections = _sections(text)
    preamble = sections.get("_preamble", "")
    email = EMAIL_RE.search(text)
    phone = PHONE_RE.search(text)
    data = {
        "kind": "resume",
        "name": _person_name(preamble),
        "email": email.group(0) if email else None,
        "phone": phone.group(0) if phone else None,
        "location": _location(preamble),
        "summary": _clean_block(sections.get("summary")) or None,
        "skills": _skills(sections.get("skills", "")),
        "experience": _experience(sections.get("experience", "")),
        "education": _education(sections.get("education", "")),
        "links": _links(text),
    }
    data["fields_found"] = _present(
        data,
        (
            "name",
            "email",
            "phone",
            "location",
            "summary",
            "skills",
            "experience",
            "education",
            "links",
        ),
    )
    return data


def _present(data: dict, keys: tuple[str, ...]) -> list[str]:
    found = []
    for key in keys:
        value = data.get(key)
        if value:
            found.append(key)
    return found


def _first_group(pattern: re.Pattern[str], text: str) -> str | None:
    match = pattern.search(text)
    return match.group(1).strip() if match else None


def _vendor_name(text: str, lines: list[str]) -> str | None:
    labeled = re.search(r"(?im)^(?:from|vendor|seller)\s*:\s*(.+)$", text)
    if labeled:
        return labeled.group(1).strip() or None
    for line in lines:
        if not line:
            continue
        lowered = line.lower().rstrip(":")
        if lowered in {"invoice", "tax invoice", "bill", "receipt"}:
            continue
        if lowered.startswith(("invoice ", "bill to", "ship to")):
            break
        if re.search(r"[A-Za-z]", line):
            return line
    return None


def _labeled_line(text: str, label: str) -> str | None:
    match = re.search(rf"(?im)^[^\n]*\b(?:{label})\b\s*[:\-]?\s*(.+)$", text)
    if not match:
        return None
    value = match.group(1).strip()
    return value or None


def _normalize_date(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = value.strip().rstrip(".")
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    return cleaned


def _currency(text: str) -> str | None:
    if "$" in text or re.search(r"\bUSD\b", text):
        return "USD"
    if "€" in text or re.search(r"\bEUR\b", text):
        return "EUR"
    if "£" in text or re.search(r"\bGBP\b", text):
        return "GBP"
    if "₹" in text or re.search(r"\bINR\b", text):
        return "INR"
    return None


def _bill_to(text: str) -> str | None:
    match = re.search(
        r"(?is)bill(?:ed)?\s*to\s*:?\s*\n(?P<body>.+?)"
        r"(?:\n\s*\n|\n(?:description|item|qty|subtotal|invoice|ship\s*to)\b)",
        text,
    )
    if not match:
        return None
    body = _clean_block(match.group("body"))
    return body or None


def _line_items(lines: list[str]) -> list[dict]:
    items = []
    for line in lines:
        match = ITEM_RE.match(line.strip())
        if not match:
            continue
        description = re.sub(r"\s+", " ", match.group("desc")).strip(" -|")
        if not description or description.lower() in {"description", "item", "qty"}:
            continue
        items.append(
            {
                "description": description,
                "quantity": _quantity(match.group("qty")),
                "unit_price": _money(match.group("price")),
                "amount": _money(match.group("amount")),
            }
        )
    return items


def _labeled_money(lines: list[str], labels: tuple[str, ...]) -> str | None:
    label_re = re.compile(rf"^(?:{'|'.join(re.escape(label) for label in labels)})\b", re.I)
    for line in lines:
        stripped = line.strip()
        if not label_re.match(stripped):
            continue
        amounts = MONEY_RE.findall(stripped)
        if amounts:
            return _money(amounts[-1])
    return None


def _money(value: str) -> str:
    try:
        return f"{Decimal(value.replace(',', '')):.2f}"
    except InvalidOperation:
        return value


def _quantity(value: str) -> int | float:
    number = Decimal(value)
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def _sections(text: str) -> dict[str, str]:
    sections: dict[str, list[str]] = {"_preamble": []}
    current = "_preamble"
    for line in text.splitlines():
        header = SECTION_RE.match(line.strip())
        if header:
            name = header.group(1).lower()
            current = SECTION_CANON.get(name, name)
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return {key: "\n".join(value).strip() for key, value in sections.items()}


def _person_name(preamble: str) -> str | None:
    for line in preamble.splitlines():
        candidate = line.strip()
        if not candidate or "@" in candidate or any(ch.isdigit() for ch in candidate):
            continue
        words = re.findall(r"[A-Za-z][A-Za-z'.-]*", candidate)
        if 2 <= len(words) <= 4 and len(candidate) <= 80:
            return candidate
    return None


def _location(preamble: str) -> str | None:
    match = LOCATION_RE.search(preamble)
    return match.group(1) if match else None


def _skills(section: str) -> list[str]:
    if not section:
        return []
    pieces = re.split(r"[,|•·;\n]+", section)
    skills: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        skill = re.sub(r"\s+", " ", piece).strip(" -*\t")
        key = skill.lower()
        if len(skill) < 2 or key in seen:
            continue
        seen.add(key)
        skills.append(skill)
        if len(skills) == 50:
            break
    return skills


def _experience(section: str) -> list[dict]:
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    entries = []
    index = 0
    while index < len(lines):
        has_date = index + 1 < len(lines) and _is_date_line(lines[index + 1]) and not _is_date_line(lines[index])
        if not has_date:
            index += 1
            continue
        title, company = _split_role(lines[index])
        dates = lines[index + 1]
        index += 2
        description: list[str] = []
        while index < len(lines):
            next_is_role = (
                index + 1 < len(lines) and _is_date_line(lines[index + 1]) and not _is_date_line(lines[index])
            )
            if next_is_role:
                break
            description.append(lines[index].lstrip("-• ").strip())
            index += 1
        entries.append(
            {
                "title": title,
                "company": company,
                "dates": dates,
                "description": "\n".join(part for part in description if part) or None,
            }
        )
    return entries


def _education(section: str) -> list[dict]:
    lines = [line.strip() for line in section.splitlines() if line.strip()]
    entries = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if not DEGREE_RE.search(line):
            index += 1
            continue
        degree, institution = _split_role(line)
        dates = None
        if index + 1 < len(lines) and _is_date_line(lines[index + 1]):
            dates = lines[index + 1]
            index += 1
        entries.append({"degree": degree, "institution": institution, "dates": dates})
        index += 1
    return entries


def _split_role(line: str) -> tuple[str, str | None]:
    if "," not in line:
        return line.strip(), None
    left, right = line.split(",", 1)
    left = left.strip()
    right = right.strip() or None
    return left, right


def _is_date_line(line: str) -> bool:
    return DATE_LINE_RE.search(line) is not None


def _links(text: str) -> list[str]:
    found = []
    seen: set[str] = set()
    for match in URL_RE.findall(text):
        link = match.rstrip(".,);")
        key = link.lower()
        if key in seen:
            continue
        seen.add(key)
        found.append(link)
    return found


def _clean_block(value: str | None) -> str:
    if not value:
        return ""
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()]
    compact = "\n".join(line for line in lines if line)
    return re.sub(r"\n{3,}", "\n\n", compact).strip()
