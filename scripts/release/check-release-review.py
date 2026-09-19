#!/usr/bin/env python3
"""Validate the declared release review against the whole delta since the last published stable release."""

from __future__ import annotations

import argparse
import fnmatch
import json
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REVIEW = ROOT / "release/review.json"

CLASSIFIERS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("runtime", ("src/**",)),
    ("tests", ("tests/**", "fixtures/**", "fuzz/**")),
    ("dependencies", ("Cargo.toml", "Cargo.lock", "deny.toml")),
    (
        "ci_release",
        (
            ".github/workflows/**",
            ".github/dependabot.yml",
            ".github/scorecard.yml",
            "scripts/release/**",
            "scripts/check-public-boundary.sh",
            "packaging/**",
            "install.sh",
            "release/**",
        ),
    ),
    (
        "docs_public",
        (
            "README.md",
            "CHANGELOG.md",
            "SECURITY.md",
            "GOVERNANCE.md",
            "CONTRIBUTING.md",
            "docs/**",
        ),
    ),
)

SECURITY_PATTERNS = (
    "src/adapters/**",
    "src/catalog/**",
    "src/cli/**",
    "scripts/release/**",
    "scripts/check-public-boundary.sh",
    "packaging/**",
    ".github/workflows/**",
    "install.sh",
    "Cargo.toml",
    "Cargo.lock",
    "SECURITY.md",
)

PROVIDER_PATTERNS = (
    "src/adapters/**",
    "src/catalog/provider_inventory.rs",
    "src/catalog/plugin_surface.rs",
    "src/cli/info.rs",
    "src/cli/resource_options.rs",
    "release/qualification.json",
)

CONTRACT_PATTERNS = (
    "docs/release/RELEASE_CONTRACT.md",
    "scripts/release/**",
    "scripts/release/check-release-review.py",
    "scripts/release/check-provider-version-sync.py",
    "scripts/release/check-repository-release-policy.py",
    "scripts/release/push-release-tag.sh",
    "scripts/release/publish-release.sh",
    "scripts/release/local-release-smoke.sh",
    "scripts/release/post-publish-smoke.sh",
    "scripts/release/qualify-real-provider.sh",
    "scripts/release/verify-qualification.py",
    ".github/workflows/release-candidate.yml",
    ".github/workflows/release.yml",
    "tests/contracts/gate_contract.rs",
)


MACHINE_EVIDENCE = {
    "artifact-binding",
    "attestation",
    "dependency-sca",
    "full-regression",
    "real-provider",
    "whole-release-review",
}

SEMANTIC_EVIDENCE = {
    "contract-evolution-review",
    "public-truth-review",
    "security-review",
    "strategic-fit-review",
}

KNOWN_EVIDENCE = MACHINE_EVIDENCE | SEMANTIC_EVIDENCE

ALWAYS_EVIDENCE = {
    "contract-evolution-review",
    "strategic-fit-review",
    "whole-release-review",
}


def fail(message: str) -> None:
    raise SystemExit("RELEASE_REVIEW_BLOCKED:" + message)


def run(*args: str) -> str:
    proc = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    if proc.returncode != 0:
        fail(f"command:{' '.join(args)}:{proc.stderr.strip()}")
    return proc.stdout


def matches(path: str, patterns: tuple[str, ...]) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in patterns)


