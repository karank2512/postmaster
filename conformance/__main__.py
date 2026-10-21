import argparse
import json
import sys
from pathlib import Path

from mock_agentmail import FAULT_NAMES, Faults

from . import report
from .harness import run_suite
from .scenarios import SCENARIOS, Scenario


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m conformance",
                                description="AgentMail MCP conformance suite (mock prototype)")
    sub = p.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run scenarios and write JSON + Markdown reports")
    run.add_argument("--scenario", action="append", choices=[s.name for s in SCENARIOS],
                     help="run only these built-in scenarios (repeatable)")
    run.add_argument("--faults", help=f"custom run with comma-separated faults from {', '.join(FAULT_NAMES)}")
    run.add_argument("--no-contract", action="store_true", help="custom run: turn the error contract off")
    run.add_argument("--out", default="reports", help="output directory (default: reports)")
    run.add_argument("--fail-on-error", action="store_true", help="exit 1 if any check fails (for CI)")
    args = p.parse_args(argv)

    if args.faults is not None:
        names = [n.strip() for n in args.faults.split(",") if n.strip()]
        scenarios = [Scenario("custom", f"Custom run: {', '.join(names) or 'no faults'}",
                              Faults.from_names(names, error_contract=not args.no_contract))]
    else:
        scenarios = [s for s in SCENARIOS if not args.scenario or s.name in args.scenario]

    rep = report.build(run_suite(scenarios))
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "conformance.json").write_text(json.dumps(rep, indent=2))
    (out / "conformance.md").write_text(report.to_markdown(rep))

    s = rep["summary"]
    print(report.scoreboard_text(rep))
    print(f"\n{s['checks_passed']}/{s['checks']} checks passed across {s['scenarios']} scenario(s).")
    for sc in rep["scenarios"]:
        for t in sc["tasks"]:
            for c in t["checks"]:
                if not c["passed"]:
                    print(f"  {sc['scenario']}/{t['task']}/{c['name']}: {c['kind']} "
                          f"(retryable={c['retryable']}, next_action={c['next_action']}) "
                          f"trace={','.join(c['trace_refs'])}")
    print(f"\nReports: {out / 'conformance.json'}  {out / 'conformance.md'}")
    if args.fail_on_error and s["checks_passed"] != s["checks"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
