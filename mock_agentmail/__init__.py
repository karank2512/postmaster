"""A local, in-process mock of the AgentMail MCP server.

Everything here is fake: no account, no API key, no network. The store is the
server-side truth that the conformance harness checks against.
"""

from .clock import FakeClock
from .faults import FAULT_NAMES, Faults
from .store import Inbox, InboxStore, Message
from .server import MockAgentMailMCP
from .client import SimulatedModelClient

__all__ = [
    "FAULT_NAMES",
    "FakeClock",
    "Faults",
    "Inbox",
    "InboxStore",
    "Message",
    "MockAgentMailMCP",
    "SimulatedModelClient",
]
