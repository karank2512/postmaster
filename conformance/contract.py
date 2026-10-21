"""The agent-readable error contract: every failure kind the suite can assign.

Each kind says whether retrying can help and where an agent (or engineer) should go next.
next_action paths are draft llms.txt anchors, not live pages.
"""

ERROR_KINDS = {
    "schema_rejected": {
        "retryable": False,
        "next_action": "/llms.txt#tool-schemas",
        "issue": "agentmail-mcp#8",
        "meaning": "The model client rejected the tool's input schema, so the tool was never called.",
    },
    "optional_args_dropped": {
        "retryable": False,
        "next_action": "/llms.txt#required-content-fields",
        "issue": "agentmail-mcp#18",
        "meaning": "Args the agent supplied never reached the server; the call still 'succeeded'.",
    },
    "token_expired_unrecoverable": {
        "retryable": False,
        "next_action": "/llms.txt#session-refresh",
        "issue": "agentmail-mcp#50",
        "meaning": "The access token expired and refresh failed; every later call returns 401.",
    },
    "inbox_not_ready": {
        "retryable": True,
        "next_action": "/llms.txt#inbox-not-ready",
        "issue": "agentmail-node#14",
        "meaning": "404 'Inbox not found' for an inbox the store says exists and was just created.",
    },
    "unauthenticated_hidden": {
        "retryable": False,
        "next_action": "/llms.txt#unauthenticated-inbound",
        "issue": "agentmail-mcp#38",
        "meaning": "Inbound mail is in the inbox, but MCP list/search never returned it.",
    },
    "claim_mismatch": {
        "retryable": False,
        "next_action": "/llms.txt#verify-delivery",
        "issue": None,
        "meaning": "What the agent reported does not match what happened on the server.",
    },
    "contract_violation": {
        "retryable": False,
        "next_action": "/llms.txt#error-contract",
        "issue": None,
        "meaning": "A server error lacked cause/next_action, or retry_after on a retryable cause.",
    },
    "unknown": {
        "retryable": False,
        "next_action": "/llms.txt#support",
        "issue": None,
        "meaning": "The check failed and no evidence in the trace matched a known kind.",
    },
}

# Server causes that must carry retry_after under the contract.
RETRYABLE_CAUSES = {"inbox_not_ready"}
