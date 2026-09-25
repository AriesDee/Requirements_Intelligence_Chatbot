"""Unit tests for parse_scope() — one test per surface variant in the corpus."""

import pytest
from ric.parsing.scope import parse_scope


# ---------------------------------------------------------------------------
# All
# ---------------------------------------------------------------------------

def test_all_basic():
    assert parse_scope("Labor Agreement(s): All") == ("all", [])

def test_all_with_spaces_around_colon():
    assert parse_scope("Labor Agreement(s) : All") == ("all", [])

def test_all_trailing_whitespace():
    assert parse_scope("Labor Agreement(s): All\n") == ("all", [])

def test_all_buried_in_description():
    desc = "Pay by the minute\n\nLabor Agreement(s): All\n"
    assert parse_scope(desc) == ("all", [])


# ---------------------------------------------------------------------------
# Include (named list)
# ---------------------------------------------------------------------------

def test_include_basic():
    scope, codes = parse_scope("Labor Agreement(s): 1402OR, 1403VC")
    assert scope == "include"
    assert codes == ["1402OR", "1403VC"]

def test_include_space_before_colon():
    scope, codes = parse_scope("Labor Agreement(s) : 1402OR, 1403VC")
    assert scope == "include"
    assert codes == ["1402OR", "1403VC"]

def test_include_no_space_after_colon():
    scope, codes = parse_scope("Labor Agreement(s):1402OR, 1403VC")
    assert scope == "include"
    assert codes == ["1402OR", "1403VC"]

def test_include_no_parens():
    scope, codes = parse_scope("Labor Agreement : 1402OR, 1403VC")
    assert scope == "include"
    assert codes == ["1402OR", "1403VC"]

def test_include_buried_in_description():
    desc = (
        "All employees will receive overtime at 1.5X for hours over 10.\n\n"
        "Regular Hour type: DOT1 - Earn code: 101/171 adj.\n\n"
        "Labor Agreement(s) : 1402OR, 1403VC\n"
    )
    scope, codes = parse_scope(desc)
    assert scope == "include"
    assert codes == ["1402OR", "1403VC"]


# ---------------------------------------------------------------------------
# Exclude — inline form  ("Labor Agreement(s): Exclude: codes")
# ---------------------------------------------------------------------------

def test_exclude_inline_with_colon():
    scope, codes = parse_scope("Labor Agreement(s) : Exclude: 1402OR, 1403VC")
    assert scope == "exclude"
    assert codes == ["1402OR", "1403VC"]

def test_exclude_inline_double_colon_spaces():
    scope, codes = parse_scope("Labor Agreement(s) : Exclude:  1402OR, 1403VC")
    assert scope == "exclude"
    assert codes == ["1402OR", "1403VC"]

def test_exclude_inline_no_colon_after_keyword():
    # "Labor Agreement(s): Exclude 1402OR, 1403VC"  (no colon after Exclude)
    scope, codes = parse_scope("Labor Agreement(s): Exclude 1402OR, 1403VC")
    assert scope == "exclude"
    assert codes == ["1402OR", "1403VC"]


# ---------------------------------------------------------------------------
# Exclude — prefix form  ("Exclude Labor Agreement(s): codes")
# ---------------------------------------------------------------------------

def test_exclude_prefix_with_parens():
    scope, codes = parse_scope("Exclude Labor Agreement(s): 1402OR, 1403VC")
    assert scope == "exclude"
    assert codes == ["1402OR", "1403VC"]

def test_exclude_prefix_lowercase_agreement():
    scope, codes = parse_scope("Exclude Labor agreement(s): 1402OR, 1403VC")
    assert scope == "exclude"
    assert codes == ["1402OR", "1403VC"]

def test_exclude_prefix_no_parens():
    scope, codes = parse_scope("Exclude Labor Agreement : 1402OR, 1403VC")
    assert scope == "exclude"
    assert codes == ["1402OR", "1403VC"]

def test_exclude_prefix_with_leading_colon():
    scope, codes = parse_scope("Exclude: Labor Agreement(s): 1402OR, 1403VC")
    assert scope == "exclude"
    assert codes == ["1402OR", "1403VC"]


# ---------------------------------------------------------------------------
# Noise rejection — lines that mention "Exclude" but are NOT LA scope
# ---------------------------------------------------------------------------

def test_noise_exclude_day_not_matched_as_la():
    # "Exclude: Day after Thanksgiving (pay as REG)" — no LA code pattern
    desc = (
        "Employees will receive a holiday premium at 1.5X except the Day After Thanksgiving\n\n"
        "Exclude: Day after Thanksgiving (pay as REG)\n\n"
        "Labor Agreement(s): All"
    )
    scope, codes = parse_scope(desc)
    assert scope == "all"
    assert codes == []

def test_narrative_labor_agreement_line_ignored():
    desc = (
        "For the Labor Agreements listed below the following rules will be used:\n\n"
        "1. Full-time employees will be paid 8 hours.\n\n"
        "Labor Agreement(s): 1402OR, 1403VC"
    )
    scope, codes = parse_scope(desc)
    assert scope == "include"
    assert codes == ["1402OR", "1403VC"]


# ---------------------------------------------------------------------------
# Default when no scope clause present
# ---------------------------------------------------------------------------

def test_no_scope_defaults_to_all():
    desc = "There will be no compounding or pyramiding of any overtime and premium pay."
    scope, codes = parse_scope(desc)
    assert scope == "all"
    assert codes == []

def test_empty_string_defaults_to_all():
    assert parse_scope("") == ("all", [])