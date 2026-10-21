# Prototype: AgentMail cross-model MCP conformance suite

This is a small, runnable version of the feature proposed in [README.md](README.md). It runs a fixed set of agent tasks against a **local mock** of the AgentMail MCP server. Each run is checked against what actually landed in the mock's inbox store, not against what the agent says it did. Every failure links to the exact tool call, with its request and response.

Everything is simulated. There is no AgentMail account, no API key, and no network traffic at all (the server is in-process). You only need Python 3 and pytest.

## Run the demo (about 2 minutes)

```bash
python3 -m conformance run          # all 7 scenarios, writes reports/conformance.{json,md}
open reports/conformance.md         # or view it in any Markdown viewer
```

Other options:

```bash
python3 -m conformance run --scenario healthy --scenario drop_optional_args
python3 -m conformance run --faults drop_optional_args,hide_unauthenticated --no-contract
python3 -m conformance run --fail-on-error   # exit 1 if any check fails, for CI
```

Run the tests:

```bash
python3 -m venv .venv && .venv/bin/pip install pytest
.venv/bin/python -m pytest -q
```

## Sample output

```
scenario                           onboard_and_send            reply_with_attachment       find_unauthenticated_inbound  survive_token_refresh
---------------------------------  --------------------------  --------------------------  ----------------------------  --------------------------------
healthy                            PASS                        PASS                        PASS                          PASS
schema_rejection                   FAIL schema_rejected        FAIL schema_rejected        PASS                          FAIL schema_rejected
drop_optional_args                 FAIL optional_args_dropped  FAIL optional_args_dropped  FAIL optional_args_dropped    FAIL optional_args_dropped
token_no_recovery                  PASS                        PASS                        PASS                          FAIL token_expired_unrecoverable
inbox_not_ready_404                FAIL inbox_not_ready        PASS                        PASS                          PASS
inbox_not_ready_404_with_contract  PASS                        PASS                        PASS                          PASS
hide_unauthenticated               PASS                        PASS                        FAIL unauthenticated_hidden   PASS

124/154 checks passed across 7 scenario(s).
  drop_optional_args/onboard_and_send/content_intact: optional_args_dropped (retryable=False, next_action=/llms.txt#required-content-fields) trace=drop_optional_args-001,drop_optional_args-002
  drop_optional_args/onboard_and_send/agent_claim_matches_truth: claim_mismatch (retryable=False, next_action=/llms.txt#verify-delivery) trace=drop_optional_args-001,drop_optional_args-002
  ...
```

Read the table like this:

- **healthy** passes everything. The checks don't flag a correct server.
- Each fault breaks only the tasks it should. The one exception is `drop_optional_args`, which hits every task because every task sends optional args.
- **inbox_not_ready_404** vs **inbox_not_ready_404_with_contract**: the server bug is the same in both. In the first, the agent gets a bare `404 Inbox not found`, concludes the inbox doesn't exist, and gives up. In the second, the error carries the contract fields, so the agent waits and succeeds:

```json
{"status": 404, "message": "Inbox not found",
 "cause": "inbox_not_ready", "next_action": "/llms.txt#inbox-not-ready", "retry_after": 1.5}
```

In `reports/conformance.md`, every check row has a trace column of links such as `[drop_optional_args-002](#drop_optional_args-002)`. Each link jumps to the full JSON-RPC request and response for that tool call. The trace also shows what the client did to the args, for example `dropped optional args: ['subject', 'text']`.

## Layout

```
mock_agentmail/
  store.py     InboxStore: server-side truth (inboxes, messages, attachments with sha256)
  server.py    MockAgentMailMCP: JSON-RPC (auth/login, auth/refresh, tools/list, tools/call)
  client.py    SimulatedModelClient: strict-schema validation, arg dropping, 401 refresh, call ids + traces
  faults.py    Faults: one flag per failure mode, plus error_contract on/off
  clock.py     FakeClock: "wait 1.5s" and "idle overnight" cost nothing
conformance/
  tasks.py     the 4 tasks: scripted agent behavior + truth checks for each
  checks.py    shared checks and trace-based classification into error kinds
  contract.py  ERROR_KINDS: the agent-readable error contract (retryable, next_action, issue)
  agent.py     ContractAwareAgent: retries only when an error carries retry_after
  scenarios.py the 7 built-in scenarios
  harness.py   runs a scenario on a fresh mock and collects checks + traces
  report.py    JSON + Markdown rendering
tests/         pytest: mock fault reproduction and harness detection
```

