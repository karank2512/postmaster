"""Mock AgentMail MCP server speaking JSON-RPC 2.0 in-process.

Methods: auth/login, auth/refresh, tools/list, tools/call.
Tool names and argument shapes follow the open-source agentmail-mcp repo loosely;
this is a demo stand-in, not a faithful port.
"""

from .faults import Faults
from .store import InboxStore

# The draft error contract: every cause maps to an action an agent can take.
# Paths are draft anchors for a future llms.txt section, not live pages.
NEXT_ACTIONS = {
    "inbox_not_ready": "/llms.txt#inbox-not-ready",
    "inbox_not_found": "/llms.txt#inbox-not-found",
    "message_not_found": "/llms.txt#message-not-found",
    "token_expired": "auth/refresh",
    "invalid_token": "auth/login",
    "session_unrecoverable": "/llms.txt#session-refresh",
    "invalid_arguments": "tools/list",
}


class ToolError(Exception):
    def __init__(self, status, message, cause, retry_after=None):
        super().__init__(message)
        self.status, self.message, self.cause, self.retry_after = status, message, cause, retry_after


class MockAgentMailMCP:
    def __init__(self, store: InboxStore, clock, faults: Faults = None, token_ttl: float = 300.0):
        self.store = store
        self.clock = clock
        self.faults = faults or Faults()
        self.token_ttl = token_ttl
        self.tokens = {}  # access_token -> expires_at
        self.refresh_tokens = set()
        self._n = 0
        self.tools = {
            "create_inbox": self._create_inbox,
            "send_message": self._send_message,
            "reply_to_message": self._reply_to_message,
            "list_messages": self._list_messages,
            "search_messages": self._search_messages,
        }

    # ---- JSON-RPC entry point -------------------------------------------------

    def handle(self, request: dict) -> dict:
        method, params = request["method"], request.get("params", {})
        if method == "auth/login":
            result = self._ok(self._issue_token())
        elif method == "auth/refresh":
            result = self._refresh(params)
        elif method == "tools/list":
            result = {"tools": self.tool_schemas()}
        elif method == "tools/call":
            result = self._call(params)
        else:
            return {"jsonrpc": "2.0", "id": request["id"],
                    "error": {"code": -32601, "message": f"Method not found: {method}"}}
        return {"jsonrpc": "2.0", "id": request["id"], "result": result}

    def _ok(self, data):
        return {"isError": False, "structuredContent": data}

    def _err(self, e: ToolError):
        error = {"status": e.status, "message": e.message}
        if self.faults.error_contract:
            error["cause"] = e.cause
            error["next_action"] = NEXT_ACTIONS[e.cause]
            if e.retry_after is not None:
                error["retry_after"] = e.retry_after
        return {"isError": True, "error": error}

    # ---- auth -----------------------------------------------------------------

    def _issue_token(self):
        self._n += 1
        access, refresh = f"at_{self._n}", f"rt_{self._n}"
        expires_at = self.clock.now() + self.token_ttl
        self.tokens[access] = expires_at
        self.refresh_tokens.add(refresh)
        return {"access_token": access, "refresh_token": refresh, "expires_at": expires_at}

    def _refresh(self, params):
        if self.faults.token_no_recovery:
            return self._err(ToolError(401, "Unauthorized", "session_unrecoverable"))
        if params.get("refresh_token") not in self.refresh_tokens:
            return self._err(ToolError(401, "Unauthorized", "invalid_token"))
        self.refresh_tokens.discard(params["refresh_token"])
        return self._ok(self._issue_token())

    def _check_auth(self, token):
        expires_at = self.tokens.get(token)
        if expires_at is None:
            raise ToolError(401, "Unauthorized", "invalid_token")
        if self.clock.now() >= expires_at:
            raise ToolError(401, "Unauthorized", "token_expired")

    # ---- tools ----------------------------------------------------------------

    def tool_schemas(self) -> list:
        recipients = {"type": "array", "items": {"type": "string"}}
        if self.faults.schema_rejection:
            # A union type: valid JSON Schema, but rejected by strict function-calling dialects.
            recipients = {"anyOf": [{"type": "string"}, recipients]}
        attachments = {"type": "array", "items": {
            "type": "object",
            "properties": {"filename": {"type": "string"}, "content_base64": {"type": "string"}},
            "required": ["filename", "content_base64"],
        }}
        unauth = {} if self.faults.hide_unauthenticated else {
            "include_unauthenticated": {"type": "boolean",
                                        "description": "Include inbound mail that failed SPF/DKIM."}}

        def tool(name, desc, props, required):
            return {"name": name, "description": desc, "inputSchema": {
                "type": "object", "properties": props, "required": required}}

        s = {"type": "string"}
        return [
            tool("create_inbox", "Create a new inbox.", {"username": s}, []),
            tool("send_message", "Send an email from an inbox.",
                 {"inbox_id": s, "to": recipients, "subject": s, "text": s, "attachments": attachments},
                 ["inbox_id", "to"]),
            tool("reply_to_message", "Reply to a message.",
                 {"inbox_id": s, "message_id": s, "text": s, "cc": recipients, "attachments": attachments},
                 ["inbox_id", "message_id"]),
            tool("list_messages", "List messages in an inbox.",
                 {"inbox_id": s, "limit": {"type": "integer"}, **unauth}, ["inbox_id"]),
            tool("search_messages", "Search messages by sender, subject, or text.",
                 {"inbox_id": s, "query": s, **unauth}, ["inbox_id", "query"]),
        ]

    def _call(self, params):
        try:
            self._check_auth(params.get("auth"))
            name, args = params["name"], params.get("arguments", {})
            schema = next((t["inputSchema"] for t in self.tool_schemas() if t["name"] == name), None)
            if schema is None:
                raise ToolError(400, f"Unknown tool {name}", "invalid_arguments")
            missing = [k for k in schema["required"] if k not in args]
            unknown = [k for k in args if k not in schema["properties"]]
            if missing or unknown:
                raise ToolError(400, f"Invalid arguments: missing={missing} unknown={unknown}",
                                "invalid_arguments")
            return self._ok(self.tools[name](args))
        except ToolError as e:
            return self._err(e)

    def _inbox(self, inbox_id):
        inbox = self.store.inboxes.get(inbox_id)
        if inbox is None:
            raise ToolError(404, "Inbox not found", "inbox_not_found")
        age = self.clock.now() - inbox.created_at
        if self.faults.inbox_not_ready_404 and age < self.faults.inbox_ready_delay:
            # Same message the real API returns, which reads as "this inbox does not exist".
            raise ToolError(404, "Inbox not found", "inbox_not_ready",
                            retry_after=round(self.faults.inbox_ready_delay - age, 2))
        return inbox

    def _create_inbox(self, args):
        inbox = self.store.create_inbox(args.get("username"), self.clock.now())
        return {"inbox_id": inbox.inbox_id, "address": inbox.address}

    def _attachments(self, args):
        return [InboxStore.attachment_record(a["filename"], a["content_base64"])
                for a in args.get("attachments", [])]

    def _send_message(self, args):
        inbox = self._inbox(args["inbox_id"])
        to = args["to"] if isinstance(args["to"], list) else [args["to"]]
        # Like the real server, a missing subject/body is accepted and a blank email goes out.
        msg = self.store.add_message(inbox.inbox_id, "outbound", inbox.address, to,
                                     args.get("subject"), args.get("text"), self.clock.now(),
                                     labels=["sent"], attachments=self._attachments(args))
        return {"message_id": msg.message_id, "status": "sent"}

    def _reply_to_message(self, args):
        inbox = self._inbox(args["inbox_id"])
        original = self.store.get_message(args["message_id"])
        if original is None or original.inbox_id != inbox.inbox_id:
            raise ToolError(404, "Message not found", "message_not_found")
        msg = self.store.add_message(inbox.inbox_id, "outbound", inbox.address,
                                     [original.sender] + list(args.get("cc", [])),
                                     f"Re: {original.subject}", args.get("text"), self.clock.now(),
                                     labels=["sent"], attachments=self._attachments(args),
                                     in_reply_to=original.message_id)
        return {"message_id": msg.message_id, "status": "sent"}

    def _visible(self, inbox_id, args):
        include = args.get("include_unauthenticated", False) and not self.faults.hide_unauthenticated
        return [m for m in self.store.messages_in(inbox_id) if include or not m.unauthenticated]

    @staticmethod
    def _summary(m):
        return {"message_id": m.message_id, "from": m.sender, "to": m.to, "subject": m.subject,
                "labels": m.labels, "preview": m.text[:80]}

    def _list_messages(self, args):
        inbox = self._inbox(args["inbox_id"])
        msgs = self._visible(inbox.inbox_id, args)[: args.get("limit", 50)]
        return {"messages": [self._summary(m) for m in msgs]}

    def _search_messages(self, args):
        inbox = self._inbox(args["inbox_id"])
        q = args["query"].lower()
        hits = [m for m in self._visible(inbox.inbox_id, args)
                if q in m.sender.lower() or q in m.subject.lower() or q in m.text.lower()]
        return {"messages": [self._summary(m) for m in hits]}
