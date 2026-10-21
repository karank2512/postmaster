"""A simulated model client: the piece between an agent and the MCP server.

It plays the role a model plus its harness plays in real life:
- validates tool schemas against a strict function-calling dialect (like Gemini in agentmail-mcp#8)
- can only send args the schema declares (a model cannot call with undeclared params)
- with drop_optional_args, silently drops optional args (like Grok in agentmail-mcp#18)
- on a 401, tries auth/refresh once and retries the call

Every exchange is recorded with a tool call id so failures can link to evidence.
"""

from .faults import Faults

STRICT_FORBIDDEN_KEYS = ("anyOf", "oneOf", "allOf")


def strict_schema_problem(schema, path="$"):
    """Return why a strict function-calling dialect would reject this schema, or None."""
    if isinstance(schema, dict):
        for key in STRICT_FORBIDDEN_KEYS:
            if key in schema:
                return f"unsupported keyword '{key}' at {path}"
        if isinstance(schema.get("type"), list):
            return f"union 'type' list at {path}"
        for key, sub in schema.get("properties", {}).items():
            problem = strict_schema_problem(sub, f"{path}.{key}")
            if problem:
                return problem
        if "items" in schema:
            return strict_schema_problem(schema["items"], f"{path}[]")
    return None


class SimulatedModelClient:
    def __init__(self, server, faults: Faults = None, call_prefix: str = "call"):
        self.server = server
        self.faults = faults or Faults()
        self.prefix = call_prefix
        self.task = "setup"
        self.exchanges = []
        self.tools = {}
        self.rejected = {}  # tool name -> reason
        self._n = 0
        self._rpc_id = 0
        self._session = None

    def _next_call_id(self):
        self._n += 1
        return f"{self.prefix}-{self._n:03d}"

    def _rpc(self, method, params):
        self._rpc_id += 1
        request = {"jsonrpc": "2.0", "id": self._rpc_id, "method": method, "params": params}
        return request, self.server.handle(request)

    def _record(self, call_id, tool, source, agent_args, request, response, **extra):
        self.exchanges.append({
            "call_id": call_id, "task": self.task, "tool": tool, "t": round(self.server.clock.now(), 3),
            "source": source, "agent_args": agent_args, "request": request, "response": response,
            "dropped_optional_args": [], "undeclared_args": [], "recovered_by_client": False, **extra,
        })

    def connect(self):
        _, resp = self._rpc("auth/login", {"api_key": "mock-key"})
        self._session = resp["result"]["structuredContent"]
        _, resp = self._rpc("tools/list", {})
        for tool in resp["result"]["tools"]:
            problem = strict_schema_problem(tool["inputSchema"])
            if problem:
                self.rejected[tool["name"]] = problem
            else:
                self.tools[tool["name"]] = tool

    def call(self, tool: str, args: dict, _retried: bool = False) -> dict:
        call_id = self._next_call_id()
        if tool in self.rejected:
            result = {"isError": True, "error": {
                "source": "model_client", "cause": "schema_rejected",
                "message": f"Invalid function declaration for {tool}: {self.rejected[tool]}"}}
            self._record(call_id, tool, "client", args, None, result)
            return result

        schema = self.tools[tool]["inputSchema"]
        sent = {k: v for k, v in args.items() if k in schema["properties"]}
        undeclared = [k for k in args if k not in schema["properties"]]
        dropped = []
        if self.faults.drop_optional_args:
            dropped = [k for k in sent if k not in schema["required"]]
            sent = {k: v for k, v in sent.items() if k in schema["required"]}

        request, resp = self._rpc("tools/call", {
            "name": tool, "arguments": sent, "auth": self._session["access_token"]})
        result = resp["result"]
        self._record(call_id, tool, "server", args, request, result,
                     dropped_optional_args=dropped, undeclared_args=undeclared)

        if result["isError"] and result["error"]["status"] == 401 and not _retried:
            failed = self.exchanges[-1]
            if self._refresh():
                failed["recovered_by_client"] = True  # the agent never sees this 401
                return self.call(tool, args, _retried=True)
        return result

    def _refresh(self) -> bool:
        call_id = self._next_call_id()
        request, resp = self._rpc("auth/refresh", {"refresh_token": self._session["refresh_token"]})
        result = resp["result"]
        self._record(call_id, "auth/refresh", "server", None, request, result)
        if not result["isError"]:
            self._session = result["structuredContent"]
        return not result["isError"]
