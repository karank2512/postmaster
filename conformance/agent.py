class ContractAwareAgent:
    """Scripted stand-in for an LLM agent.

    It behaves like a careful agent: it trusts tool results, and it retries only
    when an error says how long to wait (retry_after). Without the error
    contract, a 404 "Inbox not found" gives it no reason to retry, so it gives up,
    which is what an agent at 3am would do.
    """

    def __init__(self, client, clock, max_retries: int = 3):
        self.client = client
        self.clock = clock
        self.max_retries = max_retries

    def call(self, tool: str, args: dict) -> dict:
        for attempt in range(self.max_retries + 1):
            result = self.client.call(tool, args)
            if not result["isError"]:
                return result
            wait = result["error"].get("retry_after")
            if wait is None or attempt == self.max_retries:
                return result
            self.clock.sleep(wait)
        return result

    def idle(self, seconds: float) -> None:
        self.clock.sleep(seconds)
