"""Render results as JSON (for machines and agents) and Markdown (for people)."""

import json
from datetime import datetime, timezone

from .contract import ERROR_KINDS


def build(results: list) -> dict:
    checks = [c for s in results for t in s["tasks"] for c in t["checks"]]
    return {
        "suite": "agentmail-mcp-conformance (prototype, mock server)",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "summary": {"scenarios": len(results), "checks": len(checks),
                    "checks_passed": sum(c["passed"] for c in checks)},
        "error_kinds": ERROR_KINDS,
        "scoreboard": {s["scenario"]: {t["task"]: _cell(t) for t in s["tasks"]} for s in results},
        "scenarios": results,
    }


def _cell(task) -> str:
    if task["passed"]:
        return "PASS"
    kinds = sorted({c["kind"] for c in task["checks"] if not c["passed"]} - {"claim_mismatch", "contract_violation"})
    kinds = kinds or sorted({c["kind"] for c in task["checks"] if not c["passed"]})
    return "FAIL " + ",".join(kinds)


def scoreboard_text(report: dict) -> str:
    board = report["scoreboard"]
    tasks = list(next(iter(board.values())))
    rows = [["scenario"] + tasks] + [[s] + [board[s][t] for t in tasks] for s in board]
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]
    lines.insert(1, "  ".join("-" * w for w in widths))
    return "\n".join(lines)


def _link(call_id: str) -> str:
    return f"[{call_id}](#{call_id})"


def to_markdown(report: dict) -> str:
    s = report["summary"]
    out = [
        "# AgentMail MCP conformance report (prototype)",
        "",
        f"Generated {report['generated_at']} against the local mock server. "
        f"{s['checks_passed']}/{s['checks']} checks passed across {s['scenarios']} scenarios.",
        "Every check is judged against the mock store (server-side truth), not the agent's claim.",
        "",
        "## Scoreboard",
        "",
    ]
    board = report["scoreboard"]
    tasks = list(next(iter(board.values())))
    out += ["| scenario | " + " | ".join(tasks) + " |", "|---" * (len(tasks) + 1) + "|"]
    for name, row in board.items():
        out.append(f"| [{name}](#scenario-{name}) | " + " | ".join(
            "PASS" if v == "PASS" else f"**{v}**" for v in row.values()) + " |")

    out += ["", "## Error kinds (agent-readable contract)", "",
            "| kind | retryable | next_action | source issue | meaning |", "|---|---|---|---|---|"]
    for kind, k in report["error_kinds"].items():
        out.append(f"| `{kind}` | {k['retryable']} | `{k['next_action']}` | {k['issue'] or ''} | {k['meaning']} |")

    for sc in report["scenarios"]:
        out += ["", f'<a id="scenario-{sc["scenario"]}"></a>', "", f"## Scenario: {sc['scenario']}", "",
                sc["description"], "",
                f"Faults: `{', '.join(sc['faults']) or 'none'}`. Error contract: {'on' if sc['error_contract'] else 'off'}."
                + (f" Source: {sc['issue']}." if sc["issue"] else "")]
        for t in sc["tasks"]:
            out += ["", f"### {t['task']}: {'PASS' if t['passed'] else 'FAIL'}", "",
                    f"{t['title']}. Agent said: \"{t['agent_claim']['said']}\"", "",
                    "| check | result | error kind | next_action | detail | trace |", "|---|---|---|---|---|---|"]
            for c in t["checks"]:
                detail = c["detail"].replace("|", "\\|")
                out.append(f"| {c['name']} | {'pass' if c['passed'] else '**FAIL**'} | "
                           f"{'`' + c['kind'] + '`' if c['kind'] else ''} | "
                           f"{'`' + c['next_action'] + '`' if c['next_action'] else ''} | {detail} | "
                           f"{' '.join(_link(r) for r in c['trace_refs'])} |")
        out += ["", f"### Traces: {sc['scenario']}"]
        for call_id, e in sc["traces"].items():
            pair = {"request": e["request"], "response": e["response"]}
            extra = []
            if e["dropped_optional_args"]:
                extra.append(f"dropped optional args: `{e['dropped_optional_args']}`")
            if e["undeclared_args"]:
                extra.append(f"args not in schema: `{e['undeclared_args']}`")
            out += ["", f'<a id="{call_id}"></a>',
                    f"**{call_id}** `{e['tool']}` task={e['task']} t={e['t']}s source={e['source']}"
                    + ("; " + "; ".join(extra) if extra else ""), "",
                    "```json", json.dumps(pair, indent=2), "```"]
    return "\n".join(out) + "\n"
