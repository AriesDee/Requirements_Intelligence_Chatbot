from ric.ioc.models import IOCChange
from ric.models import Requirement


def filter_by_la_scope(
    requirements: list[Requirement],
    change: IOCChange,
    ioc_la_ids: list[str],
) -> list[Requirement]:
    """Keep only requirements whose LA scope covers the change's affected LAs.

    When the change has no explicit labor_agreements, falls back to the IOC's
    full set of LA IDs. When neither source provides any LAs, returns all
    requirements unfiltered (can't narrow further).
    """
    las = set(change.labor_agreements) or set(ioc_la_ids)
    if not las:
        return list(requirements)
    return [r for r in requirements if r.applies_to(las)]
