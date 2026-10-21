from dataclasses import dataclass, fields

# Each flag reproduces one publicly reported failure mode.
FAULT_NAMES = (
    "schema_rejection",      # agentmail-mcp#8: send/reply schemas rejected by a strict model client
    "drop_optional_args",    # agentmail-mcp#18: optional subject/body silently dropped
    "token_no_recovery",     # agentmail-mcp#50: token expires, refresh never recovers the session
    "inbox_not_ready_404",   # agentmail-node#14: 404 "Inbox not found" right after create
    "hide_unauthenticated",  # agentmail-mcp#38: unauthenticated inbound invisible to list/search
)


@dataclass
class Faults:
    schema_rejection: bool = False
    drop_optional_args: bool = False
    token_no_recovery: bool = False
    inbox_not_ready_404: bool = False
    hide_unauthenticated: bool = False
    # Not a fault: the proposed fix. When on, every server error carries a
    # machine-readable cause, next_action, and retry_after where it applies.
    error_contract: bool = True
    inbox_ready_delay: float = 1.5

    @classmethod
    def from_names(cls, names, error_contract: bool = True) -> "Faults":
        unknown = set(names) - set(FAULT_NAMES)
        if unknown:
            raise ValueError(f"unknown fault(s): {sorted(unknown)}; choose from {FAULT_NAMES}")
        return cls(error_contract=error_contract, **{n: True for n in names})

    def enabled(self) -> list:
        return [f.name for f in fields(self) if f.name in FAULT_NAMES and getattr(self, f.name)]
