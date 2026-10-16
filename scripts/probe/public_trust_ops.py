"""Read-only terminal classification, bounded settlement and incident evidence."""
import hashlib
import time

PENDING_STATUSES = {"queued", "in_progress", "pending", "waiting", "requested"}
FAILED_CONCLUSIONS = {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale"}

def classify_run(run):
    status = run.get("status")
    conclusion = run.get("conclusion")
    if status == "completed":
        if conclusion == "success":
            return "PASS"
        if conclusion in FAILED_CONCLUSIONS:
            return "BLOCKER"
        return "UNKNOWN"
    if status in PENDING_STATUSES and conclusion is None:
        return "PENDING"
    return "UNKNOWN"

def should_settle(records):
    return any(row["state"] == "PENDING" or (
        row["check"].startswith(("main:", "scorecard-")) and
        row["detail"].startswith("no exact-main push evidence"))
        for row in records)

def settle(sample, maximum_seconds, interval=45, clock=time.monotonic, sleep=time.sleep):
    started = clock()
    attempts = 0
    while True:
        records = sample()
        attempts += 1
        if any(row["state"] == "BLOCKER" for row in records):
            return records, {"state": "failure-observed", "attempts": attempts}
        if not should_settle(records):
            return records, {"state": "terminal", "attempts": attempts}
        remaining = maximum_seconds - (clock() - started)
        if remaining <= 0:
            records.append({"check": "settlement-deadline", "state": "UNKNOWN",
                            "detail": "dependent workflow still pending/missing at bounded timeout:critical"})
            return records, {"state": "timeout-unknown", "attempts": attempts}
        sleep(min(interval, remaining))

def incident_report(records, main_sha):
    incidents = []
    for row in records:
        if row["state"] == "PASS":
            continue
        check = row["check"]
        evidence = row.get("evidence") or {}
        if check.startswith("main:") or check == "scorecard-latest":
            next_action = "Inspect exact workflow run/job; propose an isolated branch fix and rerun checks."
        elif check.startswith("pr-"):
            next_action = "Inspect exact PR check and SHA; propose a reviewed PR fix."
        elif check in ("main-ruleset", "main-protection-contract"):
            next_action = "Inspect ruleset drift; Owner approval is required for settings changes."
        elif check in ("public-install-assets", "latest-release"):
            next_action = "Inspect published assets; release/tag/publish requires separate Owner approval."
        else:
            next_action = "Inspect source and API evidence; do not interpret unavailable data as green."
        fingerprint = "|".join(str(x) for x in (
            main_sha or "", check, evidence.get("run_id", ""),
            evidence.get("check_run_id", ""), evidence.get("sha", "")))
        incidents.append({
            "id": hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:20],
            "check": check, "state": row["state"], "observed": row["detail"],
            "evidence": evidence,
            "cause_class": ("unfinished" if row["state"] == "PENDING" else
                            "confirmed_failure_or_contract_drift" if row["state"] == "BLOCKER" else
                            "unverified_evidence" if row["state"] == "UNKNOWN" else "advisory"),
            "recommended_action": next_action,
            "follow_up": "After Owner-authorized fix, use workflow_dispatch read-only audit and reconcile incident ID.",
            "owner_gate": "No write, retry, dependency change, settings change, merge or release is authorized here."
        })
    return incidents

def self_test():
    for state in ("queued", "in_progress", "pending", "waiting", "requested"):
        assert classify_run({"status": state, "conclusion": None}) == "PENDING"
    for conclusion in FAILED_CONCLUSIONS:
        assert classify_run({"status": "completed", "conclusion": conclusion}) == "BLOCKER"
    assert classify_run({"status": "completed", "conclusion": "success"}) == "PASS"
    for sample in ({"status": "completed", "conclusion": None},
                   {"status": "completed", "conclusion": "neutral"},
                   {"status": "in_progress", "conclusion": "success"},
                   {"status": None, "conclusion": None}):
        assert classify_run(sample) == "UNKNOWN"
    pending = [{"check": "main:CI", "state": "PENDING", "detail": "queued"}]
    done = [{"check": "main:CI", "state": "PASS", "detail": "success"}]
    ticks, calls = [0], [0]
    def advance(seconds):
        ticks[0] += seconds
    def sample():
        calls[0] += 1
        return pending if calls[0] == 1 else done
    rows, meta = settle(sample, 3, interval=1, clock=lambda: ticks[0], sleep=advance)
    assert rows == done and meta == {"state": "terminal", "attempts": 2}
    ticks[0] = 0
    rows, meta = settle(lambda: pending.copy(), 2, interval=1, clock=lambda: ticks[0], sleep=advance)
    assert meta["state"] == "timeout-unknown" and any(r["check"] == "settlement-deadline" for r in rows)
    assert settle(lambda: [{"check": "main:CI", "state": "BLOCKER", "detail": "failure"}], 5)[1]["state"] == "failure-observed"
    missing = [{"check": "main:CI", "state": "UNKNOWN", "detail": "no exact-main push evidence:critical"}]
    assert settle(lambda: missing.copy(), 0)[1]["state"] == "timeout-unknown"
    red = [{"check": "main:CI", "state": "BLOCKER", "detail": "failure",
            "evidence": {"sha": "a" * 40, "run_id": 42, "url": "https://github.com/example/run/42"}}]
    assert incident_report(red, "a" * 40) == incident_report(red, "a" * 40)
    assert incident_report(red, "a" * 40)[0]["evidence"]["run_id"] == 42
    print("PUBLIC_TRUST_OPS_SELF_TEST_PASS")
