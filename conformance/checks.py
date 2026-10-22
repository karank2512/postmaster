"""Checks against server-side truth, plus trace-based classification of failures."""

from dataclasses import asdict, dataclass, field

from .contract import ERROR_KINDS, RETRYABLE_CAUSES


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    trace_refs: list = field(default_factory=list)
    kind: str = None  # set on failure, from ERROR_KINDS
    retryable: bool = None
    next_action: str = None

    def fail_as(self, kind: str, evidence: list = ()) -> "Check":
        self.kind = kind
        self.retryable = ERROR_KINDS[kind]["retryable"]
        self.next_action = ERROR_KINDS[kind]["next_action"]
        self.trace_refs = sorted(set(self.trace_refs) | set(evidence))
        return self

    def to_dict(self) -> dict:
        return asdict(self)


def ids(exchanges, tool=None):
    return [e["call_id"] for e in exchanges if tool is None or e["tool"] == tool]


def is_error(e) -> bool:
    return e["response"]["isError"]


def classify(exchanges, store):
    """Pick the most specific error kind the trace supports. Returns (kind, evidence call ids)."""
    hits = [e for e in exchanges if e["source"] == "client" and e["response"]["error"]["cause"] == "schema_rejected"]
    if hits:
        return "schema_rejected", ids(hits)
    hits = [e for e in exchanges if e["tool"] == "auth/refresh" and is_error(e)]
    if hits:
        return "token_expired_unrecoverable", ids(hits) + [
            e["call_id"] for e in exchanges if is_error(e) and e["response"]["error"].get("status") == 401]
    for e in exchanges:
        if e["source"] == "server" and is_error(e) and e["response"]["error"].get("status") == 404:
            inbox = store.inboxes.get((e["agent_args"] or {}).get("inbox_id"))
            # The store has this inbox, it was created moments ago, yet the server said 404.
            if inbox and e["t"] - inbox.created_at < 5:
                return "inbox_not_ready", [e["call_id"]]
    hits = [e for e in exchanges if e["dropped_optional_args"]]
    if hits:
        return "optional_args_dropped", ids(hits)
    return "unknown", []


def check_schema_accepted(exchanges) -> Check:
    rejected = [e for e in exchanges if e["source"] == "client"]
    if not rejected:
        return Check("schema_accepted", True, "every tool the agent called was accepted by the model client",
                     ids(exchanges))
    detail = "; ".join(e["response"]["error"]["message"] for e in rejected)
    return Check("schema_accepted", False, detail, ids(rejected)).fail_as("schema_rejected")


def check_errors_follow_contract(exchanges) -> Check:
    # Only errors the agent had to act on; a 401 the client fixed by refreshing never reached it.
    errors = [e for e in exchanges if e["source"] == "server" and is_error(e) and not e["recovered_by_client"]]
    bad = []
    for e in errors:
        err = e["response"]["error"]
        if "cause" not in err or "next_action" not in err:
            bad.append(e)
        elif err["cause"] in RETRYABLE_CAUSES and "retry_after" not in err:
            bad.append(e)
    if not errors:
        return Check("errors_follow_contract", True, "no server errors in this task")
    if not bad:
        return Check("errors_follow_contract", True,
                     f"{len(errors)} server error(s), all carry cause and next_action", ids(errors))
    sample = bad[0]["response"]["error"]
    return Check("errors_follow_contract", False,
                 f"{len(bad)} of {len(errors)} server error(s) lack the contract fields, e.g. {sample}",
                 ids(bad)).fail_as("contract_violation")


def check_claim(claim: dict, truth_ok: bool, exchanges) -> Check:
    said = claim.get("said", "")
    if claim["success"] == truth_ok:
        return Check("agent_claim_matches_truth", True,
                     f"agent said {said!r}; server truth {'agrees' if truth_ok else 'also shows failure'}")
    verdict = "succeeded" if claim["success"] else "failed"
    return Check("agent_claim_matches_truth", False,
                 f"agent said it {verdict} ({said!r}) but server truth disagrees",
                 ids(exchanges)).fail_as("claim_mismatch")


def finalize(truth_checks, exchanges, store, claim) -> list:
    """Classify failed truth checks from trace evidence, then add claim and contract checks."""
    for c in truth_checks:
        if not c.passed and c.kind is None:
            c.fail_as(*classify(exchanges, store))
    truth_ok = all(c.passed for c in truth_checks)
    return truth_checks + [check_claim(claim, truth_ok, exchanges), check_errors_follow_contract(exchanges)]
