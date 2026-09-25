"""Integration tests for the IOC reader and parser.

Reader tests (no API key): verify PDF text extraction.
Parser tests: require ANTHROPIC_API_KEY in the environment.
"""
import os
from pathlib import Path

import pytest

from ric.ioc.models import ChangeType, IOCParseResult
from ric.ioc.reader import extract_text

SAMPLE_DIR = Path(__file__).parent.parent / "Sample Requirements Docs"

IOC_WA_PM = (
    SAMPLE_DIR
    / "IOC_1400WA1401PM Contract Renewal for GrocWorks Driver 313 WA.PM"
      " - Eff. 8.1.22 Ratified 8.24_STANDARDIZED-10.04.2024.pdf"
)
IOC_BK = SAMPLE_DIR / "IOC_0114BK+ Contract Renewal  Local 125_STANDARDIZED.pdf"

_wa_pm_exists = pytest.mark.skipif(not IOC_WA_PM.exists(), reason="WA/PM IOC sample not found")
_bk_exists = pytest.mark.skipif(not IOC_BK.exists(), reason="BK IOC sample not found")
_api_key = pytest.mark.skipif(
    not os.getenv("ANTHROPIC_API_KEY"), reason="ANTHROPIC_API_KEY not set"
)


# ---------------------------------------------------------------------------
# Reader tests — deterministic, no API key needed
# ---------------------------------------------------------------------------

@_wa_pm_exists
class TestReaderWAPM:
    @pytest.fixture(scope="class")
    def text(self):
        return extract_text(IOC_WA_PM)

    def test_returns_nonempty_string(self, text):
        assert isinstance(text, str) and len(text) > 500

    def test_multipage_content(self, text):
        assert text.count("\n") > 20

    def test_contract_ids_in_text(self, text):
        assert "1400" in text or "1401" in text


@_bk_exists
class TestReaderBK:
    @pytest.fixture(scope="class")
    def text(self):
        return extract_text(IOC_BK)

    def test_returns_nonempty_string(self, text):
        assert isinstance(text, str) and len(text) > 500

    def test_contract_id_in_text(self, text):
        assert "0114" in text


def test_unsupported_extension_raises():
    with pytest.raises(ValueError, match="Unsupported"):
        extract_text(Path("not_a_pdf.docx"))


# ---------------------------------------------------------------------------
# Parser tests — require ANTHROPIC_API_KEY
# ---------------------------------------------------------------------------

@_wa_pm_exists
@_api_key
class TestParserWAPM:
    @pytest.fixture(scope="class")
    def result(self):
        from ric.ioc.parser import parse_ioc
        return parse_ioc(IOC_WA_PM)

    def test_returns_parse_result(self, result):
        assert isinstance(result, IOCParseResult)

    def test_la_ids_found(self, result):
        combined = " ".join(result.contract_ids + result.labor_agreement_ids)
        assert "1400" in combined

    def test_changes_extracted(self, result):
        assert len(result.changes) >= 2

    def test_wage_rate_change_present(self, result):
        assert any(c.change_type == ChangeType.WAGE_RATE for c in result.changes)

    def test_timekeeping_relevant_changes_flagged(self, result):
        assert any(c.timekeeping_relevant for c in result.changes)

    def test_benefit_changes_not_timekeeping(self, result):
        benefit = [c for c in result.changes if c.change_type == ChangeType.BENEFIT]
        if benefit:
            assert all(not c.timekeeping_relevant for c in benefit)

    def test_all_changes_have_summaries(self, result):
        assert all(c.summary.strip() for c in result.changes)

    def test_all_changes_have_source_text(self, result):
        assert all(c.source_text.strip() for c in result.changes)

    def test_labor_agreements_are_six_chars(self, result):
        for change in result.changes:
            for la in change.labor_agreements:
                assert len(la) == 6, f"Expected 6-char LA code, got {la!r}"


@_bk_exists
@_api_key
class TestParserBK:
    @pytest.fixture(scope="class")
    def result(self):
        from ric.ioc.parser import parse_ioc
        return parse_ioc(IOC_BK)

    def test_returns_parse_result(self, result):
        assert isinstance(result, IOCParseResult)

    def test_changes_extracted(self, result):
        assert len(result.changes) >= 2

    def test_bk_la_referenced(self, result):
        all_las = result.labor_agreement_ids + [
            la for c in result.changes for la in c.labor_agreements
        ]
        assert any("0114" in la for la in all_las)

    def test_all_changes_have_source_text(self, result):
        assert all(c.source_text.strip() for c in result.changes)
