"""The mock reproduces each documented failure mode, switchable by flag."""

import pytest

from mock_agentmail import FakeClock, Faults, InboxStore, MockAgentMailMCP, SimulatedModelClient


def make(**faults):
    clock, store = FakeClock(), InboxStore()
    f = Faults(**faults)
    server = MockAgentMailMCP(store, clock, f)
    client = SimulatedModelClient(server, f)
    client.connect()
    return clock, store, server, client


def test_healthy_schemas_pass_strict_client():
    *_, client = make()
    assert client.rejected == {}


def test_schema_rejection_flag_makes_strict_client_reject_send_and_reply():  # agentmail-mcp#8
    *_, client = make(schema_rejection=True)
    assert set(client.rejected) == {"send_message", "reply_to_message"}
    r = client.call("send_message", {"inbox_id": "x", "to": ["a@b.c"]})
    assert r["error"]["cause"] == "schema_rejected"
    assert client.exchanges[-1]["request"] is None  # never reached the server


def test_drop_optional_args_delivers_blank_email_and_reports_success():  # agentmail-mcp#18
    _, store, _, client = make(drop_optional_args=True)
    inbox = store.create_inbox("a", -100)
    r = client.call("send_message", {"inbox_id": inbox.inbox_id, "to": ["x@y.z"], "subject": "Hi", "text": "Body"})
    assert r["isError"] is False
    assert (store.messages[-1].subject, store.messages[-1].text) == ("", "")
    assert client.exchanges[-1]["dropped_optional_args"] == ["subject", "text"]


@pytest.mark.parametrize("fault,recovers", [(False, True), (True, False)])
def test_token_expiry_and_refresh(fault, recovers):  # agentmail-mcp#50
    clock, store, server, client = make(token_no_recovery=fault)
    inbox = store.create_inbox("a", -100)
    clock.sleep(server.token_ttl + 1)
    r = client.call("list_messages", {"inbox_id": inbox.inbox_id})
    assert (not r["isError"]) is recovers
    assert any(e["tool"] == "auth/refresh" for e in client.exchanges)
    if not recovers:
        assert r["error"]["status"] == 401


def test_inbox_404_window_after_create():  # agentmail-node#14
    clock, store, _, client = make(inbox_not_ready_404=True)
    inbox_id = client.call("create_inbox", {})["structuredContent"]["inbox_id"]
    r = client.call("list_messages", {"inbox_id": inbox_id})
    assert r["error"]["status"] == 404 and r["error"]["message"] == "Inbox not found"
    assert r["error"]["retry_after"] == 1.5 and r["error"]["cause"] == "inbox_not_ready"
    clock.sleep(1.5)
    assert client.call("list_messages", {"inbox_id": inbox_id})["isError"] is False


def test_error_contract_off_strips_machine_readable_fields():
    _, _, _, client = make(inbox_not_ready_404=True, error_contract=False)
    inbox_id = client.call("create_inbox", {})["structuredContent"]["inbox_id"]
    err = client.call("list_messages", {"inbox_id": inbox_id})["error"]
    assert err == {"status": 404, "message": "Inbox not found"}


@pytest.mark.parametrize("fault,visible", [(False, True), (True, False)])
def test_unauthenticated_inbound_visibility(fault, visible):  # agentmail-mcp#38
    _, store, _, client = make(hide_unauthenticated=fault)
    inbox = store.create_inbox("a", -100)
    store.add_message(inbox.inbox_id, "inbound", "c@d.e", [inbox.address], "Re: hi", "ok", -100,
                      labels=["received", "unauthenticated"])
    r = client.call("search_messages", {"inbox_id": inbox.inbox_id, "query": "c@d.e",
                                        "include_unauthenticated": True})
    assert bool(r["structuredContent"]["messages"]) is visible
    if fault:
        assert client.exchanges[-1]["undeclared_args"] == ["include_unauthenticated"]
