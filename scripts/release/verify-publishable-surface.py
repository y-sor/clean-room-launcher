#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "schemas/release/release-contract-v1.json"
CHANGELOG = ROOT / "CHANGELOG.md"
CANONICAL_INSTALL_URL = "https://github.com/y-sor/clean-room-launcher/releases/latest/download/install.sh"
SCHEMA = "clroom.publish-preview.v1"
HEADING_RE = re.compile(r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\] - \d{4}-\d{2}-\d{2}$")
SEMVER_TOKEN = re.compile(
    r"(?<![0-9])(?P<prefix>v?)(?P<version>[0-9]+\.[0-9]+\.[0-9]+)(?P<plus>\+)?(?![0-9])"
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_body(text: str) -> str:
    return text.rstrip() + "\n"


def release_range(lines: list[str], candidate: str, baseline: str) -> tuple[list[tuple[int, str]], list[str]]:
    candidate_prefix = f"## [{candidate}] - "
    baseline_prefix = f"## [{baseline}] - "
    candidate_matches = [i for i, line in enumerate(lines) if line.startswith(candidate_prefix)]
    baseline_matches = [i for i, line in enumerate(lines) if line.startswith(baseline_prefix)]
    if len(candidate_matches) != 1:
        raise ValueError(f"expected exactly one changelog section for {candidate}")
    if len(baseline_matches) != 1:
        raise ValueError(f"expected exactly one published baseline section for {baseline}")
    start = candidate_matches[0]
    end = baseline_matches[0]
    if start >= end:
        raise ValueError("published baseline must appear after candidate in changelog")
    selected = [(index + 1, lines[index]) for index in range(start, end)]
    versions = [
        match.group(1)
        for _, line in selected
        if (match := HEADING_RE.fullmatch(line)) is not None
    ]
    if not versions or versions[0] != candidate or baseline in versions:
        raise ValueError("release changelog range is not candidate-through-baseline-exclusive")
    return selected, versions


def review_baseline(version: str) -> str:
    path = ROOT / f"reports/release/v{version}-review.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    baseline = data.get("baseline_release")
    if not isinstance(baseline, str) or re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", baseline) is None:
        raise ValueError("review-published-baseline")
    return baseline


def provider_policy() -> dict[str, object]:
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    policy = contract.get("policy", {}).get("public_doc_version_inventory")
    if not isinstance(policy, dict):
        raise ValueError("public-doc-version-policy")
    scoped = policy.get("candidate_scoped_historical_paths")
    if scoped != ["CHANGELOG.md"]:
        raise ValueError("candidate-scoped-historical-paths")
    if contract.get("policy", {}).get("release_notes_scope") != "published_baseline_exclusive_through_candidate":
        raise ValueError("release-notes-scope")
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


def footer(artifact: str) -> str:
    return f"""## Install

```sh
curl --proto '=https' --tlsv1.2 -fsSL {CANONICAL_INSTALL_URL} | sh
```

## Download and verification

- `install.sh` — one-line macOS Apple Silicon installer
- `{artifact}` — macOS Apple Silicon archive
- `SHA256SUMS` — SHA-256 digests for the archive, SBOM, and installer
- `sbom.cdx.json` — CycloneDX SBOM bound to the archive digest
- `{artifact}.provenance.sigstore.json` — release-visible Sigstore bundle for build provenance of the exact archive, SBOM, and installer bytes
- `{artifact}.sbom.sigstore.json` — release-visible Sigstore bundle for the CycloneDX SBOM attestation bound to the exact archive bytes

Verify the downloaded archive against its release-visible provenance bundle:

```sh
gh attestation verify "{artifact}" \
  -R y-sor/clean-room-launcher \
  --bundle "{artifact}.provenance.sigstore.json" \
  --signer-workflow y-sor/clean-room-launcher/.github/workflows/release.yml
```

The distributed archive is currently unsigned at the Apple platform-signing layer. Verify the checksums and release-visible GitHub attestation bundles before use.""".strip()


def source_semantic_check(
    version: str, codex_version: str, claude_version: str
) -> tuple[str, list[str], str]:
    baseline_tag = review_baseline(version)
    lines = CHANGELOG.read_text(encoding="utf-8").splitlines()
    selected, versions = release_range(lines, version, baseline_tag[1:])
    violations = provider_claim_violations(
        selected, codex_version, claude_version, provider_policy()
    )
    if violations:
        raise ValueError("release-range-provider-drift:" + "|".join(violations))
    text = "\n".join(line for _, line in selected).strip()
    if not text:
        raise ValueError("release-range-empty")
    return text, versions, baseline_tag


def expected_preview(
    stage: Path,
    version: str,
    source_head: str,
    source_tree: str,
    codex_version: str,
    claude_version: str,
) -> dict[str, object]:
    range_text, included_versions, baseline_tag = source_semantic_check(
        version, codex_version, claude_version
    )
    notes_path = stage / "release-notes.md"
    if not notes_path.is_file():
        raise ValueError("release-notes-missing")
    notes = canonical_body(notes_path.read_text(encoding="utf-8"))
    artifact = f"clean-room-launcher-v{version}-aarch64-apple-darwin.tar.gz"
    expected_notes = canonical_body(range_text + "\n\n" + footer(artifact))
    if notes != expected_notes:
        raise ValueError("release-notes-not-exact-published-baseline-range")
    tag = f"v{version}"
    prerelease = "-rc." in version
    return {
        "schema_version": SCHEMA,
        "release_version": version,
        "published_baseline": baseline_tag,
        "included_changelog_versions": included_versions,
        "source_head": source_head,
        "source_tree": source_tree,
        "tag_name": tag,
        "title": f"{tag} — Clean Room Launcher",
        "draft": True,
        "prerelease": prerelease,
        "release_notes_sha256": sha256_bytes(notes.encode("utf-8")),
        "release_changelog_range_sha256": sha256_bytes(
            (range_text + "\n").encode("utf-8")
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
    sample = [
        "## [0.4.6] - 2026-10-02",
        "- Codex 0.160.0 and Claude Code 2.1.287",
        "## [0.4.5] - 2026-10-01",
        "- Codex 0.160.0 and Claude Code 2.1.287",
        "## [0.4.4] - 2026-09-30",
        "- historical Codex 0.159.0 and Claude Code 2.1.284",
    ]
    selected, versions = release_range(sample, "0.4.6", "0.4.4")
    if versions != ["0.4.6", "0.4.5"]:
        raise SystemExit("PUBLISHABLE_SURFACE_SELF_TEST_FAIL:BASELINE_RANGE")
    if provider_claim_violations(selected, "0.160.0", "2.1.287", policy):
        raise SystemExit("PUBLISHABLE_SURFACE_SELF_TEST_FAIL:CURRENT_RANGE")
    # The published baseline and older history must be excluded by range
    # selection rather than by weakening validation of included content.
    if any(line_no >= 5 for line_no, _line in selected):
        raise SystemExit("PUBLISHABLE_SURFACE_SELF_TEST_FAIL:HISTORICAL_RANGE_LEAK")
    stale_intermediate = list(selected)
    for index, (line_no, line) in enumerate(stale_intermediate):
        if line_no == 4:
            stale_intermediate[index] = (
                line_no,
                "Codex 0.159.0 and Claude Code 2.1.284",
            )
    if not provider_claim_violations(
        stale_intermediate, "0.160.0", "2.1.287", policy
    ):
        raise SystemExit("PUBLISHABLE_SURFACE_SELF_TEST_FAIL:STALE_INTERMEDIATE")
    if "historical Codex 0.159.0" in "\n".join(line for _, line in selected):
        raise SystemExit("PUBLISHABLE_SURFACE_SELF_TEST_FAIL:HISTORICAL_CONTENT_LEAK")
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
    required = (args.version, args.codex_version, args.claude_version)
    if not all(required):
        raise SystemExit("PUBLISHABLE_SURFACE_BLOCKED:REQUIRED_ARGUMENTS")
    try:
        if args.source_only:
            _text, versions, baseline = source_semantic_check(
                args.version, args.codex_version, args.claude_version
            )
            print(
                f"PUBLISHABLE_SOURCE_SEMANTIC_PASS version={args.version} "
                f"baseline={baseline} included={','.join(versions)} "
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
