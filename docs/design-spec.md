# Requirements Intelligence Chatbot (RIC) — Design Specification

> Consolidated design document. Contains: cover summary, glossary, full design
> specification, and companion extraction schema for developers.
>
> Three diagrams accompany this document. They are referenced inline as
> `[DIAGRAM: ...]`. Image files should be placed at those points in the
> human-facing version; the captions below describe each one fully enough to
> follow the text without the image.

---

## Cover summary (one page)

**The problem.** When a union labor agreement is renegotiated, the change reaches the business as a plain-language memo (an IOC). An analyst must then figure out which of hundreds of timekeeping rules that memo affects. The memo is written for store managers, not for system configuration — so it never names the rules, the labor-agreement codes, or the requirement IDs the analyst actually works with. Today this translation happens by hand, from memory, against a large and densely written inventory. Skilled analysts do it well, but rules occasionally get missed — and a missed rule becomes a payroll error.

**The solution.** The Requirements Intelligence Chatbot reads the IOC and the current requirements inventory and produces a reviewed-by-a-human impact analysis: which rules the change touches, how complex the change looks, and what needs clarifying before anyone edits. It is a decision-support tool, not an automation tool — it never edits the inventory. The analyst stays fully in control; the tool's job is to make sure nothing is overlooked before they begin.

[DIAGRAM: Master architecture — the IOC and inventory feed a central analysis core; the core produces a structured analysis rendered as a report (phase 1) and a chatbot (phase 2).]

**Why it works.** The tool is deliberately tuned for completeness over precision. Flagging one rule too many costs an analyst seconds to dismiss; missing one costs a payroll defect. Its most valuable single capability is resolving the inventory's "include / exclude" scope logic — the exact place a human skims a rule, sees unfamiliar codes, and wrongly skips it. A computer never makes that inversion.

**Proven on real data.** Run against a real IOC and inventory, the tool caught findings a rushed analyst could miss: a holiday change that touched two rules in different sections rather than one, a sick-leave change that mapped to an existing rule, and an open question in the inventory that the IOC actually answered.

**The plan.** Phase 1 delivers the analysis as a structured report and proves it can be trusted. Phase 2 adds the conversational chatbot — grounded in that validated analysis — plus scale across the full inventory library. The architecture is built to carry the organization's move from the current Workbrain-based inventory (RI) to its application-agnostic successor (FRI) without a rewrite.

**What we need to confirm.** Two dependencies: the existing contract-to-labor-agreement mapping (already available), and whether the future FRI will store rule details in a more structured form than today's free-text inventory.

---

## Glossary

**IOC — Inter-Office Communication.** The plain-language memo that Legal/HR sends out after a labor agreement is negotiated and ratified, announcing the change to store managers. It is the tool's starting input. Written for a business audience, so it describes changes in everyday terms rather than in system or requirement identifiers.

**RI — Requirements Inventory.** The catalog of timekeeping rules that drives configuration in the current system (Infor Workbrain). Structured around Workbrain's calc-group model. The authoritative inventory today.

**FRI — Foundational Requirements Inventory.** A re-expression of the same requirements in an application-agnostic form, decoupled from Workbrain, so the rules survive a future move to a different application. The forward-looking successor to the RI. Both RI and FRI are requirements inventories; they differ in what they are structured around.

**LA — Labor Agreement.** A union contract governing a group of employees. Identified by a six-character code (for example 1400WA, 1401PM). Each rule in the inventory specifies which labor agreements it applies to. Not to be confused with a Contract ID, which is the shorter four-character form (for example 1400, 1401); one contract maps to one or more labor agreements.

**HNW — Holiday Not Worked.** A category of pay rule covering holiday pay for employees who do not work the holiday. It appears often in the sample inventory and is used in the spec as an example of a rule category a change might touch.

**BRD — Business Requirements Document.** A business-readable requirements write-up sometimes produced from an IOC. Mentioned in the spec as an output deliberately excluded from the current scope.

**Calc group — Calculation group.** A Workbrain structural concept the RI is organized around. Relevant because the FRI exists specifically to break the dependency on it.

**WFM — Workforce Management.** The functional domain this tool serves — the systems and rules governing employee time, attendance, scheduling, and pay.

---

## 1. Overview

