from pathlib import Path

import pdfplumber


def extract_text(path: str | Path) -> str:
    """Extract all text from an IOC document, joining pages with blank lines."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _from_pdf(path)
    raise ValueError(f"Unsupported file type: {suffix!r} — only PDF is supported")


def _from_pdf(path: Path) -> str:
    pages: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = (page.extract_text() or "").strip()
            if text:
                pages.append(text)
    return "\n\n".join(pages)
