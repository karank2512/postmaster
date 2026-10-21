"""The fixed task set. Each task seeds the store, runs a scripted agent, then checks the store.

Truth checks only read InboxStore (what actually landed), never the agent's claim.
"""

import base64
import hashlib

from .checks import Check, check_schema_accepted, finalize, ids

SEEDED_AT = -3600.0  # seeded inboxes are an hour old, so they are always "ready"


def _result_error(r) -> str:
    return r["error"].get("message", "error")


def _delivered(store, inbox_ids, match, exchanges, tool, name="delivered_exactly_once"):
    found = [m for m in store.messages
             if m.inbox_id in inbox_ids and m.direction == "outbound" and match(m)]
    detail = f"{len(found)} matching outbound message(s) in the store" + (
        f" ({', '.join(m.message_id for m in found)})" if found else "")
    return found, Check(name, len(found) == 1, detail, ids(exchanges, tool))


def _content(found, exchanges, tool, **expected):
    if not found:
        return Check("content_intact", False, "nothing delivered, so no content to check", ids(exchanges, tool))
    m = found[0]
    observed = {k: getattr(m, k) for k in expected}
    ok = observed == expected
    detail = f"store has {observed}" + ("" if ok else f", agent sent {expected}")
    return Check("content_intact", ok, detail, ids(exchanges, tool))


class OnboardAndSend:
    name = "onboard_and_send"
    title = "Self sign-up: create an inbox and send right away"
    issues = ["agentmail-node#14", "agentmail-mcp#8", "agentmail-mcp#18"]
    TO, SUBJECT, TEXT = "founder@example.com", "Hello from your new agent", "My inbox is live."

    def seed(self, store):
        return {}

    def run(self, agent, seed):
        r = agent.call("create_inbox", {"username": "onboard-bot"})
        if r["isError"]:
            return {"success": False, "said": f"Could not create an inbox: {_result_error(r)}"}
        inbox_id = r["structuredContent"]["inbox_id"]
        r = agent.call("send_message", {"inbox_id": inbox_id, "to": [self.TO],
                                        "subject": self.SUBJECT, "text": self.TEXT})
        if r["isError"]:
            return {"success": False, "said": f"Inbox {inbox_id} does not exist ({_result_error(r)}); giving up."}
        return {"success": True, "said": f"Sent '{self.SUBJECT}' to {self.TO}."}

    def checks(self, store, seed, claim, ex):
        new_inboxes = {i.inbox_id for i in store.inboxes.values() if not i.seeded}
        found, delivered = _delivered(store, new_inboxes, lambda m: self.TO in m.to, ex, "send_message")
        content = _content(found, ex, "send_message", subject=self.SUBJECT, text=self.TEXT)
        return finalize([check_schema_accepted(ex), delivered, content], ex, store, claim)


class ReplyWithAttachment:
    name = "reply_with_attachment"
    title = "Find a customer email and reply with an attachment"
    issues = ["agentmail-mcp#8", "agentmail-mcp#18"]
    TEXT = "Attached is the corrected invoice."
    FILENAME, CONTENT = "invoice-1042.pdf", b"%PDF-1.4 sample corrected invoice 1042"

    def seed(self, store):
        inbox = store.create_inbox("support-bot", SEEDED_AT, seeded=True)
        msg = store.add_message(inbox.inbox_id, "inbound", "customer@example.com", [inbox.address],
                                "Invoice #1042 is wrong", "The total is off by $40.", SEEDED_AT,
                                labels=["received"])
        return {"inbox_id": inbox.inbox_id, "target_id": msg.message_id}

    def run(self, agent, seed):
        r = agent.call("list_messages", {"inbox_id": seed["inbox_id"], "limit": 10})
        if r["isError"]:
            return {"success": False, "said": f"Could not read the inbox: {_result_error(r)}"}
        target = next((m for m in r["structuredContent"]["messages"] if "Invoice" in m["subject"]), None)
        if target is None:
            return {"success": False, "said": "No invoice email found."}
        r = agent.call("reply_to_message", {
            "inbox_id": seed["inbox_id"], "message_id": target["message_id"], "text": self.TEXT,
            "attachments": [{"filename": self.FILENAME,
                             "content_base64": base64.b64encode(self.CONTENT).decode()}]})
        if r["isError"]:
            return {"success": False, "said": f"Reply failed: {_result_error(r)}"}
        return {"success": True, "said": f"Replied to {target['from']} with {self.FILENAME} attached."}

    def checks(self, store, seed, claim, ex):
        found, delivered = _delivered(store, {seed["inbox_id"]},
                                      lambda m: m.in_reply_to == seed["target_id"], ex,
                                      "reply_to_message", name="reply_delivered_exactly_once")
        content = _content(found, ex, "reply_to_message", text=self.TEXT)
        want = {"filename": self.FILENAME, "sha256": hashlib.sha256(self.CONTENT).hexdigest(),
                "size": len(self.CONTENT)}
        got = found[0].attachments if found else []
        attach = Check("attachment_intact", got == [want],
                       f"store has attachments {got}" if got else "no attachment in the store",
                       ids(ex, "reply_to_message"))
        return finalize([check_schema_accepted(ex), delivered, content, attach], ex, store, claim)


