#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CONTROLLED_WORKFLOWS = (
    ".github/workflows/ci.yml",
    ".github/workflows/codeql.yml",
    ".github/workflows/dependency-review.yml",
    ".github/workflows/fuzz.yml",
    ".github/workflows/indexnow.yml",
    ".github/workflows/release-candidate.yml",
    ".github/workflows/release-promotion-rehearsal.yml",
    ".github/workflows/release.yml",
    ".github/workflows/scorecard.yml",
)
CODEQL_ACTIONS = {"init", "analyze", "upload-sarif"}
AUTOMATION_MARKERS = (
    "AUTOMATION_CHAIN_RELEASE_CANDIDATE_TO_PROMOTION_REHEARSAL",
    "AUTOMATION_CHAIN_TAG_TO_DRAFT",
    "AUTOMATION_CHAIN_NO_AUTO_PUBLISH",
)
CODEQL_RE = re.compile(
    r"uses:\s+github/codeql-action/(init|analyze|upload-sarif)@([0-9a-f]{40})\s+#\s+v([0-9]+\.[0-9]+\.[0-9]+)"
)


def read(root: Path, rel: str) -> str:
    return (root / rel).read_text(encoding="utf-8")


def job_blocks(text: str) -> dict[str, str]:
    lines = text.splitlines()
    blocks: dict[str, list[str]] = {}
    in_jobs = False
    current: str | None = None
    for line in lines:
        if line == "jobs:":
            in_jobs = True
            current = None
            continue
        if not in_jobs:
            continue
        if line and not line.startswith(" "):
            break
        match = re.fullmatch(r"  ([A-Za-z0-9_-]+):", line)
        if match:
            current = match.group(1)
            blocks[current] = [line]
            continue
        if current is not None:
            blocks[current].append(line)
    return {name: "\n".join(lines) for name, lines in blocks.items()}


def validate_codeql_records(records: list[tuple[str, str, str]]) -> list[str]:
    errors: list[str] = []
    present = {action for action, _, _ in records}
    missing = sorted(CODEQL_ACTIONS - present)
    if missing:
        errors.append("CODEQL_FAMILY_MISSING:" + ",".join(missing))
    tuples = {(sha, version) for _, sha, version in records}
    if len(tuples) != 1:
        errors.append("CODEQL_FAMILY_DIVERGED")
    return errors


def require(errors: list[str], condition: bool, code: str) -> None:
    if not condition:
        errors.append(code)