When a labor agreement is negotiated or renewed, the change is communicated to the business through an Inter-Office Communication (IOC). A business analyst then has to work out how that change affects the organization's requirements inventory — the catalog of timekeeping rules that drives system configuration. Today this analysis is done from memory and manual reading. Analysts are skilled, but the inventory is large and the IOC is written in plain business language that doesn't line up with how the inventory is organized, so impacted requirements are occasionally missed. A missed requirement becomes a configuration defect that surfaces in payroll.

The Requirements Intelligence Chatbot is a decision-support tool, not an automation tool. It reads an IOC and the current requirements inventory, and produces a human-reviewed impact analysis: which requirements the change touches, how complex the change looks, and what needs clarification before anyone edits. The analyst stays fully in control — the tool never edits the inventory. Its job is to ensure nothing is overlooked before the analyst starts, and to surface the questions that should be asked up front.

The core value is completeness. The tool is deliberately tuned to catch every potentially impacted requirement, accepting that it will sometimes flag one that turns out not to matter. An analyst dismissing an irrelevant suggestion costs seconds; a missed requirement costs a payroll error. That trade-off shapes the entire design.

The product's end state is an interactive assistant that analysts can question directly about a change and its impact. Because a conversational answer is only as reliable as the analysis beneath it, the capability is built in two stages: the analysis core and its structured impact report first, and the conversational interface layered over that validated core once it is trusted. This specification details the analysis core (phase 1) in full and defines how the conversational layer (phase 2) builds on it.

## 2. Two requirements inventories: RI and FRI

The organization maintains its timekeeping requirements in two related but distinct forms, and the tool must understand both.

The Requirements Inventory (RI) is the original artifact. Its structure is tied to Infor Workbrain, the current enterprise Time and Attendance system — specifically to Workbrain's calc-group structure, because the requirements were written to drive that application's configuration. The RI is authoritative today but application-bound.

The Foundational Requirements Inventory (FRI) is the contract analysts' effort to re-express those same requirements in an application-agnostic form, deliberately decoupled from Workbrain's structure. Its purpose is portability: when the organization migrates to a different application, with different configuration items, the requirements should not have to be reverse-engineered out of a Workbrain-shaped inventory. The FRI is the forward-looking, durable version.

Both are requirements inventories serving the same fundamental role; they differ only in what they are structured around. The stated direction is for the FRI to become the primary inventory, with the RI as the legacy source. However, there is no fixed timeline for retiring the RI, and today many labor agreements have an RI but no FRI. The tool must therefore treat RI/FRI coexistence as a normal, indefinite operating condition — not a migration edge case. This is an architectural constraint on phase 1, addressed directly in section 4.

## 3. The problem, precisely

The difficulty is not that changes are complicated to make — analysts make edits confidently. The difficulty is in the analysis step that should happen first: surveying the full blast radius of a change across a large, densely written inventory.

Three properties of the documents make this hard. First, the IOC is written for store managers, not for timekeeping configuration. It describes a change in plain business language ("pharmacy staff get a higher Sunday premium") rather than in requirement identifiers or labor-agreement codes. Second, the IOC is under-specified by design — it may give an effective date without saying which of several dates governs the timekeeping change, or name a population without listing the labor agreements. Third, a single IOC bundles many changes across many domains — wages, benefits, pension, operational provisions — and only some touch timekeeping at all, so the analyst must triage relevance before matching anything.

A real example illustrates all three. The IOC for contracts 1400/1401 (073 GrocWorks union drivers, labor agreements 1400WA and 1401PM) is six pages covering pension, health and welfare, a third-party delivery arrangement, tipping, vacation accrual, jury duty, and funeral leave — most of which never touches timekeeping — alongside a few changes that do: a holiday-worked premium change, a holiday-week composition change, and a new job classification. Buried in the benefits language is a sick-leave change (a Seattle ordinance now applying) that does affect the inventory. Finding those few needles, then mapping them to specific requirements, is the manual work that leads to misses.

## 4. Architecture: an inventory-agnostic core with input adapters

Because RI/FRI coexistence is indefinite, the tool must not be built "against the RI" with FRI added later. The core analysis engine operates on an abstract, inventory-agnostic representation of a requirement — its identity, its scope, the change delta, and its configuration metadata (hour types, earn codes, effective conditions). The RI and the FRI are each an input adapter that reads its particular structure and normalizes it into this shared representation. The Workbrain calc-group shape of the RI lives entirely inside the RI adapter and never reaches the reasoning core.

