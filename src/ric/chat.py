"""
Chat module — Q&A over a loaded impact analysis using Gemini via Vertex AI.
"""
from google.genai import types

from ric._vertex import make_client
from ric.ioc.models import IOCParseResult
from ric.matcher.models import ChangeMatch

_SYSTEM = """\
You are a helpful analyst assistant for the Requirements Intelligence Chatbot (RIC).

You have been given a complete IOC (Inter-Office Communication) impact analysis as context.
The analysis shows:
- The IOC metadata (contract IDs, labor agreement IDs, effective dates, union locals)
- Each change extracted from the IOC (type, summary, source text, which LAs it affects)
- Which WFM/timekeeping requirements are matched to each change
- The relevance level (direct = must update, indirect = verify)
- The rationale for each match
- The delta description — a concrete action statement for the WFM analyst

Answer the user's questions about this analysis accurately and concisely.
Use the context provided. Do not invent requirement IDs, change details, or dollar amounts
that are not in the context. If you are unsure, say so.
You may provide general labor agreement or WFM/Workbrain guidance when it adds value.
"""


def build_context(ioc: IOCParseResult, results: list[ChangeMatch]) -> str:
    """Serialize the full analysis into a text block for the LLM system prompt."""
    lines = [
        "## IOC ANALYSIS CONTEXT",
        "",
        "### IOC Metadata",
        f"Contract IDs: {', '.join(ioc.contract_ids) or '—'}",
        f"Labor Agreement IDs: {', '.join(ioc.labor_agreement_ids) or '—'}",
        f"Effective Date: {ioc.effective_date or '—'}",
        f"Union Locals: {', '.join(ioc.union_locals) or '—'}",
        f"Total Changes: {len(results)}",
        "",
        "### Changes and Matched Requirements",
    ]

    for i, cm in enumerate(results, 1):
        ch = cm.change
        lines += [
            "",
            f"#### Change {i}: {ch.change_type.value} "
            f"({'TK-Relevant' if ch.timekeeping_relevant else 'Non-TK'})",
            f"Summary: {ch.summary}",
            f"Effective Date: {ch.effective_date or ioc.effective_date or '—'}",
            f"LAs: {', '.join(ch.labor_agreements) or 'All IOC LAs'}",
            f'Source: "{ch.source_text[:400]}"',
        ]

        if cm.matched_requirements:
            lines.append(f"Matched Requirements ({len(cm.matched_requirements)}):")
            for m in cm.matched_requirements:
                lines += [
                    f"  - {m.requirement_id} [{m.relevance}]",
                    f"    Rationale: {m.rationale}",
                    f"    Delta: {m.delta_description or '—'}",
                ]
        else:
            lines.append(
                f"No matched requirements. "
                f"Reason: {cm.no_match_reason or 'None found'}"
            )

    return "\n".join(lines)


def ask(
    question: str,
    context: str,
    history: list[dict],
    *,
    model: str = "gemini-2.5-flash",
) -> str:
    """Send a question to Gemini (Vertex AI) with the analysis context and conversation history."""
    client = make_client()

    history_contents = [
        types.Content(
            role=msg["role"],
            parts=[types.Part(text=msg["content"])],
        )
        for msg in history
    ]

    chat = client.chats.create(
        model=model,
        config=types.GenerateContentConfig(
            system_instruction=_SYSTEM + "\n\n" + context,
        ),
        history=history_contents,
    )

    response = chat.send_message(question)
    return response.text
