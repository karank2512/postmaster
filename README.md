# AgentMail: feature proposal

- **Company:** AgentMail (YC), email inboxes and identity for AI agents
- **Role:** Agent Experience Engineer, San Francisco ($110K to $175K, 0.2% to 0.5% equity per posting)
- **Posting:** https://jobs.ashbyhq.com/agentmail/3918f5f4-8246-4c65-bf63-8a77798a03cf
- **Date researched:** 2026-10-21

The posting says AgentMail's most important user is an agent, and asks for evals and benchmarks of how models and harnesses use AgentMail, agent traces, MCP descriptions, and "the error messages agents hit at 3am with no human watching." The public pains below are mostly that exact surface.

## Pain points (public sources)

- **One MCP tool schema behaves differently across models, sometimes silently.**
  - Gemini's function calling rejected the send, reply and forward tool schemas. A user posted a proxy workaround. [agentmail-mcp#8](https://github.com/agentmail-to/agentmail-mcp/issues/8) (2026-02-28)
  - With Grok, optional subject and body args were dropped, which "turns a model quirk into silently-delivered blank emails" and "the agent has no way to know the content was lost." [agentmail-mcp#18](https://github.com/agentmail-to/agentmail-mcp/issues/18) (2026-07-04)
  - Claude Code rejected tool results with "Invalid input: expected record, received string." The reporter fell back to the REST API. [agentmail-mcp#5](https://github.com/agentmail-to/agentmail-mcp/issues/5) (2026-02-02)
- **The MCP server fails without saying why.**
  - `npx -y agentmail-mcp` exited with no output and no error, so clients only reported "failed to connect" (fixed in #28). [agentmail-mcp#24](https://github.com/agentmail-to/agentmail-mcp/issues/24) (2026-07-15)
  - On the hosted server, the sign-in token doesn't refresh. Tools start returning 401, and "the session is never recovered without a full manual re-authentication." Still open. [agentmail-mcp#50](https://github.com/agentmail-to/agentmail-mcp/issues/50) (2026-08-22)
- **The MCP tools can do less than the REST API.** A client reply labelled `unauthenticated` was invisible to list and search over MCP. The REST API has `include_unauthenticated`, but the MCP tool doesn't expose it: "Legitimate inbound mail is unreachable through the MCP server." Still open. [agentmail-mcp#38](https://github.com/agentmail-to/agentmail-mcp/issues/38) (2026-07-30)
- **Errors that send an agent the wrong way.** Sending right after creating an inbox returns 404 "Inbox not found" for about 1 to 2 seconds. The reporter's workaround is "Adding a ~2 second delay." An agent reading that 404 would conclude the inbox doesn't exist. Still open. [agentmail-node#14](https://github.com/agentmail-to/agentmail-node/issues/14) (2026-04-05)
- **Docs drift from the API.** The webhook example fails because the API requires an `event_types` "field that is not documented or provided in the example." [agentmail-examples#3](https://github.com/agentmail-to/agentmail-examples/issues/3) (2025-09-28)
- **Agents that sign themselves up have no support path.** An inbox created through the agent sign-up flow hits an SMTP 450 rejection, and with no console login there is no private way to diagnose it. [agentmail-docs#312](https://github.com/agentmail-to/agentmail-docs/issues/312) (2026-10-13)

## Proposed feature: a public cross-model MCP conformance suite with an agent-readable error contract

**What it is:** a nightly harness that runs real agent tasks through the AgentMail MCP server and SDKs against a sandbox inbox. It covers Claude, GPT, Gemini, Grok and a few open-source models, in a few harnesses (Claude Code, a plain function-calling loop, an MCP client).

- **Tasks:** onboarding (self sign-up, create inbox, send right away), send, reply and forward with attachments, finding an unauthenticated inbound message, and surviving a token refresh.
- **Checks:** each run is checked against what actually happened on the server, not what the agent claims. Did the email arrive with a non-empty subject and body? Was the schema accepted? Did the session recover?
- **Trace links:** every failure links to the trace and the exact tool call ID, so a fix is one click from the evidence.
- **Error contract (ships with the suite):**
  - Every error an agent can hit (404 on a fresh inbox, 401 after expiry, 403 suspension, SMTP 450) returns a machine-readable `cause`, a `retry_after` where it applies, and a `next_action` URL into llms.txt or the docs.
  - The suite asserts that contract on every run, so it can't drift.
- **Published scoreboard:** results go on a public pass-rate table by model and harness. This is the "original research" and benchmark material the posting asks for, and it gives answer engines a citable, current source.

**Why this one:**
- The six pains above are all cases where an agent hit a failure no human saw, and each was found by a user filing an issue.
- Issues #8, #18 and #5 are one bug class (schema compatibility across models), found one model at a time.
- A conformance suite would catch the next one before a user does, and it turns the agent-experience work into a number the team can move week to week.

## How Karan would build it (claims mapped to his work)

- **Scoring every run several ways, with traces tied to tool call IDs:**
  - **From:** Foreman, Karan's open-source agent platform. Its evals score every LLM output 3 ways, and its approve/deny traces are tied to tool call IDs. It is a fully tested MVP in simulated mode, with no customers yet.
  - **Here:** the same pattern, pointed at MCP tool calls. Check the schema was accepted, check the server-side outcome, and check the agent's own understanding of what happened.
- **Reliable scheduled collection:**
  - **From:** tell, which Karan built solo. Six idempotent collectors track 907 companies and 10,585 open postings at 97.8% run success over 321 runs.
  - **Here:** a nightly multi-model suite needs the same idempotent, retry-safe runs, so a flaky night doesn't send duplicate emails or false alarms.
- **Every number links to its evidence:**
  - **From:** in tell, every score links to its public-record receipt (open source at github.com/karank2512/tell-ai).
  - **Here:** every scoreboard cell links to the trace behind it, which is what makes a published benchmark citable.
- **Exactly-once side effects, and holding uncertain actions for a human:**
  - **From:** RelayIQ, which does exactly-once HubSpot writes and holds low-confidence writes back for a human. It went from 68% to 77% accuracy on a 495-case seeded benchmark.
  - **Here:** the same ideas drive the suite's sandbox sends (no duplicate mail on retry). They also suggest a guard that refuses to send an empty email instead of delivering it, which is the #18 failure.
- **Measuring against a golden set in production:**
  - **From:** Karan's retrieval assistant at UW-Madison IT, used daily by 60+ staff. It cut manual lookup time 40% and was evaluated against a golden set.
  - **Here:** that is the same discipline as checking whether models answer "how do I give my agent an email?" correctly from AgentMail's docs chunks.

## Rough demo plan (a few days, no paid services)

1. **Day 1:** stand up a local mock of the MCP tools from the open-source [agentmail-mcp](https://github.com/agentmail-to/agentmail-mcp) repo. Reproduce two known bug classes as test cases: optional args dropped (#18) and 404 right after create (agentmail-node #14).
2. **Day 2:** run the same 5 tasks through 2 or 3 local open-source models plus any API keys Karan already has. Record each tool call with its ID, and score each run 3 ways: schema accepted, server-side outcome, agent's self-report.
3. **Day 3:** generate a static scoreboard (model by task pass rate). Every failed cell opens its trace. Add a draft error contract (`cause`, `retry_after`, `next_action`) and show that one agent recovers from the fresh-inbox 404 with it and fails without it.
4. **Optional:** run it against the real API on the free tier, only if Karan chooses to sign up himself.

## LinkedIn note (under 300 characters)

> Hi! 321 runs at 97.8% success on my tell pipeline. I'd point that rigor at AgentMail: a nightly cross-model MCP eval, every failure tied to a tool call ID, catching bugs like Grok's blank sends and Gemini's rejected schemas. Chat? Karan
