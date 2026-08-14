"""FRI adapter — normalises Format C (FRI Standard Template) xlsx files into Requirement objects.

Each FRI file covers one People Group (the LA population for this contract).
Unlike the RI, scope is NOT embedded in description text — Include/Exclude columns
filter sub-populations within the People Group (job classes, hire-date cohorts),
not labor agreements. So scope_type is always "all" from the LA perspective, and
the People Group is stored in extra["people_group"] for routing by the engine.

Columns (0-indexed, row 0 is the header):
  0   Sequence #          — unreliable; ignored for ID generation
  1   Banner              → extra["banner"]
  2   People Group        → extra["people_group"]
  3   Employee Type       → extra["employee_type"]
  4   Default Hours       → extra["default_hours"]
  5   Requirements Category → category
  6   Requirements Type   → section (slug used in ID)
  7   Requirements        → description
  8   Include             → extra["include"] (job-class filter, not LA codes)
  9   Exclude             → extra["exclude"]
  10  Enhancement         → extra["enhancement"]
  11  Hour Type/Timecode  → hour_types
  12  Earn codes          → earn_codes
  13  Adj. Earn codes     → adj_earn_codes
  14  Timecode List       → extra["timecode_list"]
  15  CBA/Past Practice   → contract_reference
  16  Notes               → extra["notes"]
  17  Element name        → extra["element_name"] (optional column)
"""

import re
from pathlib import Path
from typing import Iterator

import openpyxl

from ric.models import Requirement

_METADATA_SHEETS = re.compile(
    r"""(?ix)
    ^(
        old
        | change\s+history
        | template\s+change\s+history
        | title(\s+info)?
        | contracts?
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
        | req\s+type\s+numbering
        | process\s+flow
    )$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# 3-digit earn code
_EARN_CODE_RE = re.compile(r"\b([0-9]{3})\b")

# Hour type tokens (2-10 alphanumeric + hyphen characters)
_HOUR_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9-]{1,9})\b")


def _infer_paygroup(path: Path) -> str:
    m = re.search(r"\b(\d{3})\b", path.stem)
    if m:
        return m.group(1)
    for part in reversed(path.parts):
        m = re.search(r"(?i)paygroup[s]?\s+(\d{3})", part)
        if m:
            return m.group(1)
        m = re.search(r"^(\d{3})(?:\D|$)", part)
        if m:
            return m.group(1)
    raise ValueError(
        f"Cannot infer paygroup from path: {path}\n"
        "Pass paygroup= explicitly to the adapter."
    )


def _slugify(text: str) -> str:
    text = text.upper().strip()
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def _cell(row: tuple, idx: int) -> str:
    val = row[idx] if idx < len(row) else None
    return str(val).strip() if val is not None else ""


def _is_blank_row(row: tuple) -> bool:
    return not any(str(c).strip() for c in row if c is not None)


def _parse_earn_codes(raw: str) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for m in _EARN_CODE_RE.finditer(raw):
        code = m.group(1)
        if code not in seen:
            seen.add(code)
            result.append(code)
    return result


def _parse_hour_types(raw: str) -> list[str]:
    """Split hour-type cell into individual tokens (newline/comma/semicolon delimited)."""
    if not raw:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for token in re.split(r"[\n,;]+", raw):
        token = token.strip()
        if token and token not in seen:
            seen.add(token)
            result.append(token)
    return result


def _row_to_requirement(
    row: tuple,
    *,
    section_counters: dict[str, int],
    paygroup: str,
    sheet_name: str,
) -> Requirement | None:
    if _is_blank_row(row):
        return None

    description = _cell(row, 7)
    if not description:
        return None

    section = _cell(row, 6)
    section_slug = _slugify(section) if section else "UNKNOWN"
    n = section_counters.get(section_slug, 0) + 1
    section_counters[section_slug] = n

    raw_hour = _cell(row, 11)
    raw_earn = _cell(row, 12)
    raw_adj = _cell(row, 13)

    extra: dict = {
        "sheet_name": sheet_name,
        "banner": _cell(row, 1),
        "people_group": _cell(row, 2),
        "employee_type": _cell(row, 3),
        "default_hours": _cell(row, 4),
        "enhancement": _cell(row, 10),
        "include": _cell(row, 8),
        "exclude": _cell(row, 9),
        "timecode_list": _cell(row, 14),
        "notes": _cell(row, 16) if len(row) > 16 else "",
        "element_name": _cell(row, 17) if len(row) > 17 else "",
    }
    extra = {k: v for k, v in extra.items() if v}

    return Requirement(
        id=f"FRI-{paygroup}-{section_slug}-{n:03d}",
        source="FRI",
        paygroup=paygroup,
        section=section,
        category=_cell(row, 5) or None,
        contract_reference=_cell(row, 15) or None,
        description=description,
        scope_type="all",
        labor_agreements=[],
        hour_types=_parse_hour_types(raw_hour),
        earn_codes=_parse_earn_codes(raw_earn),
        adj_earn_codes=_parse_earn_codes(raw_adj),
        extra=extra,
    )


def _iter_sheet(
    rows: list[tuple],
    *,
    paygroup: str,
    sheet_name: str,
    section_counters: dict[str, int] | None = None,
) -> Iterator[Requirement]:
    if section_counters is None:
        section_counters = {}
    for i, row in enumerate(rows):
        if i == 0:
            continue  # header row
        if _is_blank_row(row):
            continue
        req = _row_to_requirement(
            row,
            section_counters=section_counters,
            paygroup=paygroup,
            sheet_name=sheet_name,
        )
        if req is not None:
            yield req


def load_fri(path: str | Path, *, paygroup: str | None = None) -> list[Requirement]:
    """Load a Format C FRI xlsx and return Requirement objects."""
    path = Path(path)
    pg = paygroup or _infer_paygroup(path)

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)

    data_sheets = [
        name for name in wb.sheetnames
        if not _METADATA_SHEETS.match(name.strip())
    ]

    results: list[Requirement] = []
    for sheet_name in data_sheets:
        ws = wb[sheet_name]
        rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
        if not rows or not any(c is not None for c in rows[0]):
            continue
        results.extend(_iter_sheet(rows, paygroup=pg, sheet_name=sheet_name))

    return results