def classify(path: str) -> set[str]:
    classes = {name for name, patterns in CLASSIFIERS if matches(path, patterns)}
    if matches(path, SECURITY_PATTERNS):
        classes.add("security_boundary")
    return classes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-tag", required=True)
    parser.add_argument("--candidate", default="HEAD")
    args = parser.parse_args()

    try:
        review = json.loads(REVIEW.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"review-json:{exc}")

    if review.get("schema_version") != "clroom.release-review.v1":
        fail("schema")

    with (ROOT / "Cargo.toml").open("rb") as handle:
        package_version = tomllib.load(handle)["package"]["version"]

    if review.get("release_version") != package_version:
        fail("release-version")
    if review.get("previous_published_stable_tag") != args.base_tag:
        fail(
            "published-baseline:"
            f"declared={review.get('previous_published_stable_tag')}:actual={args.base_tag}"
        )

    base_sha = run("git", "rev-parse", f"{args.base_tag}^{{commit}}").strip()
    candidate_sha = run("git", "rev-parse", f"{args.candidate}^{{commit}}").strip()

    reviewed_digest = review.get("reviewed_content_digest")
    if (
        not isinstance(reviewed_digest, str)
        or len(reviewed_digest) != 64
        or any(ch not in "0123456789abcdef" for ch in reviewed_digest)
    ):
        fail("reviewed-content-digest")

    tree = subprocess.run(
        ["git", "ls-tree", "-r", "-z", candidate_sha],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    ).stdout
    digest = hashlib.sha256()
    for record in tree.split(b"\0"):
        if not record:
            continue
        try:
            metadata, path = record.split(b"\t", 1)
        except ValueError:
            fail("review-content-tree-record")
        if path == b"release/review.json":
            continue
        digest.update(metadata)
        digest.update(b"\t")
        digest.update(path)
        digest.update(b"\0")
    candidate_review_digest = digest.hexdigest()
    if candidate_review_digest != reviewed_digest:
        fail(
            "review-content-drift:"
            f"declared={reviewed_digest}:actual={candidate_review_digest}"
        )

    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base_sha, candidate_sha],
        cwd=ROOT,
        check=False,
    )
    if ancestor.returncode != 0:
        fail("base-not-ancestor")

    # Disable rename collapsing so both the removed and added path are classified.
    # A move across trust/change-class boundaries must not make the original
    # high-risk path disappear from release evidence requirements.
    changed = [
        line.strip()
        for line in run(
            "git",
            "diff",
            "--name-only",
            "--no-renames",
            f"{base_sha}..{candidate_sha}",
        ).splitlines()
        if line.strip()
    ]
    if not changed:
        fail("empty-release-delta")

    computed: set[str] = set()
    unknown: list[str] = []
    for path in changed:
        classes = classify(path)
        if not classes:
            unknown.append(path)
        computed.update(classes)
    if unknown:
        fail("unclassified-paths:" + ",".join(sorted(unknown)))

    declared_raw = review.get("declared_change_classes")
    if not isinstance(declared_raw, list) or not all(isinstance(x, str) for x in declared_raw):
        fail("declared-change-classes")
    declared = set(declared_raw)
    missing_classes = computed - declared
    stale_classes = declared - computed
    if missing_classes:
        fail("undeclared-change-classes:" + ",".join(sorted(missing_classes)))
    if stale_classes:
        fail("stale-declared-change-classes:" + ",".join(sorted(stale_classes)))

    evidence_raw = review.get("required_evidence")
    if not isinstance(evidence_raw, list) or not all(isinstance(x, str) for x in evidence_raw):
        fail("required-evidence")
    evidence = set(evidence_raw)
    unknown_evidence = evidence - KNOWN_EVIDENCE
    if unknown_evidence:
        fail("unknown-evidence:" + ",".join(sorted(unknown_evidence)))

    required = set(ALWAYS_EVIDENCE)
    if "runtime" in computed:
        required.add("full-regression")
    if "dependencies" in computed:
        required.add("dependency-sca")
    if "docs_public" in computed:
        required.add("public-truth-review")
    if "security_boundary" in computed:
        required.add("security-review")
    if "ci_release" in computed:
        required.update({"artifact-binding", "attestation"})
    if any(matches(path, PROVIDER_PATTERNS) for path in changed):
        required.add("real-provider")

    missing_evidence = required - evidence
    if missing_evidence:
        fail("missing-required-evidence:" + ",".join(sorted(missing_evidence)))

    outcome = review.get("strategic_product_outcome")
    if not isinstance(outcome, str) or len(outcome.strip()) < 20:
        fail("strategic-product-outcome")

    evolution = review.get("contract_evolution")
    if not isinstance(evolution, dict) or evolution.get("reviewed") is not True:
        fail("contract-evolution-review")
    if evolution.get("result") not in {"expanded", "no_change"}:
        fail("contract-evolution-result")

    contract_changed = any(matches(path, CONTRACT_PATTERNS) for path in changed)
    if bool(evolution.get("release_contract_changed")) != contract_changed:
        fail("contract-change-declaration")
    if contract_changed and evolution.get("result") != "expanded":
        fail("contract-change-requires-expansion-review")

    if evolution.get("result") == "expanded":
        promoted = evolution.get("promoted_controls")
        if not isinstance(promoted, list) or not promoted or not all(
            isinstance(item, str) and item.strip() for item in promoted
        ):
            fail("contract-evolution-promoted-controls")

    commit_count = run("git", "rev-list", "--count", f"{base_sha}..{candidate_sha}").strip()
    print(f"RELEASE_REVIEW_PASS base={args.base_tag} base_sha={base_sha}")
    print(f"CANDIDATE_SHA={candidate_sha}")
    print(f"REVIEWED_CONTENT_DIGEST={candidate_review_digest}")
    print(f"COMMITS={commit_count}")
    print(f"CHANGED_FILES={len(changed)}")
    print("CHANGE_CLASSES=" + ",".join(sorted(computed)))
    print("REQUIRED_EVIDENCE=" + ",".join(sorted(required)))
    print("CONTRACT_EVOLUTION=" + str(evolution.get("result")))


if __name__ == "__main__":
    main()
