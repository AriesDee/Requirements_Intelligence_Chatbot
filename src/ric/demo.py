"""
Sample data for demo / UI testing — no API key or file uploads required.
"""
from ric.flagging.models import FlagSeverity, RiskFlag
from ric.ioc.models import ChangeType, IOCChange, IOCParseResult
from ric.matcher.models import ChangeMatch, RequirementMatch
from ric.models import Requirement


def sample_ioc() -> IOCParseResult:
    return IOCParseResult(
        contract_ids=["1400", "1401"],
        labor_agreement_ids=["1400WA", "1401PM"],
        effective_date="2026-01-01",
        union_locals=["UFCW 3000", "UFCW 555"],
        changes=[
            IOCChange(
                change_type=ChangeType.WAGE_RATE,
                summary="All wage classifications receive a $0.75/hr increase effective January 1, 2026.",
                source_text=(
                    "Effective January 1, 2026, all employees covered under this agreement "
                    "shall receive a wage increase of $0.75 per hour applied to all wage "
                    "schedule classifications."
                ),
                labor_agreements=["1400WA", "1401PM"],
                effective_date=None,
                timekeeping_relevant=True,
            ),
            IOCChange(
                change_type=ChangeType.PREMIUM_VALUE,
                summary="One-time ratification bonus of $500 for all active employees as of ratification date.",
                source_text=(
                    "All active employees on the payroll as of the ratification date shall "
                    "receive a one-time ratification bonus of $500.00, payable within 30 days "
                    "of ratification."
                ),
                labor_agreements=["1400WA"],
                effective_date="2025-11-15",
                timekeeping_relevant=True,
            ),
            IOCChange(
                change_type=ChangeType.BENEFIT,
                summary="Health & Welfare contribution increases by $0.25/hr to $9.75/hr effective January 1, 2026.",
                source_text=(
                    "The Employer's Health and Welfare contribution shall increase from $9.50 "
                    "per hour to $9.75 per hour for all hours paid, effective January 1, 2026."
                ),
                labor_agreements=["1400WA", "1401PM"],
                effective_date=None,
                timekeeping_relevant=False,
            ),
            IOCChange(
                change_type=ChangeType.HOLIDAY_COMPOSITION,
                summary="Indigenous Peoples Day added to the recognized holiday schedule.",
                source_text=(
                    "Indigenous Peoples Day (observed the second Monday of October) is hereby "
                    "added to the list of recognized holidays under Section 12.1 of this agreement."
                ),
                labor_agreements=["1400WA"],
                effective_date=None,
                timekeeping_relevant=True,
            ),
            IOCChange(
                change_type=ChangeType.ELIGIBILITY,
                summary="Probationary period for new hires reduced from 90 days to 60 days.",
                source_text=(
                    "The probationary period for newly hired employees shall be reduced from "
                    "ninety (90) calendar days to sixty (60) calendar days."
                ),
                labor_agreements=["1401PM"],
                effective_date=None,
                timekeeping_relevant=False,
            ),
        ],
    )


