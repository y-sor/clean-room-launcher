#!/usr/bin/env python3
"""Public CLROOM trust gate. Read-only; never edits PRs, alerts, releases or settings."""
import argparse
from public_trust_ops import classify_run, settle, incident_report, self_test as ops_self_test
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
REPO = "y-sor/clean-room-launcher"
API = "https://api.github.com/repos/" + REPO
REQUIRED = ("CI", "Fuzz smoke", "Release candidate readiness", "CodeQL")
LEVELS = ("PASS", "PENDING", "ATTENTION", "BLOCKER", "UNKNOWN")


def record(items, name, state, detail, evidence=None):
    if state not in LEVELS:
        raise ValueError("invalid state")
    row = {"check": name, "state": state, "detail": str(detail)[:180]}
    if evidence is not None:
        row["evidence"] = evidence
    items.append(row)


def static_checks(root):
    out = []
    files = ("README.md", "SECURITY.md", "LICENSE", "docs/install.md",
             "docs/verify-release.md", ".github/workflows/ci.yml",
             ".github/workflows/release-candidate.yml")
    for path in files:
        record(out, "file:" + path, "PASS" if (root / path).is_file() else "BLOCKER",
               "present" if (root / path).is_file() else "missing")
    readme = (root / "README.md").read_text(encoding="utf-8") if (root / "README.md").exists() else ""
    policy = (root / "SECURITY.md").read_text(encoding="utf-8") if (root / "SECURITY.md").exists() else ""
    assertions = {
        "main-ci-badge": "actions/workflows/ci.yml/badge.svg?branch=main" in readme,
        "latest-install-route": "releases/latest/download/install.sh" in readme,
        "honest-signing-status": "unsigned and unnotarized" in readme,
        "private-vulnerability-channel": "Report a vulnerability" in policy,
    }
    for key, valid in assertions.items():
        record(out, key, "PASS" if valid else "BLOCKER", "present" if valid else "missing/misleading")
    return out


def request_json(path, token, read=None):
    if read is not None:
        return read(path)
    req = urllib.request.Request(API + path, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "clroom-public-trust-readonly",
        "X-GitHub-Api-Version": "2022-11-28",
        **({"Authorization": "Bearer " + token} if token else {}),
    })
    with urllib.request.urlopen(req, timeout=12) as response:
        return json.load(response)


