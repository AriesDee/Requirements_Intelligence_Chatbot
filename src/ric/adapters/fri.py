"""FRI adapter — normalises Format C (FRI Standard Template) xlsx files into Requirement objects.

Each FRI file covers one People Group (the LA population for this contract).
Unlike the RI, scope is NOT embedded in description text — Include/Exclude columns
filter sub-populations within the People Group (job classes, hire-date cohorts),
not labor agreements. So scope_type is always "all" from the LA perspective, and
the People Group is stored in extra["people_group"] for routing by the engine.

Column positions are detected dynamically from the header row so the adapter
works regardless of hidden/extra columns across different FRI file versions.
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

# Earn codes: 2-3 digits optionally followed by one letter (e.g. 099, 34B, 65A)
_EARN_CODE_RE = re.compile(r"\b([0-9]{2,3}[A-Za-z]?)\b")

# Hour type tokens (2-10 alphanumeric + hyphen characters)
_HOUR_TOKEN_RE = re.compile(r"\b([A-Z][A-Z0-9-]{1,9})\b")


def _infer_paygroup(path: Path) -> str:
    m = re.search(r"\b(\d{3}[A-Za-z]?)\b", path.stem)
    if m:
        return m.group(1).upper()
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


def _slugify(text: str) -> str:
    text = text.upper().strip()
    text = re.sub(r"[^A-Z0-9]+", "_", text)
    return text.strip("_")


def _cell(row: tuple, idx: int) -> str:
    val = row[idx] if idx < len(row) else None
    return str(val).strip() if val is not None else ""


def _is_blank_row(row: tuple) -> bool:
    return not any(str(c).strip() for c in row if c is not None)


# Maps logical field name → candidate header strings (lowercase, checked in order)
_COL_ALIASES: dict[str, list[str]] = {
    "banner":             ["banner"],
    "people_group":       ["people group"],
    "employee_type":      ["employee type"],
    "default_hours":      ["default hours"],
    "category":           ["requirements category", "requirement category"],
    "section":            ["requirements type", "requirement type"],
    "description":        ["requirements", "requirement"],
    "include":            ["include"],
    "exclude":            ["exclude"],
    "enhancement":        ["enhancement"],
    "hour_types":         ["hour type/timecode", "hour type", "timecode", "hour types"],
    "earn_codes":         ["earn codes", "earn code"],
    "adj_earn_codes":     ["adj. earn codes", "adj earn codes", "adj. earn code"],
    "timecode_list":      ["timecode list"],
    "contract_reference": ["cba/past practice", "cba", "past practice"],
    "notes":              ["notes"],
    "element_name":       ["element name"],
}


def _build_col_map(header_row: tuple) -> dict[str, int]:
    """Return {field_name: column_index} by matching header cells to known aliases."""
    raw = {str(cell).strip().lower(): i for i, cell in enumerate(header_row) if cell is not None}
    col_map: dict[str, int] = {}
    for field, aliases in _COL_ALIASES.items():
        for alias in aliases:
            if alias in raw:
                col_map[field] = raw[alias]
                break
    return col_map


def _find_header_row(rows: list[tuple], max_scan: int = 5) -> int:
    """Return the index of the first row that looks like a header (≥3 known column names).

    Some FRI files have junk/notes rows before the real header. Scanning the first
    few rows and picking the one with the most alias matches handles this robustly.
    """
    all_aliases = {alias for aliases in _COL_ALIASES.values() for alias in aliases}
    best_idx, best_score = 0, 0
    for i, row in enumerate(rows[:max_scan]):
        cells = {str(c).strip().lower() for c in row if c is not None}
        score = len(cells & all_aliases)
        if score > best_score:
            best_score, best_idx = score, i
    return best_idx


def _col(row: tuple, col_map: dict[str, int], field: str) -> str:
    idx = col_map.get(field)
    if idx is None:
        return ""
    return _cell(row, idx)


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
    col_map: dict[str, int],
    section_counters: dict[str, int],
    paygroup: str,
    sheet_name: str,
) -> Requirement | None:
    if _is_blank_row(row):
        return None

    def c(field: str) -> str:
        return _col(row, col_map, field)

    description = c("description")
    if not description:
        return None

    section = c("section")
    section_slug = _slugify(section) if section else "UNKNOWN"
    n = section_counters.get(section_slug, 0) + 1
    section_counters[section_slug] = n

    extra: dict = {
        "sheet_name": sheet_name,
        "banner":        c("banner"),
        "people_group":  c("people_group"),
        "employee_type": c("employee_type"),
        "default_hours": c("default_hours"),
        "enhancement":   c("enhancement"),
        "include":       c("include"),
        "exclude":       c("exclude"),
        "timecode_list": c("timecode_list"),
        "notes":         c("notes"),
        "element_name":  c("element_name"),
    }
    extra = {k: v for k, v in extra.items() if v}

    return Requirement(
        id=f"FRI-{paygroup}-{section_slug}-{n:03d}",
        source="FRI",
        paygroup=paygroup,
        section=section,
        category=c("category") or None,
        contract_reference=c("contract_reference") or None,
        description=description,
        scope_type="all",
        labor_agreements=[],
        hour_types=_parse_hour_types(c("hour_types")),
        earn_codes=_parse_earn_codes(c("earn_codes")),
        adj_earn_codes=_parse_earn_codes(c("adj_earn_codes")),
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
    if not rows:
        return
    header_idx = _find_header_row(rows)
    col_map = _build_col_map(rows[header_idx])
    for row in rows[header_idx + 1:]:
        if _is_blank_row(row):
            continue
        req = _row_to_requirement(
            row,
            col_map=col_map,
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
    try:
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
    finally:
        wb.close()

    return results