from dataclasses import dataclass

from mock_agentmail import Faults


@dataclass
class Scenario:
    name: str
    description: str
    faults: Faults
    issue: str = None


# Fault scenarios run with the error contract OFF, which mirrors today's errors.
SCENARIOS = [
    Scenario("healthy", "All faults off, error contract on. Every check should pass.", Faults()),
    Scenario("schema_rejection", "Send/reply schemas use a union type a strict model client rejects.",
             Faults(schema_rejection=True, error_contract=False), "agentmail-mcp#8"),
    Scenario("drop_optional_args", "The model client silently drops optional args (subject, text, attachments).",
             Faults(drop_optional_args=True, error_contract=False), "agentmail-mcp#18"),
    Scenario("token_no_recovery", "The access token expires and refresh never recovers the session.",
             Faults(token_no_recovery=True, error_contract=False), "agentmail-mcp#50"),
    Scenario("inbox_not_ready_404", "A new inbox returns 404 'Inbox not found' for 1.5s after creation.",
             Faults(inbox_not_ready_404=True, error_contract=False), "agentmail-node#14"),
    Scenario("inbox_not_ready_404_with_contract",
             "Same 404 fault, but errors carry cause/retry_after/next_action. The agent waits and recovers.",
             Faults(inbox_not_ready_404=True, error_contract=True), "agentmail-node#14"),
    Scenario("hide_unauthenticated", "Inbound mail labelled unauthenticated is invisible to MCP list/search.",
             Faults(hide_unauthenticated=True, error_contract=False), "agentmail-mcp#38"),
]
