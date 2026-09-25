from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ChangeType(str, Enum):
    WAGE_RATE = "wage_rate"
    PREMIUM_VALUE = "premium_value"
    ELIGIBILITY = "eligibility"
    LIST_OPERATION = "list_operation"
    HOLIDAY_COMPOSITION = "holiday_composition"
    BENEFIT = "benefit"
    OTHER = "other"


class IOCChange(BaseModel):
    change_type: ChangeType = Field(description="Category of this change")
    timekeeping_relevant: bool = Field(
        description=(
            "True if this change affects how time is tracked, earn-coded, or paid "
            "(e.g. wage rates, premiums, holidays). False for purely benefits-side "
            "changes such as H&W or pension contribution amounts."
        )
    )
    summary: str = Field(description="1-2 sentence plain-language summary of the change")
    effective_date: str | None = Field(
        default=None,
        description="Effective date of this specific change (ISO or natural language), "
                    "or null if it matches the overall IOC effective date",
    )
    labor_agreements: list[str] = Field(
        default_factory=list,
        description="6-char LA codes this change applies to (e.g. ['1400WA', '1401PM'])",
    )
    source_text: str = Field(
        description="Verbatim text from the IOC that describes this change"
    )
    notes: str | None = Field(
        default=None,
        description="Any uncertainty, ambiguity, or open question about this change",
    )


class IOCParseResult(BaseModel):
    contract_ids: list[str] = Field(
        description="4-character contract IDs from the IOC (e.g. ['1400', '1401'])"
    )
    labor_agreement_ids: list[str] = Field(
        description="6-character LA IDs (e.g. ['1400WA', '1401PM', '0114BK'])"
    )
    effective_date: str | None = Field(
        default=None, description="Overall effective date of the IOC"
    )
    union_locals: list[str] = Field(
        default_factory=list, description="Union local names mentioned in the IOC"
    )
    changes: list[IOCChange] = Field(description="All changes described in the IOC")
