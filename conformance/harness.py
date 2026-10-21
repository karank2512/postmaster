from mock_agentmail import FakeClock, InboxStore, MockAgentMailMCP, SimulatedModelClient

from .agent import ContractAwareAgent
from .scenarios import SCENARIOS, Scenario
from .tasks import default_tasks


def run_scenario(scenario: Scenario) -> dict:
    """Run every task against a fresh mock server and check the store, not the agent."""
    clock, store = FakeClock(), InboxStore()
    server = MockAgentMailMCP(store, clock, scenario.faults)
    client = SimulatedModelClient(server, scenario.faults, call_prefix=scenario.name)
    client.connect()
    agent = ContractAwareAgent(client, clock)

    tasks = default_tasks(server.token_ttl)
    seeds = {t.name: t.seed(store) for t in tasks}
    results = []
    for task in tasks:
        client.task = task.name
        claim = task.run(agent, seeds[task.name])
        exchanges = [e for e in client.exchanges if e["task"] == task.name]
        checks = task.checks(store, seeds[task.name], claim, exchanges)
        results.append({
            "task": task.name, "title": task.title, "issues": task.issues,
            "passed": all(c.passed for c in checks), "agent_claim": claim,
            "checks": [c.to_dict() for c in checks],
        })
    return {
        "scenario": scenario.name, "description": scenario.description, "issue": scenario.issue,
        "faults": scenario.faults.enabled(), "error_contract": scenario.faults.error_contract,
        "rejected_tools": client.rejected,
        "passed": all(r["passed"] for r in results), "tasks": results,
        "traces": {e["call_id"]: e for e in client.exchanges},
    }


def run_suite(scenarios=None) -> list:
    return [run_scenario(s) for s in (scenarios or SCENARIOS)]
