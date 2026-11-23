from pathlib import Path

import fitz


def write_pdf(path: Path, text: str) -> None:
    document = fitz.open()
    page = document.new_page()
    y = 72
    for line in text.splitlines():
        page.insert_text((72, y), line if line else " ", fontsize=11)
        y += 14
        if y > 760:
            page = document.new_page()
            y = 72
    document.save(path)
    document.close()
