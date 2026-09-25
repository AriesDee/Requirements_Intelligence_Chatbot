"""Parse LA scope declarations embedded in RI requirement description text.

The RI embeds scope in free text rather than a dedicated column.  Ten distinct
surface forms exist in the corpus; all are handled here with two regex families
(exclude-prefix and LA-keyword) plus an "All" sentinel.

Returns (scope_type, labor_agreement_codes).  Defaults to ("all", []) when no
scope declaration is found — the safe over-inclusive choice for the analysis engine.
"""

import re

from ric.models import ScopeType

# Six-character LA code: four digits then two uppercase letters (e.g. 1402OR).
_LA_CODE = r"[0-9]{4}[A-Z]{2}"
_LA_LIST = rf"{_LA_CODE}(?:\s*,\s*{_LA_CODE})*"

# --- compiled patterns, checked in priority order --------------------------------

# "Exclude[:]? Labor Agreement[(s)]? : <codes>"
_EXCLUDE_PREFIX = re.compile(
    rf"Exclude\s*:?\s*Labor\s+Agreement\s*\(?s?\)?\s*:\s*({_LA_LIST})",
    re.IGNORECASE,
)

# "Labor Agreement[(s)]? [:]? Exclude[:]? <codes>"
_INLINE_EXCLUDE = re.compile(
    rf"Labor\s+Agreement\s*\(?s?\)?\s*:?\s*Exclude\s*:?\s*({_LA_LIST})",
    re.IGNORECASE,
)

# "Labor Agreement[(s)]? : All"
_ALL = re.compile(
    r"Labor\s+Agreement\s*\(?s?\)?\s*:\s*All\b",
    re.IGNORECASE,
)

# "Labor Agreement[(s)]? : <codes>"  (include list — checked last to avoid
# shadowing the exclude forms above)
_INCLUDE = re.compile(
    rf"Labor\s+Agreement\s*\(?s?\)?\s*:\s*({_LA_LIST})",
    re.IGNORECASE,
)


def parse_scope(description: str) -> tuple[ScopeType, list[str]]:
    """Extract (scope_type, la_codes) from an RI requirement description."""
    for line in description.splitlines():
        line = line.strip()
        if not line:
            continue

        m = _EXCLUDE_PREFIX.search(line)
        if m:
            codes = re.findall(_LA_CODE, m.group(1))
            if codes:
                return "exclude", codes

        m = _INLINE_EXCLUDE.search(line)
        if m:
            codes = re.findall(_LA_CODE, m.group(1))
            if codes:
                return "exclude", codes

        if _ALL.search(line):
            return "all", []

        m = _INCLUDE.search(line)
        if m:
            codes = re.findall(_LA_CODE, m.group(1))
            if codes:
                return "include", codes

    return "all", []