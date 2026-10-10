#!/usr/bin/env python3
"""Bind untrusted upstream/advisory observations into a non-authoritative risk envelope."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import sys

SOURCE_SCHEMA = "clroom.advisory-watch.v1"
SECURITY_SCHEMA = "clroom.advisory-intake.v1"
OUTPUT_SCHEMA = "clroom.risk-intelligence-input.v1"
SOURCES = frozenset({"codex", "claude", "agent-plugins", "agent-skills", "mcp"})
COVERAGE = frozenset({
    "github-reviewed-rust",
    "github-reviewed-actions",
    "github-reviewed-npm-provider-pins",
    "cisa-kev-mirror",
})
MAX_SOURCE_BYTES = 512 * 1024
MAX_SECURITY_BYTES = 2 * 1024 * 1024


class InvalidEvidence(ValueError):
    pass


def require(test, reason):
    if not test:
        raise InvalidEvidence(reason)


def read_bounded(path, limit):
    require(path.is_file(), "evidence-file-missing")
    require(path.stat().st_size <= limit, "evidence-file-oversize")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise InvalidEvidence("evidence-not-json") from error


def as_utc(text):
    require(isinstance(text, str), "missing-observation-time")
    try:
        result = dt.datetime.fromisoformat(text)
    except ValueError as error:
        raise InvalidEvidence("malformed-observation-time") from error
    require(result.tzinfo is not None and result.utcoffset() is not None, "naive-observation-time")
    return result.astimezone(dt.timezone.utc)


def source_state(item):
    require(isinstance(item, dict), "malformed-source")
    key, state = item.get("source"), item.get("state")
    # The existing collector uses source IDs in the field "source" and reports
    # fixed source locations in "url". Do not accept arbitrary extra sources.
    require(key in SOURCES and isinstance(state, str), "unknown-source-id-or-state")
    require(state in {"UNKNOWN", "UNCHANGED", "REVIEW_NEEDED", "OBSERVED_UNTRIAGED"},
            "unexpected-source-state")
    return key, state


def assemble(upstream, advisory, now, source_head, max_age_hours=48):
    require(isinstance(upstream, dict) and upstream.get("schema") == SOURCE_SCHEMA,
            "upstream-schema-mismatch")
    require(isinstance(advisory, dict) and advisory.get("schema") == SECURITY_SCHEMA,
            "advisory-schema-mismatch")
    require(upstream.get("release_decision") == "NOT_AUTHORIZED" and
            advisory.get("release_decision") == "NOT_AUTHORIZED", "unsafe-release-claim")
    require(isinstance(source_head, str) and bool(source_head), "missing-source-head")
    require(upstream.get("source_commit") == source_head and
            advisory.get("source_commit") == source_head, "source-head-mismatch")

    require(isinstance(upstream.get("signals"), list), "upstream-signals-missing")
    signals = upstream["signals"]
    require(len(signals) == len(SOURCES), "incomplete-upstream-sources")
    states = dict(source_state(s) for s in signals)
    require(len(states) == len(SOURCES) and set(states) == SOURCES,
            "duplicate-or-missing-upstream-source")
    coverage = advisory.get("coverage")
    require(isinstance(coverage, dict) and set(coverage) == COVERAGE,
            "incomplete-security-coverage")
    require(all(isinstance(v, str) and
                (v.startswith("OBSERVED_RECENT_WINDOW_PAGES_") or
                 v == "OBSERVED_SNAPSHOT" or v.startswith("UNKNOWN:"))
                for v in coverage.values()), "invalid-security-coverage-state")
    require(coverage["cisa-kev-mirror"] == "OBSERVED_SNAPSHOT" or
            coverage["cisa-kev-mirror"].startswith("UNKNOWN:"), "invalid-kev-source-state")

    t1, t2 = as_utc(upstream.get("observed_at")), as_utc(advisory.get("observed_at"))
    require(isinstance(now, dt.datetime) and now.tzinfo is not None, "invalid-reference-time")
    utc_now = now.astimezone(dt.timezone.utc)
    ages = [(utc_now - t).total_seconds() for t in (t1, t2)]
    # Future timestamps are a hard error. Old snapshots remain records of
    # history, but are explicitly stale and cannot represent today's audit.
    require(all(age >= -300 for age in ages), "observation-in-future")
    require(abs((t1 - t2).total_seconds()) <= 1800, "observation-window-mismatch")

    found = advisory.get("signals")
    require(isinstance(found, list) and len(found) <= 500, "malformed-advisory-candidates")
    candidates = []
    for item in found:
        require(isinstance(item, dict), "malformed-advisory-candidate")
        ghsa, pkg, ecosystem = item.get("ghsa_id"), item.get("package"), item.get("ecosystem")
        require(isinstance(ghsa, str) and ghsa.startswith("GHSA-") and
                isinstance(pkg, str) and 0 < len(pkg) <= 160 and
                ecosystem in {"rust", "npm", "actions"}, "unexpected-candidate-identity")
        require(item.get("release_decision") == "NOT_AUTHORIZED", "unauthorized-candidate")
        require(isinstance(item.get("present_versions"), list), "missing-inventory-version")
        candidates.append({
            "ghsa_id": ghsa, "package": pkg, "ecosystem": ecosystem,
            "cve_id": item.get("cve_id"), "kev": item.get("cisa_kev_listed"),
            "present_versions": item["present_versions"],
            "vendor_severity": item.get("vendor_severity", "unknown"),
            "applicability": "NOT_EVALUATED",
        })
    coverage_unknown = sorted(k for k, v in coverage.items() if v.startswith("UNKNOWN:"))
    source_unknown = sorted(k for k, v in states.items() if v == "UNKNOWN")
    stale = max(ages) > max_age_hours * 3600
    state = ("STALE" if stale else
             "UNKNOWN_COVERAGE" if coverage_unknown or source_unknown else
             "TRIAGE_CANDIDATES" if candidates else
             "SOURCE_SIGNALS_OBSERVED")
    return {
        "schema": OUTPUT_SCHEMA,
        "generated_at": utc_now.isoformat(),
        "source_commit": source_head,
        "observed_at": {"upstream": t1.isoformat(), "advisories": t2.isoformat()},
        "max_age_hours": max_age_hours,
        "state": state,
        "upstream": {
            "states": states,
            "provider_version_drift": sorted(k for k, v in states.items() if v == "REVIEW_NEEDED"),
        },
        "coverage": coverage,
        "unknown": {"source": source_unknown, "security": coverage_unknown},
        "advisory_candidates": candidates,
        "release_decision": "NOT_AUTHORIZED",
        "nonclaims": [
            "Read-only untrusted data, not instructions, GPT authorization, a security verdict, or release permission.",
            "A matched GHSA or CISA KEV listing does not establish CLROOM exploitability or affected installed version.",
            "Observation of a source main SHA does not establish a published specification revision.",
            "GHSA feed only covers reviewed advisories modified in 30 days and pinned provider npm packages.",
            "Missing, incomplete, future, mismatched or stale evidence never means that no security issue exists.",
            "GitHub schedule execution and ChatGPT scheduled task/tool/notification delivery need separate E2E evidence.",
        ],
    }


def self_test():
    now = dt.datetime(2026, 10, 10, 6, 20, tzinfo=dt.timezone.utc)
    earlier = (now - dt.timedelta(minutes=3)).isoformat()
    upstream = {
        "schema": SOURCE_SCHEMA, "source_commit": "test-head",
        "release_decision": "NOT_AUTHORIZED", "observed_at": earlier,
        "signals": [{"source": k, "state": "UNCHANGED" if k in {"codex", "claude"} else
                     "OBSERVED_UNTRIAGED"} for k in sorted(SOURCES)],
    }
    advisory = {
        "schema": SECURITY_SCHEMA, "source_commit": "test-head",
        "release_decision": "NOT_AUTHORIZED", "observed_at": earlier,
        "coverage": {k: "OBSERVED_SNAPSHOT" if k == "cisa-kev-mirror" else
                     "OBSERVED_RECENT_WINDOW_PAGES_1" for k in COVERAGE},
        "signals": [],
    }
    assert assemble(upstream, advisory, now, "test-head")["state"] == "SOURCE_SIGNALS_OBSERVED"
    advisory["signals"] = [{
        "ghsa_id": "GHSA-aaaa-bbbb-cccc", "package": "example",
        "ecosystem": "rust", "present_versions": ["1.2.3"],
        "cisa_kev_listed": True, "vendor_severity": "critical",
        "release_decision": "NOT_AUTHORIZED",
    }]
    report = assemble(upstream, advisory, now, "test-head")
    assert report["state"] == "TRIAGE_CANDIDATES"
    assert report["release_decision"] == "NOT_AUTHORIZED"
    assert report["advisory_candidates"][0]["applicability"] == "NOT_EVALUATED"
    advisory["coverage"]["github-reviewed-rust"] = "UNKNOWN:http-503"
    assert assemble(upstream, advisory, now, "test-head")["state"] == "UNKNOWN_COVERAGE"
    advisory["coverage"]["github-reviewed-rust"] = "OBSERVED_RECENT_WINDOW_PAGES_1"
    upstream["observed_at"] = (now - dt.timedelta(hours=49)).isoformat()
    advisory["observed_at"] = upstream["observed_at"]
    assert assemble(upstream, advisory, now, "test-head")["state"] == "STALE"
    upstream["observed_at"] = earlier
    advisory["observed_at"] = earlier
    for key, left, right in (
        ("head", "test-head", "other-head"),
        ("schema", SOURCE_SCHEMA, "wrong-schema"),
    ):
        current = dict(upstream)
        if key == "head":
            current["source_commit"] = right
        else:
            current["schema"] = right
        try:
            assemble(current, advisory, now, left)
            raise AssertionError(key + "-mismatch-accepted")
        except InvalidEvidence:
            pass
    dup = dict(upstream)
    dup["signals"] = dup["signals"][:-1] + [dup["signals"][0]]
    try:
        assemble(dup, advisory, now, "test-head")
        raise AssertionError("duplicate-source-accepted")
    except InvalidEvidence:
        pass
    print("RISK_EVIDENCE_ENVELOPE_SELF_TEST_PASS")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--advisories", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--source-head")
    parser.add_argument("--require-fresh-observed", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not args.upstream or not args.advisories or not args.output or not args.source_head:
        parser.error("upstream, advisories, output and source-head required")
    report = assemble(read_bounded(args.upstream, MAX_SOURCE_BYTES),
                      read_bounded(args.advisories, MAX_SECURITY_BYTES),
                      dt.datetime.now(dt.timezone.utc), args.source_head)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("RISK_EVIDENCE_STATE=" + report["state"])
    if args.require_fresh_observed and report["state"] in {"STALE", "UNKNOWN_COVERAGE"}:
        print("RISK_EVIDENCE_INPUT_NOT_QUALIFIED", file=sys.stderr)
        return 1
    # Scheduled observation may be UNKNOWN; preserve it instead of fabricating PASS.
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (InvalidEvidence, OSError) as error:
        print("RISK_EVIDENCE_CONTRACT_FAILURE:" + str(error), file=sys.stderr)
        sys.exit(2)
