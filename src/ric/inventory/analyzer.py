"""Pure-Python statistics over a loaded requirements inventory. No LLM calls."""
from collections import Counter
from dataclasses import dataclass, field

from ric.models import Requirement


@dataclass
class InventoryStats:
    total: int
    by_source: dict[str, int]          # "FRI" / "RI" → count
    by_paygroup: dict[str, int]
    by_scope_type: dict[str, int]       # "all" / "include" / "exclude" → count
    by_section: dict[str, int]          # section name → count (sorted descending)
    by_la: dict[str, int]               # LA code → count of reqs that reference it
    by_people_group: dict[str, int]     # FRI People Group → count
    gaps: list[dict]                    # [{"ID", "Source", "Paygroup", "Section", "Issue"}]


def _people_group(r: Requirement) -> str:
    for key, val in r.extra.items():
        if "people" in key.lower() and val and str(val).strip():
            return str(val).strip()
    return ""


def analyze(requirements: list[Requirement]) -> InventoryStats:
    by_source = Counter(r.source for r in requirements)
    by_paygroup = Counter(r.paygroup for r in requirements)
    by_scope_type = Counter(r.scope_type for r in requirements)
    by_section: Counter = Counter()
    la_counter: Counter = Counter()
    pg_counter: Counter = Counter()

    for r in requirements:
        by_section[r.section] += 1
        for la in r.labor_agreements:
            la_counter[la] += 1
        pg = _people_group(r)
        if pg:
            pg_counter[pg] += 1

    gaps: list[dict] = []
    for r in requirements:
        issues = []
        if r.scope_type in ("include", "exclude") and not r.labor_agreements:
            issues.append(f"scope_type='{r.scope_type}' but no LA codes listed")
        if not r.description or len(r.description.strip()) < 20:
            issues.append("Description missing or too short")
        for issue in issues:
            gaps.append({
                "ID": r.id,
                "Source": r.source,
                "Paygroup": r.paygroup,
                "Section": r.section,
                "Issue": issue,
            })

    return InventoryStats(
        total=len(requirements),
        by_source=dict(by_source.most_common()),
        by_paygroup=dict(by_paygroup.most_common()),
        by_scope_type=dict(by_scope_type.most_common()),
        by_section=dict(by_section.most_common(25)),
        by_la=dict(la_counter.most_common(30)),
        by_people_group=dict(pg_counter.most_common(20)),
        gaps=gaps,
    )
