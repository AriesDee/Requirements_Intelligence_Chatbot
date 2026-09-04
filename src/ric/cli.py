import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ric",
        description="Requirements Intelligence Chatbot — IOC impact analysis",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("analyze", help="Analyze an IOC against a requirements inventory")
    p.add_argument("--ioc", required=True, type=Path, metavar="FILE",
                   help="Path to IOC PDF")
    p.add_argument("--fri", nargs="+", type=Path, default=[], metavar="FILE",
                   help="One or more FRI xlsx files")
    p.add_argument("--ri", nargs="+", type=Path, default=[], metavar="FILE",
                   help="One or more RI xlsx or csv files")
    p.add_argument("--paygroup", default=None,
                   help="Paygroup override (inferred from filename when omitted)")
    p.add_argument("--output", default="impact_analysis", metavar="BASENAME",
                   help="Output file basename without extension (default: impact_analysis)")
    p.add_argument("--model", default="gemini-2.5-flash", metavar="MODEL",
                   help="Gemini model ID (default: gemini-2.5-flash)")

    args = parser.parse_args()
    if args.command == "analyze":
        _run_analyze(args)


def _run_analyze(args: argparse.Namespace) -> None:
    if not args.fri and not args.ri:
        print("Error: provide at least one --fri or --ri file.", file=sys.stderr)
        sys.exit(1)

    from ric.adapters.fri import load_fri
    from ric.adapters.ri import load_ri
    from ric.flagging import flag_changes
    from ric.ioc.parser import parse_ioc
    from ric.matcher import match_changes
    from ric.report.excel import write_excel
    from ric.report.html import write_html

    # ---- Load requirements ----
    print("Loading requirements...")
    requirements = []
    for path in args.fri:
        print(f"  FRI: {path.name}", flush=True)
        requirements.extend(load_fri(path, paygroup=args.paygroup))
    for path in args.ri:
        print(f"  RI:  {path.name}", flush=True)
        requirements.extend(load_ri(path, paygroup=args.paygroup))
    print(f"  {len(requirements)} requirements loaded\n")

    # ---- Parse IOC ----
    print(f"Parsing IOC: {args.ioc.name} ...", flush=True)
    ioc = parse_ioc(args.ioc, model=args.model)
    print(f"  {len(ioc.changes)} changes extracted\n")

    # ---- Match ----
    print("Matching changes to requirements...")

    def _progress(i: int, total: int, change) -> None:
        label = change.summary[:60] + ("..." if len(change.summary) > 60 else "")
        print(f"  [{i}/{total}] {change.change_type.value}: {label}", flush=True)

    results = match_changes(ioc, requirements, model=args.model, on_progress=_progress)

    total_matches = sum(len(r.matched_requirements) for r in results)
    print(f"  {total_matches} requirement matches found\n")

    # ---- Flag (Stage 4) ----
    print("Flagging risks and clarifications…")

    def _flag_progress(i: int, total: int, change) -> None:
        print(f"  [{i}/{total}] flagging: {change.summary[:60]}", flush=True)

    results = flag_changes(ioc, results, model=args.model, on_progress=_flag_progress)
    total_flags = sum(len(getattr(r, "risk_flags", [])) for r in results)
    print(f"  {total_flags} flags identified\n")

    # ---- Write reports ----
    out = Path(args.output)
    excel_path = out.with_suffix(".xlsx")
    html_path = out.with_suffix(".html")

    write_excel(ioc, results, excel_path, requirements=requirements)
    print(f"Excel: {excel_path.resolve()}")

    write_html(ioc, results, html_path, requirements=requirements)
    print(f"HTML:  {html_path.resolve()}")