def live_checks(token, read=None, phase="daily", event=None, running_sha=None):
    out = []

    def get(path, key, critical=True):
        try:
            return request_json(path, token, read)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError,
                ValueError, KeyError, OSError) as exc:
            detail = f"{type(exc).__name__}:{getattr(exc, 'code', 'unavailable')}"
            record(out, key, "UNKNOWN", detail + (":critical" if critical else ":advisory"))
            return None

    repo = get("", "repo-api")
    main = get("/branches/main", "main-identity")
    sha = main.get("commit", {}).get("sha") if isinstance(main, dict) else None
    if isinstance(repo, dict):
        valid = repo.get("id") == 1342241983 and repo.get("default_branch") == "main" and not repo.get("archived")
        record(out, "repo-identity", "PASS" if valid else "BLOCKER", "repository ID, default branch, archive status")
    if not sha:
        record(out, "main-commit", "UNKNOWN", "missing-current-main-sha:critical")
    elif phase == "daily" and running_sha and running_sha != sha:
        record(out, "main-commit-stale", "UNKNOWN", "event SHA differs from main:critical",
               {"expected_sha": running_sha, "observed_sha": sha})

    release = get("/releases/latest", "latest-release")
    if isinstance(release, dict):
        assets = {a.get("name") for a in release.get("assets", []) if isinstance(a, dict)}
        tag = release.get("tag_name")
        needed = {"install.sh", "SHA256SUMS"}
        valid = bool(tag) and not release.get("draft") and not release.get("prerelease") and needed <= assets and any(
            isinstance(n, str) and n.startswith("clean-room-launcher-") and n.endswith(".tar.gz") for n in assets)
        record(out, "public-install-assets", "PASS" if valid else "BLOCKER",
               ("published=" + str(tag)) if valid else "missing/incorrect public release assets")

    rules = get("/rulesets?includes_parents=true", "rulesets")
    if isinstance(rules, list):
        active = any(x.get("enforcement") == "active" and x.get("name") == "CLROOM main protection" for x in rules)
        record(out, "main-ruleset", "PASS" if active else "BLOCKER", "active main protection" if active else "missing/inactive")

    precise = get("/rulesets/22516055", "main-ruleset-contract")
    if isinstance(precise, dict):
        conditions = precise.get("conditions", {}).get("ref_name", {})
        rows = {rule.get("type"): rule.get("parameters", {}) for rule in precise.get("rules", [])}
        checks = rows.get("required_status_checks", {})
        contexts = {c.get("context") for c in checks.get("required_status_checks", [])}
        expected = {"Release required", "Required", "Bounded cargo-fuzz smoke", "Review dependency delta"}
        codeql = rows.get("code_scanning", {}).get("code_scanning_tools", [])
        valid = (precise.get("enforcement") == "active"
                 and "refs/heads/main" in conditions.get("include", [])
                 and {"deletion", "non_fast_forward", "pull_request",
                      "required_status_checks", "code_scanning"} <= rows.keys()
                 and checks.get("strict_required_status_checks_policy") is True
                 and expected <= contexts
                 and any(tool.get("tool") == "CodeQL" and tool.get("security_alerts_threshold") == "high_or_higher"
                         for tool in codeql))
        record(out, "main-protection-contract", "PASS" if valid else "BLOCKER",
               "active protected main + required checks + CodeQL" if valid else "protection contract drift")

    if sha:
        runs = get("/actions/runs?branch=main&per_page=100", "main-workflow-runs")
        if isinstance(runs, dict):
            all_runs = runs.get("workflow_runs", [])
            if not isinstance(all_runs, list):
                record(out, "main-workflow-runs-shape", "UNKNOWN", "invalid run listing:critical")
                all_runs = []
            for name in (*REQUIRED, "OpenSSF Scorecard"):
                candidates = [r for r in all_runs if isinstance(r, dict) and
                              r.get("name") == name and r.get("head_sha") == sha and
                              r.get("event") == "push"]
                key = "scorecard-latest" if name == "OpenSSF Scorecard" else "main:" + name
                if not candidates:
                    record(out, key, "UNKNOWN", "no exact-main push evidence:" +
                           ("critical" if phase == "daily" else "advisory-release-deferred"),
                           {"sha": sha, "workflow": name})
                    continue
                latest = max(candidates, key=lambda r: (
                    r.get("created_at") or "", r.get("run_attempt") or 0, r.get("id") or 0))
                state = classify_run(latest)
                record(out, key, state,
                       str(latest.get("conclusion") or latest.get("status") or "invalid-status") +
                       (":critical" if state == "UNKNOWN" and phase == "daily" else ""),
                       {"sha": sha, "workflow": name, "run_id": latest.get("id"),
                        "run_attempt": latest.get("run_attempt"), "url": latest.get("html_url")})

    prs = get("/pulls?state=open&per_page=100", "open-prs", critical=False)
    if isinstance(prs, list):
        record(out, "open-pr-count", "PASS" if len(prs) < 5 else "ATTENTION", str(len(prs)) + " open PRs")
        for pr in prs[:15]:
            number, head = pr.get("number"), pr.get("head", {}).get("sha")
            if not isinstance(number, int) or not head:
                record(out, "pr-check", "UNKNOWN", "missing PR identity:advisory")
                continue
            checks = get(f"/commits/{head}/check-runs?per_page=100", f"pr-{number}-checks", critical=False)
            if not isinstance(checks, dict):
                continue
            rows = checks.get("check_runs", [])
            if not isinstance(rows, list) or checks.get("total_count", len(rows)) > len(rows):
                record(out, f"pr-{number}-checks-incomplete", "UNKNOWN",
                       "incomplete PR check listing:advisory", {"sha": head, "pr": number})
                continue
            for row in rows:
                if row.get("status") == "completed" and row.get("conclusion") in (
                        "failure", "timed_out", "action_required", "cancelled", "startup_failure"):
                    record(out, f"pr-{number}-red", "ATTENTION",
                           str(row.get("name") or "unnamed") + ":" + str(row.get("conclusion")),
                           {"sha": head, "pr": number, "check_run_id": row.get("id"),
                            "url": row.get("html_url")})

    return out


def decision(records, mode):
    blocked = [r for r in records if r["state"] == "BLOCKER"]
    missing_core = [r for r in records if r["state"] == "UNKNOWN" and ":critical" in r["detail"]]
    if blocked or missing_core:
        return "BLOCKED"
    if mode == "daily" and any(r["state"] == "PENDING" for r in records):
        return "PENDING"
    if mode == "daily" and any(r["state"] in ("ATTENTION", "UNKNOWN") for r in records):
        return "ATTENTION_REQUIRED"
    return "PASS"