This is the decision that lets the tool survive the migration. The analysis engine, the scope logic, the output tiering, and the clarification routing are all written once, against the abstract representation. Supporting the RI today means writing the RI adapter; making the FRI primary later means maturing the FRI adapter. Neither touches the engine. For any given labor agreement, the tool uses whichever inventory is available — in practice the RI today, the FRI as it comes online, and either when both exist.

This architecture also yields a valuable capability once both inventories exist for a labor agreement: the tool can run the same IOC against both and verify the impact analysis agrees — that a change lands on corresponding requirements in each. This is a built-in consistency check on the FRI re-creation effort, surfacing places where the FRI has drifted from or failed to capture what the RI encodes. It is deferred beyond phase 1, but the inventory-agnostic core is what makes it possible at no extra structural cost.

## 5. The central concept: analysis, not documents

The most important design decision is what sits at the center of the system. It is not the IOC and not the edits — it is the structured analysis in between: a machine-readable understanding of what changed, for which population, in what way, with what remaining uncertainty. Every output is a rendering of that analysis. Keeping it explicit, rather than jumping straight from IOC text to a list of requirements, is what makes the tool reviewable rather than a black box, what makes it inventory-agnostic (section 4), what will make the conversational layer safe (section 7), and what would let a business-readable rendering be added later without redesign.

## 6. How the analysis works

The pipeline has four stages, and the difficulty is not spread evenly.

The first stage classifies each change in the IOC. The IOC is decomposed into discrete changes, each categorized — a premium value change, a list operation (adding or removing a labor agreement or job code), an eligibility change, a rate change, a holiday-composition change — and tagged for timekeeping relevance. This turns an open-ended document into a set of bounded, typed changes, which makes everything downstream tractable. It is worth building and testing this stage first, in isolation, because everything after it inherits its quality.

Before matching, the tool normalizes identifiers. Contract IDs are four-character strings (1400, 1401); labor agreements are six-character strings (1400WA, 1401PM). An IOC may reference either. The organization maintains an existing mapping between contracts and labor agreements, and the tool uses it to resolve any contract reference to its constituent labor agreements and vice versa. This is a known lookup, not an open problem.

The second stage locates the affected requirements. This is the hardest stage, because the IOC cannot cite requirement identifiers. The tool matches by meaning and by contract reference, using both signals to keep recall high: semantic similarity between the change and each requirement's description, and the Contract Reference field, which ties each requirement back to a clause of the agreement, so a change can be cross-checked against requirements pointing at the same clause.

Within this stage sits the single most important piece of logic in the system: labor-agreement scope resolution. Each requirement declares its scope in one of three forms, and the tool must resolve all three against the change's target labor agreements. "Labor Agreement(s): All" applies to every agreement. A named list — "Labor Agreement(s): 1402OR, 1403VC" — applies only to those. "Exclude: 1402OR, 1403VC" applies to everyone except those, which for a 1400WA/1401PM change means it does apply.

[DIAGRAM: Scope resolution — for each rule, read its LA clause. "All" is in scope. A named list is in scope only if a target LA is listed. "Exclude" is in scope only if the target LA is not excluded. The exclude branch is the trap: it looks like a rule about the excluded LAs, but it governs everyone else — a human skims the codes and skips it; the tool resolves the set logic and catches it.]

That exclude case is the trap the tool exists to catch. A requirement reading "Exclude: 1402OR, 1403VC" looks, to a skimming human, like a requirement about Oregon and VC — so an analyst pattern-matches on those codes and skips it, when in fact it is precisely the requirement governing their Washington/PM change. A computer resolving the set logic never makes that inversion. This one check likely justifies the tool on its own. The requirement is that the tool parse the all/include/exclude language for every requirement and determine in-scope status by set logic, never by surface keyword matching.

The third stage describes the delta for each impacted requirement: current state, proposed new state, and the reason it is affected — anchored to the requirement's identifier so the output is precise. The fourth stage flags risk: potential conflicts, gaps where the IOC is silent, and clarification questions where the IOC is under-specified.

## 7. The output the analyst sees

The analyst receives a tiered impact map, and the tiering is essential to adoption. Over-surfacing catches misses, but past a certain volume it becomes noise that analysts learn to ignore, recreating the original problem. The output separates a confident tier of directly impacted requirements from a secondary tier of possibly-related requirements to check, from a set of flagged clarifications. Attention goes to the confident tier first;