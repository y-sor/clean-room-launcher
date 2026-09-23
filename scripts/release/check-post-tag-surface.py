#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def fail(reason: str) -> "NoReturn":
    raise SystemExit(f"POST_TAG_SURFACE_BLOCKED:{reason}")


def main() -> int:
    workflows = ROOT / ".github/workflows"
    release_path = workflows / "release.yml"
    release = release_path.read_text(encoding="utf-8")

    for path in sorted(workflows.glob("*.yml")):
        if path == release_path:
            continue
        text = path.read_text(encoding="utf-8")
        if 'tags:\n' in text and '"v*"' in text:
            fail(f"NON_RELEASE_TAG_TRIGGER:{path.name}")

    forbidden_release = {
        "cargo test": "TEST_AFTER_TAG",
        "cargo build": "BUILD_AFTER_TAG",
        "cargo fetch": "FETCH_AFTER_TAG",
        "provision-provider-canaries": "PROVIDER_PROVISION_AFTER_TAG",
        "qualify-real-provider": "PROVIDER_QUALIFICATION_AFTER_TAG",
        "local-codex-plugin-activation-smoke": "CODEX_RUNTIME_AFTER_TAG",
        "local-plugin-activation-smoke": "CLAUDE_RUNTIME_AFTER_TAG",
        "check-provider-pins.sh": "PROVIDER_LATEST_AFTER_TAG",
        "/immutable-releases": "ADMIN_POLICY_AFTER_TAG",
        "npm view": "REGISTRY_LATEST_AFTER_TAG",
        "npm pack": "REGISTRY_PACKAGE_AFTER_TAG",
    }
    for needle, reason in forbidden_release.items():
        if needle in release:
            fail(reason)

    required_release = (
        "resolve-release-stage.sh",
        "verify-release-stage.py",
        "actions/attest@",
        'gh release upload "$tag" release-artifacts/* --clobber',
        "Reconcile uploaded Draft bytes",
    )
    for needle in required_release:
        if needle not in release:
            fail(f"PROMOTION_CONTRACT:{needle}")

    verifier = (ROOT / "scripts/release/verify-draft-release.sh").read_text(encoding="utf-8")
    for needle, reason in (
        ("check-provider-pins.sh", "PREPUBLISH_PROVIDER_LATEST"),
        ("local-codex-plugin-activation-smoke", "PREPUBLISH_CODEX_RUNTIME"),
        ("local-plugin-activation-smoke", "PREPUBLISH_CLAUDE_RUNTIME"),
        ("resolve-codex-draft-evidence.sh", "PREPUBLISH_CODEX_DRAFT_EVIDENCE"),
    ):
        if needle in verifier:
            fail(reason)

    tag = (ROOT / "scripts/release/push-release-tag.sh").read_text(encoding="utf-8")
    for needle in (
        "resolve-release-stage.sh",
        "verify-release-stage.py",
        "immutable-releases",
        "STAGE_CLAUDE_EVIDENCE",
    ):
        if needle not in tag:
            fail(f"PRETAG_CLOSURE:{needle}")

    print("POST_TAG_SURFACE_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
