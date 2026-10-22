"""The harness detects each failure mode from server-side truth and classifies it."""

import json

import pytest

from conformance import SCENARIOS, run_scenario
from conformance.__main__ import main
from conformance.contract import ERROR_KINDS

BY_NAME = {s.name: s for s in SCENARIOS}
TASKS = ["onboard_and_send", "reply_with_attachment", "find_unauthenticated_inbound", "survive_token_refresh"]


@pytest.fixture(scope="module")
def results():
    return {s.name: run_scenario(s) for s in SCENARIOS}


def check(result, task, name):
    t = next(t for t in result["tasks"] if t["task"] == task)
    return next(c for c in t["checks"] if c["name"] == name)


def task_passed(result, task):
    return next(t for t in result["tasks"] if t["task"] == task)["passed"]


def test_healthy_run_passes_every_check(results):
    r = results["healthy"]
    failed = [(t["task"], c["name"]) for t in r["tasks"] for c in t["checks"] if not c["passed"]]
    assert failed == []
    assert [t["task"] for t in r["tasks"]] == TASKS


@pytest.mark.parametrize("scenario,task,check_name,kind", [
    ("schema_rejection", "onboard_and_send", "schema_accepted", "schema_rejected"),
    ("schema_rejection", "reply_with_attachment", "reply_delivered_exactly_once", "schema_rejected"),
    ("drop_optional_args", "onboard_and_send", "content_intact", "optional_args_dropped"),
    ("drop_optional_args", "onboard_and_send", "agent_claim_matches_truth", "claim_mismatch"),
    ("drop_optional_args", "reply_with_attachment", "attachment_intact", "optional_args_dropped"),
    ("token_no_recovery", "survive_token_refresh", "session_recovered", "token_expired_unrecoverable"),
    ("token_no_recovery", "survive_token_refresh", "errors_follow_contract", "contract_violation"),
    ("inbox_not_ready_404", "onboard_and_send", "delivered_exactly_once", "inbox_not_ready"),
    ("inbox_not_ready_404", "onboard_and_send", "errors_follow_contract", "contract_violation"),
    ("hide_unauthenticated", "find_unauthenticated_inbound", "inbound_visible_via_mcp", "unauthenticated_hidden"),
    ("hide_unauthenticated", "find_unauthenticated_inbound", "agent_claim_matches_truth", "claim_mismatch"),
])
def test_failure_mode_detected_and_classified(results, scenario, task, check_name, kind):
    c = check(results[scenario], task, check_name)
    assert not c["passed"]
    assert c["kind"] == kind
    assert c["next_action"] == ERROR_KINDS[kind]["next_action"]
    assert c["trace_refs"], "every failure must link to its evidence"


@pytest.mark.parametrize("scenario,affected", [
    ("token_no_recovery", {"survive_token_refresh"}),
    ("inbox_not_ready_404", {"onboard_and_send"}),
    ("hide_unauthenticated", {"find_unauthenticated_inbound"}),
])
def test_faults_only_break_the_tasks_they_target(results, scenario, affected):
    failing = {t for t in TASKS if not task_passed(results[scenario], t)}
    assert failing == affected


def test_error_contract_lets_agent_recover_from_fresh_inbox_404(results):
    r = results["inbox_not_ready_404_with_contract"]
    assert r["passed"]
    retried = [e for e in r["traces"].values() if e["response"]["isError"]]
    assert retried and retried[0]["response"]["error"]["retry_after"] == 1.5


def test_checks_use_server_truth_not_agent_claim(results):
    # In drop_optional_args the agent believes it succeeded; the store shows a blank email.
    t = next(t for t in results["drop_optional_args"]["tasks"] if t["task"] == "onboard_and_send")
    assert t["agent_claim"]["success"] is True
    assert check(results["drop_optional_args"], "onboard_and_send", "delivered_exactly_once")["passed"]
    assert not check(results["drop_optional_args"], "onboard_and_send", "content_intact")["passed"]


def test_every_trace_ref_resolves_to_a_request_response_pair(results):
    for r in results.values():
        for t in r["tasks"]:
            for c in t["checks"]:
                for ref in c["trace_refs"]:
                    e = r["traces"][ref]
                    assert e["call_id"] == ref and "response" in e and "request" in e
                if not c["passed"]:
                    assert c["kind"] in ERROR_KINDS


def test_cli_writes_json_and_markdown(tmp_path, capsys):
    assert main(["run", "--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "conformance.json").read_text())
    md = (tmp_path / "conformance.md").read_text()
    assert report["scoreboard"]["healthy"] == {t: "PASS" for t in TASKS}
    ref = check(report["scenarios"][1], "onboard_and_send", "schema_accepted")["trace_refs"][0]
    assert f'<a id="{ref}"></a>' in md and f"(#{ref})" in md
    assert "healthy" in capsys.readouterr().out


def test_cli_custom_faults_and_fail_on_error(tmp_path):
    assert main(["run", "--faults", "", "--out", str(tmp_path), "--fail-on-error"]) == 0
    assert main(["run", "--faults", "drop_optional_args", "--out", str(tmp_path), "--fail-on-error"]) == 1
