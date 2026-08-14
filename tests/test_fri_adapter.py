"""Integration tests for the FRI adapter against sample files in the repo."""

from pathlib import Path

import pytest

from ric.adapters.fri import load_fri

SAMPLE_DIR = (
    Path(__file__).parent.parent
    / "Sample Requirements Docs"
    / "Haggen FRIs - latest"
    / "Paygroup 087"
)
FRI_UNION = SAMPLE_DIR / "Union" / "RTL Haggen UFCW King Grocery Clerks Local 3000.xlsx"
FRI_NU = SAMPLE_DIR / "Non-Union" / "RTL Haggen NU Retail.xlsx"
FRI_BAKERS = SAMPLE_DIR / "Union" / "RTL Haggen BCTW Kings & Snohomish Bakers Local 9.xlsx"

_union_exists = pytest.mark.skipif(not FRI_UNION.exists(), reason="FRI union sample not found")
_nu_exists = pytest.mark.skipif(not FRI_NU.exists(), reason="FRI non-union sample not found")
_bakers_exists = pytest.mark.skipif(not FRI_BAKERS.exists(), reason="FRI bakers sample not found")


# ---------------------------------------------------------------------------
# Union FRI — main fixture
# ---------------------------------------------------------------------------

@_union_exists
class TestFRIUnion:
    @pytest.fixture(scope="class")
    def reqs(self):
        return load_fri(FRI_UNION, paygroup="087")

    def test_loads_requirements(self, reqs):
        assert len(reqs) > 0

    def test_paygroup(self, reqs):
        assert all(r.paygroup == "087" for r in reqs)

    def test_source_is_fri(self, reqs):
        assert all(r.source == "FRI" for r in reqs)

    def test_ids_are_unique(self, reqs):
        ids = [r.id for r in reqs]
        assert len(ids) == len(set(ids))

    def test_id_format(self, reqs):
        for r in reqs:
            parts = r.id.split("-")
            assert parts[0] == "FRI"
            assert parts[1] == "087"

    def test_scope_is_all(self, reqs):
        # FRI scope is always "all" — each file is already scoped to one People Group
        assert all(r.scope_type == "all" for r in reqs)
        assert all(r.labor_agreements == [] for r in reqs)

    def test_applies_to_any_la(self, reqs):
        # scope_type="all" means applies_to() returns True for any LA set
        assert all(r.applies_to({"1400WA"}) for r in reqs)

    def test_sections_present(self, reqs):
        sections = {r.section for r in reqs}
        assert len(sections) > 3
        upper = {s.upper() for s in sections}
        assert any("ROUNDING" in s for s in upper)

    def test_category_captured(self, reqs):
        categories = {r.category for r in reqs if r.category}
        assert len(categories) > 0
        assert "Definition" in categories or "Overtime" in categories or "Premium" in categories

    def test_people_group_in_extra(self, reqs):
        assert all("people_group" in r.extra for r in reqs)
        groups = {r.extra["people_group"] for r in reqs}
        assert len(groups) == 1  # one file = one people group

    def test_no_empty_descriptions(self, reqs):
        assert all(r.description.strip() for r in reqs)

    def test_contract_reference_sometimes_present(self, reqs):
        with_ref = [r for r in reqs if r.contract_reference]
        assert len(with_ref) > 0

    def test_sub_population_filters_in_extra(self, reqs):
        # Include/Exclude columns capture sub-population filters (job classes, etc.)
        with_filter = [r for r in reqs if r.extra.get("include") or r.extra.get("exclude")]
        assert len(with_filter) > 0

    def test_no_metadata_sheets_leaked(self, reqs):
        bad = {"old", "change history", "title info"}
        sheet_names = {r.extra.get("sheet_name", "").lower() for r in reqs}
        assert not sheet_names & bad


# ---------------------------------------------------------------------------
# Non-union FRI
# ---------------------------------------------------------------------------

@_nu_exists
class TestFRINonUnion:
    @pytest.fixture(scope="class")
    def reqs(self):
        return load_fri(FRI_NU, paygroup="087")

    def test_loads_requirements(self, reqs):
        assert len(reqs) > 0

    def test_source_is_fri(self, reqs):
        assert all(r.source == "FRI" for r in reqs)

    def test_ids_are_unique(self, reqs):
        ids = [r.id for r in reqs]
        assert len(ids) == len(set(ids))

    def test_scope_is_all(self, reqs):
        assert all(r.scope_type == "all" for r in reqs)

    def test_no_empty_descriptions(self, reqs):
        assert all(r.description.strip() for r in reqs)


# ---------------------------------------------------------------------------
# Bakers FRI — larger file (981 rows in spreadsheet, many blank)
# ---------------------------------------------------------------------------

@_bakers_exists
class TestFRIBakers:
    @pytest.fixture(scope="class")
    def reqs(self):
        return load_fri(FRI_BAKERS, paygroup="087")

    def test_loads_requirements(self, reqs):
        assert len(reqs) > 0

    def test_ids_are_unique(self, reqs):
        ids = [r.id for r in reqs]
        assert len(ids) == len(set(ids))

    def test_no_empty_descriptions(self, reqs):
        assert all(r.description.strip() for r in reqs)


# ---------------------------------------------------------------------------
# Paygroup inference from folder name
# ---------------------------------------------------------------------------

@_union_exists
def test_paygroup_inferred_from_folder():
    reqs = load_fri(FRI_UNION)
    assert all(r.paygroup == "087" for r in reqs)