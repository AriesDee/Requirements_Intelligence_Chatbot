"""Integration tests for the RI adapter against the sample files in the repo."""

from pathlib import Path

import pytest

from ric.adapters.ri import load_ri

SAMPLE_DIR = Path(__file__).parent.parent / "Sample Requirements Docs"
CSV_073 = SAMPLE_DIR / "073 E-commerce .csv"
XLSX_087 = SAMPLE_DIR / "087 Haggen RI as of Oct 7 2025.xlsx"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def req_by_section(reqs, section_fragment: str):
    return [r for r in reqs if section_fragment.upper() in r.section.upper()]


# ---------------------------------------------------------------------------
# 073 CSV — single-sheet, LA scope embedded in description
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CSV_073.exists(), reason="073 CSV sample not in repo")
class TestCSV073:
    @pytest.fixture(scope="class")
    def reqs(self):
        return load_ri(CSV_073, paygroup="073")

    def test_loads_requirements(self, reqs):
        assert len(reqs) > 0

    def test_paygroup(self, reqs):
        assert all(r.paygroup == "073" for r in reqs)

    def test_source_is_ri(self, reqs):
        assert all(r.source == "RI" for r in reqs)

    def test_ids_are_unique(self, reqs):
        ids = [r.id for r in reqs]
        assert len(ids) == len(set(ids))

    def test_id_format(self, reqs):
        for r in reqs:
            parts = r.id.split("-")
            assert parts[0] == "RI"
            assert parts[1] == "073"

    def test_all_scope(self, reqs):
        # Row 2 in CSV: "Pay by the minute\n\nLabor Agreement(s): All\n"
        rounding = req_by_section(reqs, "ROUNDING")
        assert len(rounding) > 0
        assert rounding[0].scope_type == "all"
        assert rounding[0].labor_agreements == []

    def test_include_scope(self, reqs):
        # Daily OT rows with "Labor Agreement(s) : 1402OR, 1403VC"
        dot = req_by_section(reqs, "DAILY OVERTIME")
        include_reqs = [r for r in dot if r.scope_type == "include"]
        assert len(include_reqs) > 0
        for r in include_reqs:
            assert "1402OR" in r.labor_agreements
            assert "1403VC" in r.labor_agreements

    def test_exclude_scope(self, reqs):
        # Daily OT rows with "Exclude: 1402OR, 1403VC"
        dot = req_by_section(reqs, "DAILY OVERTIME")
        exclude_reqs = [r for r in dot if r.scope_type == "exclude"]
        assert len(exclude_reqs) > 0
        for r in exclude_reqs:
            assert "1402OR" in r.labor_agreements
            assert "1403VC" in r.labor_agreements

    def test_applies_to_resolves_correctly(self, reqs):
        dot = req_by_section(reqs, "DAILY OVERTIME")
        # An exclude req (excl. 1402OR, 1403VC) SHOULD apply to 1400WA
        exclude_reqs = [r for r in dot if r.scope_type == "exclude"]
        assert any(r.applies_to({"1400WA"}) for r in exclude_reqs)
        # And should NOT apply to an excluded code
        assert not any(
            r.applies_to({"1402OR"}) and r.scope_type == "exclude"
            and set(r.labor_agreements) == {"1402OR", "1403VC"}
            for r in exclude_reqs
        )

    def test_sections_are_set(self, reqs):
        sections = {r.section for r in reqs}
        assert "ROUNDING" in sections
        assert "DAILY OVERTIME" in sections
        assert "HOLIDAY NOT WORKED (HNW)" in sections

    def test_hnw_has_both_scope_types(self, reqs):
        hnw = req_by_section(reqs, "HOLIDAY NOT WORKED")
        scopes = {r.scope_type for r in hnw}
        assert "all" in scopes
        # Should also have include and/or exclude variants
        assert len(scopes) > 1

    def test_no_empty_descriptions(self, reqs):
        assert all(r.description.strip() for r in reqs)

    def test_contract_reference_captured(self, reqs):
        dot = req_by_section(reqs, "DAILY OVERTIME")
        with_ref = [r for r in dot if r.contract_reference]
        assert len(with_ref) > 0


# ---------------------------------------------------------------------------
# 087 Haggen RI xlsx — multi-sheet, LA codes in column header
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not XLSX_087.exists(), reason="087 RI xlsx not in sample dir")
class TestXLSX087:
    @pytest.fixture(scope="class")
    def reqs(self):
        return load_ri(XLSX_087, paygroup="087")

    def test_loads_requirements(self, reqs):
        assert len(reqs) > 0

    def test_paygroup(self, reqs):
        assert all(r.paygroup == "087" for r in reqs)

    def test_source_is_ri(self, reqs):
        assert all(r.source == "RI" for r in reqs)

    def test_ids_are_unique(self, reqs):
        ids = [r.id for r in reqs]
        assert len(ids) == len(set(ids))

    def test_multiple_sheets_loaded(self, reqs):
        sheet_names = {r.extra["sheet_name"] for r in reqs}
        assert len(sheet_names) > 1

    def test_sheet_las_captured(self, reqs):
        # Sheet-level LA codes should be stored in extra
        reqs_with_sheet_las = [r for r in reqs if r.extra.get("sheet_labor_agreements")]
        assert len(reqs_with_sheet_las) > 0

    def test_no_metadata_sheets_leaked(self, reqs):
        bad = {"title", "contracts", "change history", "old"}
        sheet_names = {r.extra["sheet_name"].lower() for r in reqs}
        assert not sheet_names & bad

    def test_sections_present(self, reqs):
        sections = {r.section for r in reqs}
        assert len(sections) > 0
        assert "" not in sections or len(sections) > 1

    def test_no_empty_descriptions(self, reqs):
        assert all(r.description.strip() for r in reqs)


# ---------------------------------------------------------------------------
# Paygroup inference
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not CSV_073.exists(), reason="073 CSV sample not in repo")
def test_paygroup_inferred_from_csv_filename():
    reqs = load_ri(CSV_073)
    assert all(r.paygroup == "073" for r in reqs)


@pytest.mark.skipif(not XLSX_087.exists(), reason="087 RI xlsx not in sample dir")
def test_paygroup_inferred_from_xlsx_filename():
    reqs = load_ri(XLSX_087)
    assert all(r.paygroup == "087" for r in reqs)