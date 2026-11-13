"""Tests for Stage 2: requirement matching.

Filter tests are deterministic (no API key needed).
Integration tests require ANTHROPIC_API_KEY.
"""
import os
from pathlib import Path

import pytest

from ric.ioc.models import ChangeType, IOCChange
from ric.matcher import ChangeMatch
from ric.matcher.filter import filter_by_la_scope
from ric.models import Requirement

SAMPLE_DIR = Path(__file__).parent.parent / "Sample Requirements Docs"
IOC_WA_PM = (
    SAMPLE_DIR
    / "IOC_1400WA1401PM Contract Renewal for GrocWorks Driver 313 WA.PM"
      " - Eff. 8.1.22 Ratified 8.24_STANDARDIZED-10.04.2024.pdf"
)
FRI_UNION = (
    SAMPLE_DIR
    / "Haggen FRIs - latest"
    / "Paygroup 087"
    / "Union"
    / "RTL Haggen UFCW King Grocery Clerks Local 3000.xlsx"
)

_api_key = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)
_ioc_exists = pytest.mark.skipif(not IOC_WA_PM.exists(), reason="WA/PM IOC sample not found")
_fri_exists = pytest.mark.skipif(not FRI_UNION.exists(), reason="FRI union sample not found")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_req(
    req_id: str,
    scope_type: str = "all",
    labor_agreements: list[str] | None = None,
    section: str = "WAGES",
    description: str = "Test requirement",
) -> Requirement:
    return Requirement(
        id=req_id,
        source="RI",
        paygroup="087",
        section=section,
        description=description,
        scope_type=scope_type,
        labor_agreements=labor_agreements or [],
    )


def make_change(
    labor_agreements: list[str] | None = None,
    change_type: ChangeType = ChangeType.WAGE_RATE,
    timekeeping_relevant: bool = True,
) -> IOCChange:
    return IOCChange(
        change_type=change_type,
        timekeeping_relevant=timekeeping_relevant,
        summary="Test change summary",
        source_text="The wage rate shall increase effective August 1.",
        labor_agreements=labor_agreements or [],
    )


# ---------------------------------------------------------------------------
# filter_by_la_scope — deterministic tests
# ---------------------------------------------------------------------------

class TestFilterByLAScope:
    def test_all_scope_always_passes(self):
        req = make_req("R1", scope_type="all")
        result = filter_by_la_scope([req], make_change(["1400WA"]), [])
        assert req in result

    def test_include_scope_matching_la(self):
        req = make_req("R1", scope_type="include", labor_agreements=["1400WA"])
        result = filter_by_la_scope([req], make_change(["1400WA"]), [])
        assert req in result

    def test_include_scope_no_match(self):
        req = make_req("R1", scope_type="include", labor_agreements=["9999ZZ"])
        result = filter_by_la_scope([req], make_change(["1400WA"]), [])
        assert req not in result

    def test_exclude_scope_la_not_excluded(self):
        req = make_req("R1", scope_type="exclude", labor_agreements=["9999ZZ"])
        result = filter_by_la_scope([req], make_change(["1400WA"]), [])
        assert req in result

    def test_exclude_scope_la_is_excluded(self):
        req = make_req("R1", scope_type="exclude", labor_agreements=["1400WA"])
        result = filter_by_la_scope([req], make_change(["1400WA"]), [])
        assert req not in result

    def test_falls_back_to_ioc_la_ids(self):
        req = make_req("R1", scope_type="include", labor_agreements=["1400WA"])
        change = make_change(labor_agreements=[])  # no change-level LAs
        result = filter_by_la_scope([req], change, ["1400WA"])
        assert req in result

    def test_fallback_ioc_la_excludes_correctly(self):
        req = make_req("R1", scope_type="include", labor_agreements=["9999ZZ"])
        change = make_change(labor_agreements=[])
        result = filter_by_la_scope([req], change, ["1400WA"])
        assert req not in result

    def test_returns_all_when_no_las_known(self):
        req = make_req("R1", scope_type="include", labor_agreements=["1400WA"])
        change = make_change(labor_agreements=[])
        result = filter_by_la_scope([req], change, [])
        assert req in result

    def test_empty_requirements_returns_empty(self):
        result = filter_by_la_scope([], make_change(["1400WA"]), [])
        assert result == []

    def test_mixed_scope_types(self):
        r_all = make_req("R1", scope_type="all")
        r_inc_yes = make_req("R2", scope_type="include", labor_agreements=["1400WA"])
        r_inc_no = make_req("R3", scope_type="include", labor_agreements=["9999ZZ"])
        r_exc_yes = make_req("R4", scope_type="exclude", labor_agreements=["9999ZZ"])
        r_exc_no = make_req("R5", scope_type="exclude", labor_agreements=["1400WA"])

        result = filter_by_la_scope(
            [r_all, r_inc_yes, r_inc_no, r_exc_yes, r_exc_no],
            make_change(["1400WA"]),
            [],
        )
        assert r_all in result
        assert r_inc_yes in result
        assert r_inc_no not in result
        assert r_exc_yes in result
        assert r_exc_no not in result

    def test_multiple_las_any_match_sufficient(self):
        # include req covers 1401PM; change affects both 1400WA and 1401PM
        req = make_req("R1", scope_type="include", labor_agreements=["1401PM"])
        result = filter_by_la_scope([req], make_change(["1400WA", "1401PM"]), [])
        assert req in result

    def test_preserves_order(self):
        reqs = [make_req(f"R{i}", scope_type="all") for i in range(5)]
        result = filter_by_la_scope(reqs, make_change(["1400WA"]), [])
        assert [r.id for r in result] == [r.id for r in reqs]


