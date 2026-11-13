"""RI adapter — normalises Format A files into Requirement objects.

Format A covers:
  - Multi-sheet xlsx  (e.g. 087 Haggen RI, 027 Seattle Retail)
  - Single-sheet xlsx (e.g. 073 E-commerce xlsx)
  - Single-sheet CSV  (e.g. 073 E-commerce csv)

Columns (all formats):
  0  Requirement Number  — unreliable; ignored for ID generation
  1  Contract Reference  — clause citation; may embed sheet-level LA codes in header
  2  Requirement Description — description body; LA scope embedded as free text
  3  Contract Details    — supplemental detail
  4+ Questions/Comments, Notes, Gap, etc.

Section header rows have content in column 0 and nothing in column 2.
"""

import csv
import re
from pathlib import Path
from typing import Iterator

import openpyxl

from ric.models import Requirement
from ric.parsing.scope import parse_scope

# ---------------------------------------------------------------------------
# Sheet names that contain metadata, not requirements
# ---------------------------------------------------------------------------
_METADATA_SHEETS = re.compile(
    r"""(?ix)
    ^(
        title(\s+info)?
        | contracts?
        | change\s+history
        | template\s+change\s+history
        | contract\s+listing
        | legend
        | lists?
        | instructions?
        | timecodes?
        | hour\s*types?
        | erncd
        | hnw\s*(checklist)?
        | holwksht
        | job\s*codes?
        | job\s*groups?
        | sheet\s*\d*
        | psinfo
        | dc\s+onsite\s+agenda
        | dc\s+(union|non.?union)\s+-\s+master.*
        | dc\s+qa
        | req\s+type\s+numbering
        | process\s+flow
        | old(\s*[\-_].+)?
    )$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# LA code: 4 digits + 2 uppercase letters
_LA_CODE_RE = re.compile(r"[0-9]{4}[A-Z]{2}")

# Hour-type tokens: 2–10 uppercase alphanumeric chars, sometimes with hyphens
# Preceded by keywords like "Hour type:", "Timecode:", "Time Code:"
_HOUR_TYPE_RE = re.compile(
    r"(?:Hour\s*[Tt]ype[s]?|[Tt]ime\s*[Cc]ode[s]?)\s*[:=]?\s*([A-Z][A-Z0-9-]{1,9})",
    re.IGNORECASE,
)
# Also catch bare timecodes from patterns like "7th Day = OT7"
_BARE_HOUR_TYPE_RE = re.compile(r"\b([A-Z]{2,}[A-Z0-9]{0,8})\b")

# Earn codes: purely numeric, 3 chars, after "Earn code(s):"
_EARN_CODE_RE = re.compile(
    r"(?:Earn\s+[Cc]ode[s]?)\s*[:=]?\s*([0-9]{3}(?:\s*/\s*[0-9]{3})?)",
)


# ---------------------------------------------------------------------------
# Paygroup inference
# ---------------------------------------------------------------------------

def _infer_paygroup(path: Path) -> str:
    """Extract a three-digit paygroup from filename, then from folder path."""
    # Try filename first
    m = re.search(r"\b(\d{3}[A-Za-z]?)\b", path.stem)
    if m:
        return m.group(1).upper()
    # Try parent folder names (walk up, look for "Paygroup NNN" or bare NNN)
    for part in reversed(path.parts):
        m = re.search(r"(?i)paygroup[s]?\s+(\d{3}[A-Za-z]?)", part)
        if m:
            return m.group(1).upper()
        m = re.search(r"^(\d{3}[A-Za-z]?)(?:\W|$)", part)
        if m:
            return m.group(1).upper()
    # Fall back to a sanitized filename stem (no paygroup found)
    slug = re.sub(r"[^A-Z0-9]+", "_", path.stem.upper()).strip("_")
    return slug[:24]


# ---------------------------------------------------------------------------
# Section slug
# ---------------------------------------------------------------------------

def _slugify(text: str) -> str:
    text = text.upper().strip()
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


# ---------------------------------------------------------------------------
# Sheet-level LA codes (embedded in the column-2 header of Format A xlsx)
# ---------------------------------------------------------------------------

def _extract_sheet_las(header_row: tuple) -> list[str]:
    """Return LA codes found in the Contract Reference column header."""
    raw = str(header_row[1] or "") if len(header_row) > 1 else ""
    return _LA_CODE_RE.findall(raw)


# ---------------------------------------------------------------------------
# Row classification helpers
# ---------------------------------------------------------------------------

def _cell(row: tuple, idx: int) -> str:
    val = row[idx] if idx < len(row) else None
    return str(val).strip() if val is not None else ""


def _is_section_header(row: tuple) -> bool:
    """Column 0 has content; column 2 (description) is empty."""
    return bool(_cell(row, 0)) and not _cell(row, 2)


def _is_blank_row(row: tuple) -> bool:
    return not any(str(c).strip() for c in row if c is not None)


# ---------------------------------------------------------------------------
# Config metadata extraction
# ---------------------------------------------------------------------------

def _extract_hour_types(text: str) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for m in _HOUR_TYPE_RE.finditer(text):
        code = m.group(1).upper()
        if code not in seen:
            seen.add(code)
            results.append(code)
    return results


def _extract_earn_codes(text: str) -> list[str]:
    seen: set[str] = set()
    results: list[str] = []
    for m in _EARN_CODE_RE.finditer(text):
        # "101/171 adj." — split on /
        for code in re.split(r"\s*/\s*", m.group(1)):
            code = code.strip()
            if code and code not in seen:
                seen.add(code)
                results.append(code)
    return results


# ---------------------------------------------------------------------------
# Row → Requirement
# ---------------------------------------------------------------------------

def _row_to_requirement(
    row: tuple,
    *,
    section: str,
    section_counters: dict[str, int],
    paygroup: str,
    sheet_name: str,
    sheet_las: list[str],
) -> Requirement | None:
    if _is_blank_row(row) or _is_section_header(row):
        return None

    description = _cell(row, 2)
    if not description:
        return None

    contract_ref = _cell(row, 1) or None

    scope_type, la_codes = parse_scope(description)

    section_slug = _slugify(section) if section else "UNKNOWN"
    n = section_counters.get(section_slug, 0) + 1
    section_counters[section_slug] = n

    return Requirement(
        id=f"RI-{paygroup}-{section_slug}-{n:03d}",
        source="RI",
        paygroup=paygroup,
        section=section,
        contract_reference=contract_ref,
        description=description,
        scope_type=scope_type,
        labor_agreements=la_codes,
        hour_types=_extract_hour_types(description),
        earn_codes=_extract_earn_codes(description),
        extra={
            "sheet_name": sheet_name,
            "sheet_labor_agreements": sheet_las,
        },
    )


# ---------------------------------------------------------------------------
# Sheet iterator (shared by xlsx and csv paths)
# ---------------------------------------------------------------------------

def _iter_sheet(
    rows: list[tuple],
    *,
    paygroup: str,
    sheet_name: str,
    sheet_las: list[str],
    skip_header: bool = True,
    section_counters: dict[str, int] | None = None,
) -> Iterator[Requirement]:
    section = ""
    if section_counters is None:
        section_counters = {}

    for i, row in enumerate(rows):
        if skip_header and i == 0:
            continue
        if _is_blank_row(row):
            continue
        if _is_section_header(row):
            section = _cell(row, 0)
            continue
        req = _row_to_requirement(
            row,
            section=section,
            section_counters=section_counters,
            paygroup=paygroup,
            sheet_name=sheet_name,
            sheet_las=sheet_las,
        )
        if req is not None:
            yield req


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def load_ri(path: str | Path, *, paygroup: str | None = None) -> list[Requirement]:
    """Load a Format A RI file (xlsx or csv) and return Requirement objects."""
    path = Path(path)
    pg = paygroup or _infer_paygroup(path)

    if path.suffix.lower() == ".csv":
        return list(_load_csv(path, paygroup=pg))
    return list(_load_xlsx(path, paygroup=pg))


def _load_csv(path: Path, *, paygroup: str) -> Iterator[Requirement]:
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(path, newline="", encoding=encoding) as f:
                rows = [tuple(r) for r in csv.reader(f)]
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError(f"Cannot decode {path} with any known encoding")

    yield from _iter_sheet(
        rows,
        paygroup=paygroup,
        sheet_name=path.stem,
        sheet_las=[],  # CSV: scope fully in description text
        skip_header=True,
    )


def _load_xlsx(path: Path, *, paygroup: str) -> list[Requirement]:
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        data_sheets = [
            name for name in wb.sheetnames
            if not _METADATA_SHEETS.match(name.strip())
        ]

        # Shared across all sheets so section counters (and thus IDs) are globally unique
        section_counters: dict[str, int] = {}
        results: list[Requirement] = []

        for sheet_name in data_sheets:
            ws = wb[sheet_name]
            rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
            if not rows:
                continue

            sheet_las = _extract_sheet_las(rows[0])

            results.extend(_iter_sheet(
                rows,
                paygroup=paygroup,
                sheet_name=sheet_name,
                sheet_las=sheet_las,
                skip_header=True,
                section_counters=section_counters,
            ))
    finally:
        wb.close()

    return results