class FindUnauthenticatedInbound:
    name = "find_unauthenticated_inbound"
    title = "Find a client reply that failed SPF/DKIM"
    issues = ["agentmail-mcp#38"]
    CLIENT = "client@customer.example"

    def seed(self, store):
        inbox = store.create_inbox("sales-bot", SEEDED_AT, seeded=True)
        store.add_message(inbox.inbox_id, "inbound", "news@example.com", [inbox.address],
                          "Weekly newsletter", "Nothing to see.", SEEDED_AT, labels=["received"])
        msg = store.add_message(inbox.inbox_id, "inbound", self.CLIENT, [inbox.address],
                                "Re: Proposal for Q4", "Looks good, let's sign.", SEEDED_AT,
                                labels=["received", "unauthenticated"])
        return {"inbox_id": inbox.inbox_id, "target_id": msg.message_id}

    def run(self, agent, seed):
        r = agent.call("search_messages", {"inbox_id": seed["inbox_id"], "query": self.CLIENT,
                                           "include_unauthenticated": True})
        if r["isError"]:
            return {"success": False, "said": f"Search failed: {_result_error(r)}"}
        hits = r["structuredContent"]["messages"]
        if not hits:
            # The confident wrong answer an agent gives when the tool hides the mail.
            return {"success": True, "said": f"{self.CLIENT} has not replied yet.", "found_message_id": None}
        return {"success": True, "said": f"Found the reply: {hits[0]['subject']}",
                "found_message_id": hits[0]["message_id"]}

    def checks(self, store, seed, claim, ex):
        target = store.get_message(seed["target_id"])
        returned = [e for e in ex if not e["response"]["isError"]
                    and any(m["message_id"] == target.message_id
                            for m in e["response"]["structuredContent"].get("messages", []))]
        visible = Check("inbound_visible_via_mcp", bool(returned),
                        f"store has {target.message_id} labelled {target.labels}; "
                        f"returned by {len(returned)} MCP call(s)", ids(ex))
        if not returned:
            dropped = [e for e in ex if "include_unauthenticated" in e["dropped_optional_args"]]
            if dropped:
                visible.fail_as("optional_args_dropped", ids(dropped))
            elif not any(e["source"] == "client" for e in ex):
                visible.fail_as("unauthenticated_hidden")
        found = Check("agent_found_message", claim.get("found_message_id") == target.message_id,
                      f"agent found {claim.get('found_message_id')}, truth is {target.message_id}", ids(ex))
        if not found.passed:
            found.fail_as(visible.kind or "unknown")
        return finalize([check_schema_accepted(ex), visible, found], ex, store, claim)


class SurviveTokenRefresh:
    name = "survive_token_refresh"
    title = "Idle past token expiry, then keep working"
    issues = ["agentmail-mcp#50"]
    TO, SUBJECT, TEXT = "oncall@example.com", "Nightly report", "All systems normal."

    def __init__(self, token_ttl: float):
        self.idle_for = token_ttl + 60

    def seed(self, store):
        inbox = store.create_inbox("ops-bot", SEEDED_AT, seeded=True)
        return {"inbox_id": inbox.inbox_id}

    def run(self, agent, seed):
        agent.call("list_messages", {"inbox_id": seed["inbox_id"]})
        agent.idle(self.idle_for)  # overnight, no human watching
        seed["resumed_at"] = agent.clock.now()
        r = agent.call("list_messages", {"inbox_id": seed["inbox_id"]})
        if r["isError"]:
            return {"success": False, "said": f"Session lost: {_result_error(r)}"}
        r = agent.call("send_message", {"inbox_id": seed["inbox_id"], "to": [self.TO],
                                        "subject": self.SUBJECT, "text": self.TEXT})
        if r["isError"]:
            return {"success": False, "said": f"Send failed: {_result_error(r)}"}
        return {"success": True, "said": f"Session survived; sent '{self.SUBJECT}'."}

    def checks(self, store, seed, claim, ex):
        after = [e for e in ex if e["t"] >= seed["resumed_at"] and e["source"] == "server"]
        ok = [e for e in after if e["tool"] == "list_messages" and not e["response"]["isError"]]
        session = Check("session_recovered", bool(ok),
                        f"{len(ok)} successful call(s) after the token expired", ids(after))
        found, delivered = _delivered(store, {seed["inbox_id"]}, lambda m: self.TO in m.to, ex, "send_message")
        content = _content(found, ex, "send_message", subject=self.SUBJECT, text=self.TEXT)
        return finalize([check_schema_accepted(ex), session, delivered, content], ex, store, claim)


def default_tasks(token_ttl: float) -> list:
    return [OnboardAndSend(), ReplyWithAttachment(), FindUnauthenticatedInbound(), SurviveTokenRefresh(token_ttl)]
