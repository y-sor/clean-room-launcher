#!/usr/bin/env python3
"""Verify the external GitHub tag ruleset required by the CLROOM release contract."""

from __future__ import annotations

import argparse
import json
import os
import subprocess

REPO = os.environ.get("GITHUB_REPOSITORY", "y-sor/clean-room-launcher")
TAG_PATTERN = "refs/tags/v*"


def fail(message: str) -> None:
    raise SystemExit("RELEASE_REPOSITORY_POLICY_BLOCKED:" + message)


def gh_json(endpoint: str):
    proc = subprocess.run(
        ["gh", "api", endpoint],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        fail("github-api:" + proc.stderr.strip())
    try:
        return json.loads(proc.stdout)
    except ValueError as exc:
        fail(f"github-json:{exc}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("visible", "strict"),
        default="strict",
        help=(
            "visible checks rules exposed to read-only tokens; strict additionally "
            "requires bypass_actors=[] and is mandatory immediately before tag push"
        ),
    )
    args = parser.parse_args()

    rulesets = gh_json(f"repos/{REPO}/rulesets")
    if not isinstance(rulesets, list):
        fail("rulesets-response")

    candidates = [
        item
        for item in rulesets
        if isinstance(item, dict)
        and item.get("target") == "tag"
        and item.get("enforcement") == "active"
    ]
    if not candidates:
        fail("active-tag-ruleset-missing")

    structural = []
    strict = []
    for summary in candidates:
        ruleset_id = summary.get("id")
        if not isinstance(ruleset_id, int):
            continue
        detail = gh_json(f"repos/{REPO}/rulesets/{ruleset_id}")
        includes = detail.get("conditions", {}).get("ref_name", {}).get("include", [])
        rule_types = {
            rule.get("type")
            for rule in detail.get("rules", [])
            if isinstance(rule, dict)
        }
        if TAG_PATTERN not in includes or not {"update", "deletion"}.issubset(rule_types):
            continue
        structural.append(detail)

        # GitHub intentionally omits bypass_actors unless the caller has write
        # access to the ruleset. A read-only CI token therefore cannot prove
        # the no-bypass invariant. That proof belongs to strict action-time
        # verification with the Owner-authorized gh identity.
        if "bypass_actors" in detail:
            bypass = detail.get("bypass_actors")
            if isinstance(bypass, list) and not bypass:
                strict.append(detail)

    if not structural:
        fail("protective-tag-ruleset-missing")

    if args.mode == "strict":
        if not any("bypass_actors" in ruleset for ruleset in structural):
            fail("bypass-actors-not-visible-to-caller")
        if not strict:
            fail("no-no-bypass-protective-tag-ruleset")

    accepted = strict if args.mode == "strict" else structural
    ids = ",".join(str(ruleset.get("id")) for ruleset in accepted)
    print(
        "RELEASE_REPOSITORY_POLICY_PASS "
        f"mode={args.mode} repo={REPO} "
        f"tag_rulesets={ids} pattern={TAG_PATTERN}"
    )


if __name__ == "__main__":
    main()