def sample_results(ioc: IOCParseResult) -> list[ChangeMatch]:
    changes = ioc.changes
    return [
        # Change 0: wage rate
        ChangeMatch(
            change=changes[0],
            risk_flags=[
                RiskFlag(
                    flag_type="multi_la_variance",
                    severity=FlagSeverity.LOW,
                    description=(
                        "The wage increase applies to both 1400WA and 1401PM, but each LA "
                        "may maintain a separate wage schedule with different classification names."
                    ),
                    recommendation=(
                        "Confirm with Labor Relations whether the wage schedules for 1400WA and "
                        "1401PM are identical or need to be updated independently."
                    ),
                ),
            ],
            matched_requirements=[
                RequirementMatch(
                    requirement_id="REQ-001",
                    relevance="direct",
                    rationale="REQ-001 defines the base wage rate table used to calculate regular pay — a $0.75/hr increase directly updates these values.",
                    delta_description=(
                        "Update all wage schedule classifications in the base rate table by +$0.75/hr "
                        "effective 2026-01-01. Verify each step rate in the 1400WA and 1401PM wage "
                        "schedules is updated and re-published."
                    ),
                ),
                RequirementMatch(
                    requirement_id="REQ-015",
                    relevance="indirect",
                    rationale="REQ-015 governs overtime premium calculations that are derived from the base rate.",
                    delta_description=(
                        "Verify whether overtime dollar amounts are expressed as a multiplier of the "
                        "base rate (no change needed) or as hardcoded values. If hardcoded, recalculate "
                        "OT rates using the new base rates effective 2026-01-01."
                    ),
                ),
                RequirementMatch(
                    requirement_id="REQ-023",
                    relevance="indirect",
                    rationale="REQ-023 defines shift differential earn codes that may be expressed as a percentage of the base rate.",
                    delta_description=(
                        "Check whether shift differentials for 1400WA/1401PM are percentage-based "
                        "(self-adjusting) or fixed dollar amounts. If fixed, update them to reflect "
                        "the new wage scale effective 2026-01-01."
                    ),
                ),
            ],
        ),
        # Change 1: ratification bonus
        ChangeMatch(
            change=changes[1],
            risk_flags=[
                RiskFlag(
                    flag_type="retroactive_pay",
                    severity=FlagSeverity.HIGH,
                    description=(
                        "The $500 ratification bonus must be paid within 30 days of ratification "
                        "(effective 2025-11-15). The payment deadline may be imminent or already past."
                    ),
                    recommendation=(
                        "Confirm the ratification date with Labor Relations immediately. "
                        "If the 30-day window is approaching, escalate to Payroll to prioritize configuration."
                    ),
                ),
                RiskFlag(
                    flag_type="clarification_needed",
                    severity=FlagSeverity.MEDIUM,
                    description=(
                        "The IOC does not specify the taxability treatment for the ratification bonus "
                        "or whether it counts toward the overtime base for the pay period."
                    ),
                    recommendation=(
                        "Confirm with Payroll/Tax that this is treated as supplemental wages "
                        "(22% flat federal withholding) and excluded from the OT base calculation."
                    ),
                ),
            ],
            matched_requirements=[
                RequirementMatch(
                    requirement_id="REQ-042",
                    relevance="direct",
                    rationale="REQ-042 covers one-time bonus earn code configuration and taxability rules.",
                    delta_description=(
                        "Configure a one-time earn code for the $500 ratification bonus for LA 1400WA, "
                        "payable within 30 days of ratification (by 2025-12-15). Confirm taxability "
                        "classification (supplemental wage rate) and ensure it does not count toward "
                        "overtime base for the pay period."
                    ),
                ),
            ],
        ),
        # Change 2: H&W benefit — non-TK
        ChangeMatch(
            change=changes[2],
            risk_flags=[
                RiskFlag(
                    flag_type="implementation_risk",
                    severity=FlagSeverity.LOW,
                    description=(
                        "Although this is a non-TK change, if the WFM system tracks benefit-eligible "
                        "hours via earn codes, the hour cap tied to the H&W rate may also need updating."
                    ),
                    recommendation=(
                        "Verify whether an hour cap is configured for the H&W earn code. "
                        "If so, coordinate with the benefits team to update it alongside the rate change."
                    ),
                ),
            ],
            matched_requirements=[
                RequirementMatch(
                    requirement_id="REQ-088",
                    relevance="direct",
                    rationale="REQ-088 governs H&W deduction earn codes and employer contribution amounts tracked in the system.",
                    delta_description=(
                        "Update the H&W employer contribution rate from $9.50/hr to $9.75/hr "
                        "for LAs 1400WA and 1401PM, effective 2026-01-01. Update the deduction "
                        "earn code cap if one is configured."
                    ),
                ),
            ],
        ),
        # Change 3: holiday composition
        ChangeMatch(
            change=changes[3],
            risk_flags=[
                RiskFlag(
                    flag_type="missing_earn_code",
                    severity=FlagSeverity.MEDIUM,
                    description=(
                        "Indigenous Peoples Day is a new holiday — an earn code for this holiday "
                        "may not exist in the system and will need to be created before the date."
                    ),
                    recommendation=(
                        "Check whether an earn code for Indigenous Peoples Day already exists. "
                        "If not, submit an IT configuration request immediately — allow 2–3 weeks lead time."
                    ),
                ),
                RiskFlag(
                    flag_type="ambiguous_language",
                    severity=FlagSeverity.LOW,
                    description=(
                        "The holiday is described as 'observed the second Monday of October' "
                        "without specifying the year or a fixed date, which requires annual recalculation."
                    ),
                    recommendation=(
                        "Verify the WFM holiday calendar uses the floating observed date rule "
                        "(not a hardcoded date). Confirm 2026-10-12 is the correct first occurrence."
                    ),
                ),
            ],
            matched_requirements=[
                RequirementMatch(
                    requirement_id="REQ-055",
                    relevance="direct",
                    rationale="REQ-055 defines the recognized holiday list for LA 1400WA used to trigger holiday pay rules.",
                    delta_description=(
                        "Add 'Indigenous Peoples Day' (second Monday of October) to the holiday "
                        "calendar for LA 1400WA under Section 12.1. Assign or create an earn code "
                        "for this holiday. Verify the holiday falls on 2026-10-12 for the first "
                        "applicable occurrence."
                    ),
                ),
                RequirementMatch(
                    requirement_id="REQ-063",
                    relevance="indirect",
                    rationale="REQ-063 governs holiday premium pay calculations — adding a holiday means this rule will now fire on the new date.",
                    delta_description=(
                        "No configuration change expected — REQ-063 applies generically to all "
                        "recognized holidays. Verify that the holiday premium rule activates correctly "
                        "for Indigenous Peoples Day (2026-10-12) after the holiday is added to the calendar."
                    ),
                ),
            ],
        ),
        # Change 4: eligibility — no TK match
        ChangeMatch(
            change=changes[4],
            matched_requirements=[],
            no_match_reason=(
                "Probationary period length is a HR/policy setting, not a timekeeping or "
                "payroll configuration. No WFM requirements are affected."
            ),
        ),
    ]


