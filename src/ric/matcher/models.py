from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from ric.ioc.models import IOCChange

if TYPE_CHECKING:
    from ric.flagging.models import RiskFlag


class RequirementMatch(BaseModel):
    requirement_id: str = Field(description="ID of the matched requirement")
    relevance: Literal["direct", "indirect"] = Field(
        description=(
            "direct = this requirement directly describes what changed and must be reviewed; "
            "indirect = this requirement may be affected by the change"
        )
    )
    rationale: str = Field(
        description="One sentence explaining why this requirement is relevant to the change"
    )
    delta_description: str = Field(
        description=(
            "Concrete action statement for a WFM analyst: "
            "for direct matches, what value/rule to change (from → to, with effective date); "
            "for indirect matches, what to verify and under what condition an update is needed. "
            "1–3 sentences. Reference specific dollar amounts, earn codes, or dates from the change."
        )
    )


class ChangeMatch(BaseModel):
    change: IOCChange
    matched_requirements: list[RequirementMatch] = Field(default_factory=list)
    no_match_reason: str | None = Field(
        default=None,
        description="If no requirements matched, the reason why",
    )
    risk_flags: list = Field(
        default_factory=list,
        description="Risk and clarification flags identified by Stage 4",
    )