def self_test():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        for p in ("README.md", "SECURITY.md", "LICENSE", "docs/install.md", "docs/verify-release.md",
                  ".github/workflows/ci.yml", ".github/workflows/release-candidate.yml"):
            dest = root / p
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("x", encoding="utf-8")
        (root / "README.md").write_text(
            "actions/workflows/ci.yml/badge.svg?branch=main\n"
            "releases/latest/download/install.sh\nunsigned and unnotarized", encoding="utf-8")
        (root / "SECURITY.md").write_text("Report a vulnerability", encoding="utf-8")
        assert decision(static_checks(root), "release") == "PASS"
        (root / "README.md").write_text("badge.svg", encoding="utf-8")
        assert decision(static_checks(root), "release") == "BLOCKED"
    base = {"id": 1342241983, "default_branch": "main", "archived": False}
    sha = "a" * 40
    fixture = {
        "": base, "/branches/main": {"commit": {"sha": sha}},
        "/releases/latest": {"tag_name": "v0.6.0", "draft": False, "prerelease": False,
                             "assets": [{"name": "install.sh"}, {"name": "SHA256SUMS"},
                                        {"name": "clean-room-launcher-v0.6.0-aarch64-apple-darwin.tar.gz"}]},
        "/rulesets?includes_parents=true": [{"name": "CLROOM main protection", "enforcement": "active"}],
        "/rulesets/22516055": {
            "enforcement": "active",
            "conditions": {"ref_name": {"include": ["refs/heads/main"]}},
            "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}, {"type": "pull_request"},
                      {"type": "required_status_checks", "parameters": {
                          "strict_required_status_checks_policy": True,
                          "required_status_checks": [{"context": k} for k in (
                              "Release required", "Required", "Bounded cargo-fuzz smoke", "Review dependency delta")]}},
                      {"type": "code_scanning", "parameters": {
                          "code_scanning_tools": [{"tool": "CodeQL", "security_alerts_threshold": "high_or_higher"}]}}]},
        "/actions/runs?branch=main&per_page=100": {
            "workflow_runs": [{"name": n, "head_sha": sha, "event": "push",
                               "created_at": "2026-10-15T00:00:00Z", "id": len(n),
                               "status": "completed", "conclusion": "success"}
                              for n in (*REQUIRED, "OpenSSF Scorecard")]},
        "/pulls?state=open&per_page=100": [],
    }
    assert decision(live_checks("", fixture.__getitem__), "daily") == "PASS"
    fixture["/rulesets/22516055"]["rules"][3]["parameters"]["required_status_checks"] = []
    assert decision(live_checks("", fixture.__getitem__), "release") == "BLOCKED"
    fixture["/rulesets/22516055"]["rules"][3]["parameters"]["required_status_checks"] = [
        {"context": k} for k in ("Release required", "Required", "Bounded cargo-fuzz smoke", "Review dependency delta")]
    fixture["/actions/runs?branch=main&per_page=100"]["workflow_runs"][0]["conclusion"] = None
    fixture["/actions/runs?branch=main&per_page=100"]["workflow_runs"][0]["status"] = "in_progress"
    assert decision(live_checks("", fixture.__getitem__, phase="release", event="push", running_sha=sha), "release") == "PASS"
    assert decision(live_checks("", fixture.__getitem__, phase="daily"), "daily") == "PENDING"
    fixture["/actions/runs?branch=main&per_page=100"]["workflow_runs"][0]["status"] = "completed"
    fixture["/actions/runs?branch=main&per_page=100"]["workflow_runs"][0]["conclusion"] = "failure"
    assert decision(live_checks("", fixture.__getitem__), "release") == "BLOCKED"
    fixture["/actions/runs?branch=main&per_page=100"]["workflow_runs"][0]["conclusion"] = "success"
    fixture["/pulls?state=open&per_page=100"] = [{"number": 7, "head": {"sha": sha}}] * 5
    fixture[f"/commits/{sha}/check-runs?per_page=100"] = {"check_runs": [{"id": 71, "name": "Fuzz",
        "status": "completed", "conclusion": "failure"}]}
    assert decision(live_checks("", fixture.__getitem__), "daily") == "ATTENTION_REQUIRED"
    assert decision(live_checks("", fixture.__getitem__), "release") == "PASS"
    # Real failures, stale snapshots, unknowns and Scorecard are never silently green.
    fixture["/pulls?state=open&per_page=100"] = []
    runs = fixture["/actions/runs?branch=main&per_page=100"]["workflow_runs"]
    for row in runs:
        row["status"], row["conclusion"] = "completed", "success"
    assert decision(live_checks("", fixture.__getitem__, phase="daily",
                                running_sha="b" * 40), "daily") == "BLOCKED"
    runs[0]["status"], runs[0]["conclusion"] = "queued", None
    assert decision(live_checks("", fixture.__getitem__), "daily") == "PENDING"
    runs[0]["status"], runs[0]["conclusion"] = "completed", None
    assert decision(live_checks("", fixture.__getitem__), "daily") == "BLOCKED"
    runs[0]["status"], runs[0]["conclusion"] = "completed", "failure"
    rows = live_checks("", fixture.__getitem__)
    assert decision(rows, "daily") == "BLOCKED"
    assert any(row["evidence"]["run_id"] == len("CI") for row in rows if row["check"] == "main:CI")
    assert incident_report(rows, sha) == incident_report(rows, sha)
    runs[0]["status"], runs[0]["conclusion"] = "completed", "success"
    score = next(row for row in runs if row["name"] == "OpenSSF Scorecard")
    score["status"], score["conclusion"] = "completed", "failure"
    assert decision(live_checks("", fixture.__getitem__), "daily") == "BLOCKED"
    score["status"], score["conclusion"] = "in_progress", None
    assert decision(live_checks("", fixture.__getitem__), "daily") == "PENDING"
    score["status"], score["conclusion"] = "completed", "success"
    saved = runs.pop(0)
    assert decision(live_checks("", fixture.__getitem__), "daily") == "BLOCKED"
    runs.insert(0, saved)
    fixture["/pulls?state=open&per_page=100"] = [{"number": 7, "head": {"sha": sha}}]
    fixture[f"/commits/{sha}/check-runs?per_page=100"] = {"total_count": 2, "check_runs": []}
    assert decision(live_checks("", fixture.__getitem__), "daily") == "ATTENTION_REQUIRED"
    fixture[f"/commits/{sha}/check-runs?per_page=100"] = {
        "check_runs": [{"id": 99, "name": "Security", "status": "completed",
                        "conclusion": "timed_out"}]}
    assert any(row.get("evidence", {}).get("check_run_id") == 99
               for row in live_checks("", fixture.__getitem__) if row["check"] == "pr-7-red")
    ops_self_test()
    print("PUBLIC_TRUST_SELF_TEST_PASS")


