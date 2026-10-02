#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

SURFACES = {
    "schema": ROOT / "schemas/release/release-contract-v1.json",
    "release_contract": ROOT / "scripts/release/check-release-contract.py",
    "notes_verifier": ROOT / "scripts/release/verify-release-notes.py",
    "stage": ROOT / "scripts/release/stage-release.sh",
    "stage_verifier": ROOT / "scripts/release/verify-pretag-stage.py",
    "tag": ROOT / "scripts/release/push-release-tag.sh",
    "workflow": ROOT / ".github/workflows/release.yml",
    "draft_verifier": ROOT / "scripts/release/verify-draft-release.sh",
    "publisher": ROOT / "scripts/release/publish-release.sh",
}

REQUIRED = {
    "schema": (
        '"candidate_changelog_version_inventory"',
        '"release_notes_semantic_validation": "required"',
        '"publishable_surface_manifest": "required"',
        '"draft_body_exact_stage": "required"',
        '"guarded_publish_helper": "required"',
    ),
    "release_contract": (
        "validate_candidate_changelog_versions",
        "RELEASE_CONTRACT_SELF_TEST_FAIL_STALE_CURRENT_CHANGELOG_PROVIDER",
        "RELEASE_CONTRACT_SELF_TEST_FAIL_UNCLASSIFIED_CURRENT_CHANGELOG_VERSION",
        "CANDIDATE_CHANGELOG_VERSION_DRIFT",
    ),
    "notes_verifier": (
        "clroom.release-facts.v1",
        "candidate_body",
        "release notes body is not the exact candidate changelog section",
        "RELEASE_NOTES_SELF_TEST_FAIL:BODY_DRIFT",
    ),
    "stage": (
        "verify-release-notes.py",
        "release-facts.json",
        '"release_notes_semantic_validation": "PASS"',
        '"publishable_surface_manifest": "PASS"',
        '"publishable_surface_semantics"',
    ),
    "stage_verifier": (
        '"publishable_surface_semantics"',
        '"release_notes_semantic_validation": "PASS"',
        '"publishable_surface_manifest": "PASS"',
        '"release-facts.json"',
        "PRETAG_STAGE_BLOCKED:RELEASE_FACTS",
    ),
    "tag": (
        "release-notes-sha256",
        "PUBLIC_PREVIEW_APPROVAL_BOUND",
        "OWNER_APPROVAL_PUBLIC_PREVIEW",
    ),
    "workflow": (
        "body,assets",
        "release-body-drift",
        "DRAFT_PROMOTION_RECONCILE_PASS",
    ),
    "draft_verifier": (
        '--json tagName,name,isDraft,isPrerelease,body,assets',
        'raise SystemExit("notes")',
    ),
    "publisher": (
        "verify-draft-release.sh",
        "PUBLIC_PREVIEW_APPROVAL_BOUND",
        'gh release edit "$tag" --draft=false --verify-tag',
        "PUBLISH_OUTCOME_UNKNOWN",
        "RELEASE_PUBLISH_PASS",
    ),
}

FORBIDDEN = {
    "workflow": (
        "--draft=false",
        "publish-release.sh",
    ),
}

def check_text(name: str, text: str) -> list[str]:
    errors: list[str] = []
    for token in REQUIRED.get(name, ()):
        if token not in text:
            errors.append(f"missing:{name}:{token}")
    for token in FORBIDDEN.get(name, ()):
        if token in text:
            errors.append(f"forbidden:{name}:{token}")
    return errors

def check(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for name, canonical in SURFACES.items():
        path = root / canonical.relative_to(ROOT)
        if not path.is_file():
            errors.append(f"surface-missing:{name}:{path.relative_to(root)}")
            continue
        errors.extend(check_text(name, path.read_text(encoding="utf-8")))
    return errors

def self_test() -> None:
    for name, tokens in REQUIRED.items():
        if not tokens:
            continue
        positive = "\n".join(tokens)
        if check_text(name, positive):
            raise SystemExit(f"PUBLISHABLE_SURFACE_SELF_TEST_FAIL:POSITIVE:{name}")
        missing = "\n".join(tokens[1:])
        errors = check_text(name, missing)
        if not any(error.startswith(f"missing:{name}:") for error in errors):
            raise SystemExit(f"PUBLISHABLE_SURFACE_SELF_TEST_FAIL:MISSING:{name}")
    bad_workflow = "\n".join(REQUIRED["workflow"]) + "\n--draft=false\n"
    errors = check_text("workflow", bad_workflow)
    if not any(error.startswith("forbidden:workflow:") for error in errors):
        raise SystemExit("PUBLISHABLE_SURFACE_SELF_TEST_FAIL:AUTO_PUBLISH")
    print("PUBLISHABLE_SURFACE_CONTRACT_SELF_TEST_PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    errors = check()
    if errors:
        print("\n".join(f"PUBLISHABLE_SURFACE_CONTRACT_BLOCKED:{item}" for item in errors))
        return 1
    print("PUBLISHABLE_SURFACE_CONTRACT_PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
