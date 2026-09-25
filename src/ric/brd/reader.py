from pathlib import Path

import docx


def extract_text(path: str | Path) -> str:
    """Extract all text from a BRD Word document, including table content."""
    path = Path(path)
    if path.suffix.lower() != ".docx":
        raise ValueError(f"Unsupported file type: {path.suffix!r} — only .docx is supported")
    return _from_docx(path)


def _from_docx(path: Path) -> str:
    doc = docx.Document(str(path))
    parts: list[str] = []

    # python-docx iterates body elements in order; we use the element tree to
    # preserve the interleaved paragraph / table sequence.
    for child in doc.element.body.iterchildren():
        tag = child.tag.split("}")[-1]

        if tag == "p":
            para = _para_from_element(child, doc)
            text = para.text.strip()
            if not text:
                continue
            style = para.style.name if para.style else ""
            if style.startswith("Heading"):
                lvl = style.replace("Heading", "").strip()
                prefix = "#" * int(lvl) if lvl.isdigit() else "##"
                parts.append(f"{prefix} {text}")
            else:
                parts.append(text)

        elif tag == "tbl":
            tbl = _table_from_element(child, doc)
            rows_text = _render_table(tbl)
            if rows_text:
                parts.append(rows_text)

    return "\n\n".join(parts)


def _para_from_element(el, doc):
    from docx.text.paragraph import Paragraph
    return Paragraph(el, doc)


def _table_from_element(el, doc):
    from docx.table import Table
    return Table(el, doc)


def _render_table(table) -> str:
    rows = []
    for row in table.rows:
        cells = []
        seen: set[int] = set()
        for i, cell in enumerate(row.cells):
            # Skip duplicate cells caused by merged cell references
            cell_id = id(cell._tc)
            if cell_id in seen:
                continue
            seen.add(cell_id)
            cells.append(cell.text.strip().replace("\n", " "))
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows)