def check(root: Path) -> list[str]:
    errors: list[str] = []

    workflow_text = {path: read(root, path) for path in CONTROLLED_WORKFLOWS}
    records: list[tuple[str, str, str]] = []
    for text in workflow_text.values():
        records.extend(CODEQL_RE.findall(text))
    errors.extend(validate_codeql_records(records))

    dependabot = read(root, ".github/dependabot.yml")
    require(errors, "codeql-family:" in dependabot, "DEPENDABOT_CODEQL_GROUP_MISSING")
    require(
        errors,
        '"github/codeql-action/*"' in dependabot or "'github/codeql-action/*'" in dependabot,
        "DEPENDABOT_CODEQL_PATTERN_MISSING",
    )

    release_candidate = workflow_text[".github/workflows/release-candidate.yml"]
    require(errors, "jsonschema==" not in release_candidate, "UNUSED_JSONSCHEMA_PROVISIONING")
    require(errors, "clroom-supply-chain-verifier" not in release_candidate, "UNUSED_PYPI_VERIFIER")

    fuzz = workflow_text[".github/workflows/fuzz.yml"]
    require(errors, (root / "fuzz/Cargo.lock").is_file(), "FUZZ_LOCKFILE_MISSING")
    require(errors, "generate-lockfile" not in fuzz, "FUZZ_RUNTIME_LOCK_GENERATION")
    require(
        errors,
        "fetch --locked --manifest-path fuzz/Cargo.toml" in fuzz,
        "FUZZ_LOCKED_FETCH_MISSING",
    )
    require(errors, "CARGO_NET_OFFLINE: true" in fuzz, "FUZZ_OFFLINE_EXECUTION_MISSING")

    ci_jobs = job_blocks(workflow_text[".github/workflows/ci.yml"])
    require(errors, "harness-contract" in ci_jobs, "CI_HARNESS_JOB_MISSING")
    required = ci_jobs.get("required", "")
    require(errors, "name: Required" in required, "CI_REQUIRED_NAME")
    require(
        errors,
        "needs: [harness-contract, target-matrix, docs-discovery, qualified-target-lanes]" in required,
        "CI_REQUIRED_TOPOLOGY",
    )
    require(errors, "always()" in required, "CI_REQUIRED_ALWAYS")

    release_jobs = job_blocks(release_candidate)
    eligibility = release_jobs.get("release-eligibility", "")
    require(errors, "runs-on: ubuntu-latest" in eligibility, "RELEASE_ELIGIBILITY_RUNNER")
    require(errors, "check-release-contract.py --self-test" in eligibility, "RELEASE_ELIGIBILITY_SELF_TEST")
    require(errors, "check-release-contract.py --report" in eligibility, "RELEASE_ELIGIBILITY_SEAL")
    readiness = release_jobs.get("release-readiness", "")
    require(errors, "needs: release-eligibility" in readiness, "RELEASE_READINESS_NEEDS_ELIGIBILITY")
    stage = release_jobs.get("pretag-stage", "")
    require(
        errors,
        "needs: [release-eligibility, release-readiness]" in stage,
        "PRETAG_STAGE_TOPOLOGY",
    )
    attest = release_jobs.get("pretag-attestation-rehearsal", "")
    require(
        errors,
        "needs: [release-eligibility, release-readiness, pretag-stage]" in attest,
        "PRETAG_ATTEST_TOPOLOGY",
    )
    release_required = release_jobs.get("release-required", "")
    require(errors, "name: Release required" in release_required, "RELEASE_REQUIRED_NAME")
    require(
        errors,
        "needs: [release-eligibility, release-readiness, pretag-stage, pretag-attestation-rehearsal, promotion-prepare-rehearsal]" in release_required,
        "RELEASE_REQUIRED_TOPOLOGY",
    )
    require(errors, "if: always()" in release_required, "RELEASE_REQUIRED_ALWAYS")

    docs = read(root, "docs/release/RELEASE_CONTRACT.md")
    for marker in AUTOMATION_MARKERS:
        require(errors, marker in docs, "AUTOMATION_MARKER_MISSING:" + marker)

    promotion = workflow_text[".github/workflows/release-promotion-rehearsal.yml"]
    require(errors, "workflow_call:" in promotion, "PROMOTION_CHAIN_REUSABLE_TRIGGER")
    require(errors, "workflow_run:" not in promotion, "PROMOTION_CHAIN_PRIVILEGED_TRIGGER_FORBIDDEN")
    require(errors, "inputs.source_sha" not in promotion, "PROMOTION_CHAIN_UNTRUSTED_SOURCE_INPUT")
    require(errors, "ref: ${{ github.sha }}" in promotion, "PROMOTION_CHAIN_TRUSTED_CHECKOUT")
    require(errors, "SOURCE_SHA: ${{ github.sha }}" in promotion, "PROMOTION_CHAIN_TRUSTED_SOURCE")
    require(
        errors,
        "uses: ./.github/workflows/release-promotion-rehearsal.yml" in release_candidate,
        "PROMOTION_CHAIN_CALLER_MISSING",
    )
    promotion_job = release_jobs.get("promotion-prepare-rehearsal", "")
    require(errors, "github.event_name == 'push'" in promotion_job, "PROMOTION_CHAIN_PUSH_ONLY")
    require(errors, "github.ref == 'refs/heads/main'" in promotion_job, "PROMOTION_CHAIN_MAIN_ONLY")
    require(errors, "needs.release-eligibility.outputs.lifecycle == 'ACTIVE_CANDIDATE'" in promotion_job, "PROMOTION_CHAIN_ACTIVE_ONLY")
    require(
        errors,
        "promotion-prepare-rehearsal" in release_required,
        "RELEASE_REQUIRED_PROMOTION_TOPOLOGY",
    )
    lifecycle_guard = promotion.find("resolve-release-lifecycle.py")
    stage_resolver = promotion.find("bash scripts/release/resolve-pretag-stage.sh")
    require(
        errors,
        lifecycle_guard >= 0 and stage_resolver >= 0 and lifecycle_guard < stage_resolver,
        "PROMOTION_CHAIN_LIFECYCLE_GUARD",
    )
    require(
        errors,
        "PROMOTION_PREPARE_REHEARSAL_SKIPPED lifecycle=POST_PUBLISH" in promotion,
        "PROMOTION_CHAIN_POST_PUBLISH_NOOP",
    )
    require(errors, "contents: write" not in promotion, "PROMOTION_CHAIN_WRITE_PERMISSION")

    release = workflow_text[".github/workflows/release.yml"]
    require(errors, 'tags:\n      - "v*"' in release, "RELEASE_TAG_TRIGGER")
    require(errors, 'release create "$tag" --draft' in release, "RELEASE_DRAFT_ONLY")
    require(errors, "--draft=false" not in release, "RELEASE_AUTO_PUBLISH_FORBIDDEN")
    require(errors, "gh release publish" not in release, "RELEASE_AUTO_PUBLISH_COMMAND")

    for path, text in workflow_text.items():
        require(errors, re.search(r"(?m)^concurrency:\s*$", text) is not None, f"WORKFLOW_CONCURRENCY:{path}")
        blocks = job_blocks(text)
        require(errors, bool(blocks), f"WORKFLOW_JOBS:{path}")
        for job, block in blocks.items():
            if re.search(r"(?m)^    uses:\s+\./\.github/workflows/", block):
                continue
            require(errors, "timeout-minutes:" in block, f"JOB_TIMEOUT:{path}:{job}")

    return errors


def self_test() -> None:
    sha_a = "a" * 40
    sha_b = "b" * 40
    clean = [("init", sha_a, "4.38.0"), ("analyze", sha_a, "4.38.0"), ("upload-sarif", sha_a, "4.38.0")]
    if validate_codeql_records(clean):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:CLEAN_CODEQL")
    split = [("init", sha_b, "4.38.1"), ("analyze", sha_a, "4.38.0"), ("upload-sarif", sha_a, "4.38.0")]
    if "CODEQL_FAMILY_DIVERGED" not in validate_codeql_records(split):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:SPLIT_CODEQL")
    missing = [("init", sha_a, "4.38.0"), ("analyze", sha_a, "4.38.0")]
    if not any(item.startswith("CODEQL_FAMILY_MISSING:") for item in validate_codeql_records(missing)):
        raise SystemExit("HARNESS_SELF_TEST_FAIL:MISSING_CODEQL")
    print("HARNESS_CONTRACT_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    errors = check(args.root.resolve())
    if errors:
        print("HARNESS_CONTRACT_BLOCKED")
        for error in errors:
            print(error)
        return 1
    print("HARNESS_CONTRACT_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