## Failure modes reproduced

| Flag | Source issue | How the mock reproduces it | Detected as |
|---|---|---|---|
| `schema_rejection` | agentmail-mcp#8 | `send_message.to` and `reply_to_message.cc` use `anyOf`; the strict client rejects those tool declarations | `schema_rejected` |
| `drop_optional_args` | agentmail-mcp#18 | the client sends only required args; the server accepts the blank email and returns success | `optional_args_dropped`, plus `claim_mismatch` because the agent believes it worked |
| `token_no_recovery` | agentmail-mcp#50 | `auth/refresh` returns 401, so every call after expiry fails | `token_expired_unrecoverable` |
| `inbox_not_ready_404` | agentmail-node#14 | `404 Inbox not found` for 1.5s after `create_inbox` | `inbox_not_ready` (the store has the inbox, and it was created under 5s before the 404) |
| `hide_unauthenticated` | agentmail-mcp#38 | `include_unauthenticated` is missing from the MCP schemas, and list/search filter out unauthenticated mail | `unauthenticated_hidden`, plus `claim_mismatch` ("client has not replied yet") |

`error_contract` is not a fault. It is the proposed fix: when it is on, every server error carries `cause`, `next_action`, and `retry_after` where it applies. The fault scenarios run with it off, which matches what the real errors look like today. The `errors_follow_contract` check flags every server error the agent had to act on that lacks those fields. A 401 that the client fixed quietly by refreshing never reaches the agent, so that check skips it.

## Tasks and checks

Every task gets the same three checks: `schema_accepted`, `agent_claim_matches_truth`, and `errors_follow_contract`. The task-specific checks below read only the store:

| Task | Truth checks |
|---|---|
| `onboard_and_send` | `delivered_exactly_once` from the new inbox; `content_intact` (subject and text match what the agent sent) |
| `reply_with_attachment` | `reply_delivered_exactly_once` (threaded via `in_reply_to`); `content_intact`; `attachment_intact` (filename + sha256 + size) |
| `find_unauthenticated_inbound` | `inbound_visible_via_mcp` (the seeded unauthenticated message appears in some tool response); `agent_found_message` |
| `survive_token_refresh` | `session_recovered` (a call after expiry succeeded); `delivered_exactly_once`; `content_intact` |

Failed checks are classified from trace evidence, from most specific to least: a client-side schema rejection, then a failed refresh, then a 404 on an inbox the store says exists, then dropped args. If nothing matches, the kind is `unknown`. The full list of kinds, with `retryable` and `next_action`, is in `conformance/contract.py` and in the report.

## How this maps to the proposal

| Proposal | Prototype |
|---|---|
| Real agent tasks: onboarding, send, reply with attachments, unauthenticated inbound, token refresh | `conformance/tasks.py`, 4 tasks (forward is not built yet) |
| Checked against what happened on the server, not what the agent claims | truth checks read `InboxStore` only; `agent_claim_matches_truth` compares the two |
| Every failure links to the trace and tool call id | `trace_refs` on every check, with anchors to request/response pairs in the Markdown |
| Error contract: `cause`, `retry_after`, `next_action`, asserted on every run | `Faults.error_contract` on the server; `errors_follow_contract` check; `ERROR_KINDS` registry |
| Show an agent recovering from the fresh-inbox 404 with the contract and failing without it | `inbox_not_ready_404` vs `inbox_not_ready_404_with_contract` |
| Cross-model, published scoreboard | the scoreboard is scenario by task; model differences are simulated as client faults (strict schema dialect, arg dropping) |

## What is simulated, and what comes next

- The "agent" is scripted, not an LLM. It plays a careful agent: it trusts tool results and retries only when told how long to wait. Next step: swap in real model clients (local open-source models first) behind the same `call(tool, args)` interface, and turn scenarios into model × harness rows.
- The model quirks are flags on one simulated client. With real models, they would be observed behavior. The checks and classification stay the same.
- The `next_action` paths are draft `llms.txt` anchors, not live pages.
- Next tasks: forward, webhooks with `event_types` (agentmail-examples#3), SMTP 450 on self-signed-up inboxes (agentmail-docs#312), and idempotency keys so a retried send never duplicates mail.