def main():
    parser = argparse.ArgumentParser()
    options = parser.add_mutually_exclusive_group(required=True)
    options.add_argument("--self-test", action="store_true")
    options.add_argument("--static", action="store_true")
    options.add_argument("--release-live", action="store_true")
    options.add_argument("--daily", action="store_true")
    parser.add_argument("--settle-seconds", type=int, default=0)
    args = parser.parse_args()
    if not 0 <= args.settle_seconds <= 3300:
        parser.error("settle-seconds must be between 0 and 3300")
    if args.self_test:
        self_test()
        return 0
    records = static_checks(ROOT)
    mode = "daily" if args.daily else "release"
    settlement = {"state": "not-requested", "attempts": 0}
    if args.release_live or args.daily:
        def sample():
            return static_checks(ROOT) + live_checks(
                os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN", ""),
                phase=mode, event=os.environ.get("GITHUB_EVENT_NAME"),
                running_sha=os.environ.get("GITHUB_SHA") if args.daily else None)
        if args.daily:
            records, settlement = settle(sample, args.settle_seconds)
        else:
            records = sample()
            settlement = {"state": "release-preflight-not-terminal-watch", "attempts": 1}
    verdict = decision(records, mode)
    incidents = incident_report(records, os.environ.get("GITHUB_SHA"))
    report = {"schema": "clroom.public-trust.v2", "verdict": verdict,
              "settlement": settlement, "checks": records, "incidents": incidents,
              "remediation": "Read-only. No automatic fix, notification delivery, merge or settings changes.",
              "disclaimer": "Public evidence only; not a comprehensive security/adoption audit"}
    print(json.dumps(report, sort_keys=True, ensure_ascii=True))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### CLROOM public trust: {verdict}\n\n")
            handle.write(f"Settlement: {settlement['state']} ({settlement['attempts']} observations)\n\n")
            for item in incidents:
                handle.write(f"- **{item['state']}** {item['check']} / incident {item['id']}: {item['observed']}\n")
                if item["evidence"]:
                    handle.write(f"  - Evidence: {json.dumps(item['evidence'], sort_keys=True)}\n")
                handle.write(f"  - Next: {item['recommended_action']}\n")
            handle.write("\nFollow-up: Owner-authorized fix in branch/PR; workflow_dispatch read-only re-audit.\n")
            handle.write("No automatic merges, bypasses or settings changes.\n")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
