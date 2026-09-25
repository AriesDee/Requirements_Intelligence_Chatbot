"""Inventory chat context builder — wraps existing ask() for Q&A over RI/FRI."""
from collections import defaultdict

from ric.models import Requirement


def build_inventory_context(requirements: list[Requirement]) -> str:
    """Serialize requirements into a text block for the Gemini chat system prompt."""
    # Group by source → paygroup → section
    tree: dict[str, dict[str, dict[str, list[Requirement]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )
    for r in requirements:
        tree[r.source][r.paygroup][r.section].append(r)

    lines = [
        "## REQUIREMENTS INVENTORY CONTEXT",
        f"Total requirements: {len(requirements)}",
        "",
    ]

    for source in sorted(tree):
        for paygroup in sorted(tree[source]):
            section_map = tree[source][paygroup]
            total_in_pg = sum(len(v) for v in section_map.values())
            lines.append(f"### {source} — Paygroup {paygroup} ({total_in_pg} requirements)")
            for section in sorted(section_map):
                reqs = section_map[section]
                lines.append(f"\n#### Section: {section} ({len(reqs)} requirements)")
                for r in reqs:
                    scope_str = r.scope_type
                    if r.labor_agreements:
                        scope_str += f" [{', '.join(r.labor_agreements)}]"
                    meta_parts = [f"scope={scope_str}"]
                    if r.earn_codes:
                        meta_parts.append(f"earn_codes={r.earn_codes}")
                    if r.hour_types:
                        meta_parts.append(f"hour_types={r.hour_types}")
                    if r.category:
                        meta_parts.append(f"category={r.category!r}")
                    lines.append(f"[{r.id}] {' | '.join(meta_parts)}")
                    lines.append(f"  {r.description.replace(chr(10), ' ')}")
            lines.append("")

    return "\n".join(lines)