# ---------------------------------------------------------------------------
# match_changes — integration tests (API key required)
# ---------------------------------------------------------------------------

@_ioc_exists
@_fri_exists
@_api_key
class TestMatchChangesIntegration:
    @pytest.fixture(scope="class")
    def ioc(self):
        from ric.ioc.parser import parse_ioc
        return parse_ioc(IOC_WA_PM)

    @pytest.fixture(scope="class")
    def reqs(self):
        from ric.adapters.fri import load_fri
        return load_fri(FRI_UNION, paygroup="087")

    @pytest.fixture(scope="class")
    def results(self, ioc, reqs):
        from ric.matcher import match_changes
        return match_changes(ioc, reqs)

    def test_one_result_per_change(self, results, ioc):
        assert len(results) == len(ioc.changes)

    def test_all_results_are_change_matches(self, results):
        assert all(isinstance(r, ChangeMatch) for r in results)

    def test_at_least_one_change_has_matches(self, results):
        total = sum(len(r.matched_requirements) for r in results)
        assert total > 0

    def test_no_hallucinated_ids(self, results, reqs):
        valid_ids = {r.id for r in reqs}
        for cm in results:
            for m in cm.matched_requirements:
                assert m.requirement_id in valid_ids, (
                    f"Hallucinated ID: {m.requirement_id!r}"
                )

    def test_unmatched_changes_have_reason(self, results):
        for cm in results:
            if not cm.matched_requirements:
                assert cm.no_match_reason, (
                    f"Change with no matches missing no_match_reason: {cm.change.summary!r}"
                )

    def test_all_matches_have_rationale(self, results):
        for cm in results:
            for m in cm.matched_requirements:
                assert m.rationale.strip()

    def test_relevance_values_are_valid(self, results):
        for cm in results:
            for m in cm.matched_requirements:
                assert m.relevance in ("direct", "indirect")

    def test_timekeeping_changes_produce_matches(self, results, ioc):
        tk_changes = [
            (ioc.changes[i], results[i])
            for i in range(len(ioc.changes))
            if ioc.changes[i].timekeeping_relevant
        ]
        assert any(len(cm.matched_requirements) > 0 for _, cm in tk_changes), (
            "Expected at least one timekeeping-relevant change to match a requirement"
        )