def sample_chat_history() -> list[dict]:
    """Pre-baked Q&A conversation demonstrating what users can ask the chat."""
    return [
        {
            "role": "user",
            "content": "Which changes are timekeeping-relevant and need action before January 1, 2026?",
        },
        {
            "role": "model",
            "content": (
                "Three of the five changes are timekeeping-relevant and require WFM action before **2026-01-01**:\n\n"
                "1. **Wage Rate Increase** — All classifications for LAs 1400WA and 1401PM receive +$0.75/hr. "
                "REQ-001 (base wage table) must be updated directly; REQ-015 (OT calculation) and REQ-023 "
                "(shift differentials) need to be verified for downstream impact.\n\n"
                "2. **Ratification Bonus** — A one-time $500 payment for LA 1400WA active employees. "
                "This has an earlier deadline: payable within 30 days of ratification "
                "(**by ~2025-12-15**). REQ-042 (bonus earn code) must be configured urgently.\n\n"
                "3. **Indigenous Peoples Day added to holiday schedule** — Applies to LA 1400WA only. "
                "REQ-055 (holiday calendar) needs the new date added; REQ-063 (holiday premium rule) "
                "should be verified to confirm it fires correctly on the new holiday.\n\n"
                "The H&W contribution increase and probationary period change are **not** timekeeping-relevant "
                "and do not require WFM system updates."
            ),
        },
        {
            "role": "user",
            "content": "What exactly needs to change in the system for the wage rate increase?",
        },
        {
            "role": "model",
            "content": (
                "For the **wage rate increase** (+$0.75/hr, effective 2026-01-01, LAs 1400WA and 1401PM), "
                "here is what needs to happen:\n\n"
                "**Direct action — REQ-001 (Base Wage Rate Table)**\n"
                "Update every wage classification in the schedule by +$0.75/hr. "
                "This includes all step rates in both the 1400WA and 1401PM wage tables. "
                "Re-publish the updated schedule before the effective date.\n\n"
                "**Verify — REQ-015 (Overtime Premium Calculation)**\n"
                "Check whether OT amounts are expressed as a multiplier of the base rate "
                "(e.g. 1.5× — self-adjusting, no change needed) or as hardcoded dollar values. "
                "If hardcoded, recalculate using the new base rates effective 2026-01-01.\n\n"
                "**Verify — REQ-023 (Shift Differentials)**\n"
                "Check whether differentials are percentage-based (self-adjusting) or fixed dollar amounts. "
                "If fixed, update them to align with the new wage scale.\n\n"
                "In summary: REQ-001 **must** be updated; REQ-015 and REQ-023 **may** need updates "
                "depending on how they are configured in your system."
            ),
        },
        {
            "role": "user",
            "content": "Which change has no matched requirements and why?",
        },
        {
            "role": "model",
            "content": (
                "The **probationary period change** (Change 5) has no matched requirements.\n\n"
                "The change reduces the probationary period for new hires under LA 1401PM from "
                "90 days to 60 days. This is a **HR/policy setting** — it determines how long "
                "a new employee is on probation, which is managed in the HRIS or an employee "
                "lifecycle system, not in the WFM/timekeeping system.\n\n"
                "Since the Requirements Inventory only covers timekeeping and payroll rules "
                "configured in Workbrain/WFM, there are no requirements that describe or "
                "govern probationary period length, and therefore no matches were found."
            ),
        },
        {
            "role": "user",
            "content": "Give me a summary I can paste into an email to my team.",
        },
        {
            "role": "model",
            "content": (
                "Here's a ready-to-paste summary:\n\n"
                "---\n\n"
                "**IOC Impact Summary — Contracts 1400WA / 1401PM (Effective 2026-01-01)**\n\n"
                "The RIC analysis identified **5 contract changes** across this IOC. "
                "**3 are timekeeping-relevant** and require WFM system updates. "
                "A total of **7 requirements** were matched (5 direct, 2 indirect).\n\n"
                "**Action items before 2026-01-01:**\n"
                "- [ ] REQ-001 — Update base wage rate table (+$0.75/hr, all classes, 1400WA & 1401PM)\n"
                "- [ ] REQ-055 — Add Indigenous Peoples Day to holiday calendar (1400WA, 2026-10-12)\n"
                "- [ ] REQ-015 — Verify OT premium calculation (may self-adjust)\n"
                "- [ ] REQ-023 — Verify shift differentials (may self-adjust)\n"
                "- [ ] REQ-063 — Verify holiday premium rule fires on new holiday date\n\n"
                "**Action item before ~2025-12-15:**\n"
                "- [ ] REQ-042 — Configure one-time $500 ratification bonus earn code (1400WA only)\n\n"
                "**No WFM action required:**\n"
                "- H&W contribution increase ($9.50 → $9.75/hr) — benefits side only; "
                "REQ-088 to be updated by benefits team\n"
                "- Probationary period change (90 → 60 days) — HR/HRIS only, no WFM impact\n\n"
                "Please review the full Impact Analysis report (attached) for rationale and details.\n\n"
                "---"
            ),
        },
    ]


