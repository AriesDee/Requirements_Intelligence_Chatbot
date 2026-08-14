from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class FlagSeverity(str, Enum):
    HIGH   = "high"    # Blocks implementation — must resolve before go-live
    MEDIUM = "medium"  # Must review before implementing
    LOW    = "low"     # Monitor — unlikely to block but worth noting


FlagType = Literal[
    "retroactive_pay",       # Payment deadline may have passed or is imminent
    "missing_earn_code",     # Earn code referenced or implied but not defined
    "ambiguous_language",    # "may", "at discretion of", "as mutually agreed" etc.
    "conflicting_dates",     # Effective date differs from or conflicts with IOC date
    "multi_la_variance",     # Change applies differently across LAs in this IOC
    "implementation_risk",   # Complex rule, edge case, or IT lead-time concern
    "clarification_needed",  # Open question that requires input from Labor Relations
]


class RiskFlag(BaseModel):
    flag_type: FlagType = Field(description="Category of this risk or clarification flag")
    severity: FlagSeverity = Field(description="Impact level: high / medium / low")
    description: str = Field(
        description="Plain-language description of the issue — what is unclear or at risk"
    )
    recommendation: str = Field(
        description="Concrete next step the analyst or team should take to resolve this flag"
    )
