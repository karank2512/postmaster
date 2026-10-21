import base64
import hashlib
from dataclasses import dataclass, field


@dataclass
class Inbox:
    inbox_id: str
    address: str
    created_at: float
    seeded: bool = False


@dataclass
class Message:
    message_id: str
    inbox_id: str
    direction: str  # "inbound" or "outbound"
    sender: str
    to: list
    subject: str
    text: str
    created_at: float
    labels: list = field(default_factory=list)
    attachments: list = field(default_factory=list)  # [{filename, sha256, size}]
    in_reply_to: str = None

    @property
    def unauthenticated(self) -> bool:
        return "unauthenticated" in self.labels


class InboxStore:
    """Server-side truth: what actually exists, regardless of what any tool reported."""

    DOMAIN = "agentmail.mock"

    def __init__(self):
        self.inboxes = {}
        self.messages = []
        self._seq = 0

    def _next(self, prefix: str) -> str:
        self._seq += 1
        return f"{prefix}_{self._seq:04d}"

    def create_inbox(self, username: str, now: float, seeded: bool = False) -> Inbox:
        username = username or self._next("agent")
        inbox = Inbox(self._next("inb"), f"{username}@{self.DOMAIN}", now, seeded)
        self.inboxes[inbox.inbox_id] = inbox
        return inbox

    def add_message(self, inbox_id, direction, sender, to, subject, text, now,
                    labels=None, attachments=None, in_reply_to=None) -> Message:
        msg = Message(self._next("msg"), inbox_id, direction, sender, list(to), subject or "",
                      text or "", now, list(labels or []), list(attachments or []), in_reply_to)
        self.messages.append(msg)
        return msg

    def get_message(self, message_id: str) -> Message:
        return next((m for m in self.messages if m.message_id == message_id), None)

    def messages_in(self, inbox_id: str) -> list:
        return [m for m in self.messages if m.inbox_id == inbox_id]

    @staticmethod
    def attachment_record(filename: str, content_base64: str) -> dict:
        raw = base64.b64decode(content_base64)
        return {"filename": filename, "sha256": hashlib.sha256(raw).hexdigest(), "size": len(raw)}
