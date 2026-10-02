#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "schemas/release/release-contract-v1.json"
CHANGELOG = ROOT / "CHANGELOG.md"
CANONICAL_INSTALL_URL = "https://github.com/y-sor/clean-room-launcher/releases/latest/download/install.sh"
SCHEMA = "clroom.publish-preview.v1"
SEMVER_TOKEN = re.compile(
    r"(?<![0-9])(?P<prefix>v?)(?P<version>[0-9]+\.[0-9]+\.[0-9]+)(?P<plus>\+)?(?![0-9])"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_body(text: str) -> str:
    return text.rstrip() + "\n"


def candidate_section(lines: list[str], version: str) -> list[tuple[int, str]]:
    prefix = f"## [{version}] - "
    matches = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one changelog section for {version}")
    start = matches[0] + 1
    end = len(lines)
    for index in range(start, len(lines)):
        if lines[index].startswith("## ["):
            end = index
            break
    return [(index + 1, lines[index]) for index in range(start, end)]


def provider_policy() -> dict[str, object]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    policy = contract.get("policy", {}).get("public_doc_version_inventory")
    if not isinstance(policy, dict):
        raise ValueError("public-doc-version-policy")
    scoped = policy.get("candidate_scoped_historical_paths")
    if scoped != ["CHANGELOG.md"]:
        raise ValueError("candidate-scoped-historical-paths")
    return policy


def provider_claim_violations(
    section: list[tuple[int, str]],
    codex_version: str,
    claude_version: str,
    policy: dict[str, object],
) -> list[str]:
    pins = {"codex": codex_version, "claude": claude_version}
    allow = policy.get("allowed_noncurrent_provider_versions")
    if not isinstance(allow, dict):
        raise ValueError("provider-allowlist")
    violations: list[str] = []
    for line_number, line in section:
        lower = line.lower()
        providers = {provider for provider in ("codex", "claude") if provider in lower}
        if not providers:
            continue
        allowed: set[str] = set()
        for provider in providers:
            allowed.add(pins[provider])
            configured = allow.get(provider)
            if not isinstance(configured, dict):
                raise ValueError(f"provider-allowlist:{provider}")
            allowed.update(configured)
        for match in SEMVER_TOKEN.finditer(line):
            if match.group("prefix") == "v":
                continue
            version = match.group("version")
            if version not in allowed:
                violations.append(
                    f"line={line_number}:version={version}:allowed={','.join(sorted(allowed))}"
                )
    return violations


def source_semantic_check(version: str, codex_version: str, claude_version: str) -> str:
    section = candidate_section(
        CHANGELOG.read_text(encoding="utf-8").splitlines(), version
    )
    violations = provider_claim_violations(
        section, codex_version, claude_version, provider_policy()
    )
    if violations:
        raise ValueError("candidate-provider-drift:" + "|".join(violations))
    return "\n".join(line for _, line in section).strip()


def expected_preview(
    stage: Path,
    version: str,
    source_head: str,
    source_tree: str,
    codex_version: str,
    claude_version: str,
) -> dict[str, object]:
    section_text = source_semantic_check(version, codex_version, claude_version)
    notes_path = stage / "release-notes.md"
    if not notes_path.is_file():
        raise ValueError("release-notes-missing")
    notes = canonical_body(notes_path.read_text(encoding="utf-8"))
    if not notes.startswith(section_text + "\n\n"):
        raise ValueError("release-notes-not-current-candidate-section")
    artifact = f"clean-room-launcher-v{version}-aarch64-apple-darwin.tar.gz"
    if CANONICAL_INSTALL_URL not in notes:
        raise ValueError("canonical-install-url")
    if artifact not in notes:
        raise ValueError("artifact-name")
    tag = f"v{version}"
    prerelease = "-rc." in version
    return {
        "schema_version": SCHEMA,
        "release_version": version,
        "source_head": source_head,
        "source_tree": source_tree,
        "tag_name": tag,
        "title": f"{tag} — Clean Room Launcher",
        "draft": True,
        "prerelease": prerelease,
        "release_notes_sha256": sha256_bytes(notes.encode("utf-8")),
        "candidate_changelog_sha256": sha256_bytes(
            (section_text + "\n").encode("utf-8")
        ),
        "semantic_validation": "PASS",
        "provider_claims_validation": "PASS",
        "canonical_install_url": CANONICAL_INSTALL_URL,
        "providers": {
            "codex": codex_version,
            "claude": claude_version,
        },
        "expected_release_assets": sorted(
            [
                artifact,
                f"{artifact}.provenance.sigstore.json",
                f"{artifact}.sbom.sigstore.json",
                "SHA256SUMS",
                "install.sh",
                "sbom.cdx.json",
            ]
        ),
        "manual_draft_repair": "FORBIDDEN",
    }


def verify_or_write(
    stage: Path,
    version: str,
    source_head: str,
    source_tree: str,
    codex_version: str,
    claude_version: str,
    write_preview: bool,
) -> None:
    expected = expected_preview(
        stage, version, source_head, source_tree, codex_version, claude_version
    )
    preview_path = stage / "publish-preview.json"
    if write_preview:
        preview_path.write_text(
            json.dumps(expected, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    if not preview_path.is_file():
        raise ValueError("publish-preview-missing")
    actual = json.loads(preview_path.read_text(encoding="utf-8"))
    if actual != expected:
        raise ValueError("publish-preview-drift")


def self_test() -> None:
    policy = {
        "allowed_noncurrent_provider_versions": {
            "codex": {"0.147.0": "minimum"},
            "claude": {"2.1.223": "minimum"},
        }
    }
    current = [(1, "Codex 0.160.0 and Claude Code 2.1.287")]
    if provider_claim_violations(current, "0.160.0", "2.1.287", policy):
        raise SystemExit("PUBLISHABLE_SURFACE_SELF_TEST_FAIL:CURRENT")
    historical_floor = [(1, "Codex 0.147.0 minimum; Claude 2.1.223 minimum")]
    if provider_claim_violations(historical_floor, "0.160.0", "2.1.287", policy):
        raise SystemExit("PUBLISHABLE_SURFACE_SELF_TEST_FAIL:ALLOWLIST")
    stale = [(1, "Codex 0.159.0 and Claude Code 2.1.284")]
    if not provider_claim_violations(stale, "0.160.0", "2.1.287", policy):
        raise SystemExit("PUBLISHABLE_SURFACE_SELF_TEST_FAIL:STALE")
    if canonical_body("body\n\n") != "body\n":
        raise SystemExit("PUBLISHABLE_SURFACE_SELF_TEST_FAIL:BODY_NORMALIZATION")
    print("PUBLISHABLE_SURFACE_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--source-only", action="store_true")
    parser.add_argument("--write-preview", action="store_true")
    parser.add_argument("--dir")
    parser.add_argument("--version")
    parser.add_argument("--source-head")
    parser.add_argument("--source-tree")
    parser.add_argument("--codex-version")
    parser.add_argument("--claude-version")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    required = (
        args.version,
        args.codex_version,
        args.claude_version,
    )
    if not all(required):
        raise SystemExit("PUBLISHABLE_SURFACE_BLOCKED:REQUIRED_ARGUMENTS")
    try:
        if args.source_only:
            source_semantic_check(
                args.version, args.codex_version, args.claude_version
            )
            print(
                f"PUBLISHABLE_SOURCE_SEMANTIC_PASS version={args.version} "
                f"codex={args.codex_version} claude={args.claude_version}"
            )
            return 0
        if not all((args.dir, args.source_head, args.source_tree)):
            raise ValueError("stage-arguments")
        verify_or_write(
            Path(args.dir),
            args.version,
            args.source_head,
            args.source_tree,
            args.codex_version,
            args.claude_version,
            args.write_preview,
        )
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"PUBLISHABLE_SURFACE_BLOCKED:{exc}") from exc
    print(
        f"PUBLISHABLE_SURFACE_PASS version={args.version} "
        f"source={args.source_head}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