def sample_requirements() -> list[Requirement]:
    """Requirement objects matching the IDs used in sample_results()."""
    return [
        Requirement(
            id="REQ-001", source="FRI", paygroup="087",
            section="Wage Rates",
            description=(
                "The base wage rate table defines the hourly rate for each job classification "
                "covered under the labor agreement. Rates are maintained per step and classification "
                "in the WFM system and are used as the basis for all regular pay calculations. "
                "Any change to the negotiated wage schedule must be reflected here before the effective date."
            ),
            scope_type="include", labor_agreements=["1400WA", "1401PM"],
        ),
        Requirement(
            id="REQ-015", source="FRI", paygroup="087",
            section="Overtime",
            description=(
                "Overtime premium pay is calculated at 1.5× the employee's regular rate of pay "
                "for all hours worked in excess of 8 per day or 40 per week, per applicable state law. "
                "The system computes overtime using the blended rate where multiple earn codes are present. "
                "Hardcoded OT dollar amounts must be recalculated whenever the base rate changes."
            ),
            scope_type="include", labor_agreements=["1400WA", "1401PM"],
        ),
        Requirement(
            id="REQ-023", source="RI", paygroup="087",
            section="Premium Pay — Shift Differentials",
            description=(
                "Shift differential premiums apply to employees working evening or overnight shifts "
                "as defined in the labor agreement. Differentials may be expressed as a fixed dollar "
                "amount per hour or as a percentage of the base rate. The earn code configuration "
                "determines whether the differential auto-adjusts when the base rate changes."
            ),
            scope_type="include", labor_agreements=["1400WA", "1401PM"],
        ),
        Requirement(
            id="REQ-042", source="RI", paygroup="087",
            section="Bonus Payments",
            description=(
                "One-time bonus payments such as ratification bonuses and signing bonuses are processed "
                "via dedicated earn codes that are separate from regular wages. These earn codes must be "
                "configured for correct taxability (supplemental wage rate), excluded from the OT base, "
                "and activated only for the applicable paygroups and effective date range."
            ),
            scope_type="include", labor_agreements=["1400WA"],
        ),
        Requirement(
            id="REQ-055", source="FRI", paygroup="087",
            section="Holidays — Recognized Holiday Calendar",
            description=(
                "The recognized holiday calendar lists all holidays for which employees are entitled "
                "to holiday pay or premium rates under Section 12.1 of the labor agreement. "
                "Each holiday must be entered with its observed date (floating or fixed), "
                "an associated earn code, and the applicable labor agreements. "
                "New holidays require IT configuration before the first occurrence."
            ),
            scope_type="include", labor_agreements=["1400WA"],
        ),
        Requirement(
            id="REQ-063", source="FRI", paygroup="087",
            section="Holidays — Premium Pay",
            description=(
                "Employees who work on a recognized holiday are entitled to holiday premium pay "
                "in addition to their regular rate, as specified in the labor agreement. "
                "The WFM system automatically applies the holiday premium earn code to hours worked "
                "on any date that appears on the recognized holiday calendar. No separate configuration "
                "is needed per holiday — the rule fires generically for all calendar entries."
            ),
            scope_type="include", labor_agreements=["1400WA"],
        ),
        Requirement(
            id="REQ-088", source="RI", paygroup="087",
            section="H&W Benefits — Employer Contribution",
            description=(
                "The employer Health and Welfare contribution rate is tracked per hour paid for "
                "benefits-eligible employees. The contribution amount is maintained in the benefits "
                "configuration module and is separate from timekeeping earn codes. "
                "If the system enforces an hour cap tied to the H&W rate, that cap must also be "
                "reviewed when the contribution rate changes."
            ),
            scope_type="include", labor_agreements=["1400WA", "1401PM"],
        ),
    ]
