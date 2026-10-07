#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SEMVER_TOKEN = re.compile(
    r"(?<![0-9])(?P<prefix>v?)(?P<version>[0-9]+\.[0-9]+\.[0-9]+)(?![0-9])"
)

def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def provider_versions() -> dict[str, str]:
    text = (ROOT / "scripts/release/provider-pins.sh").read_text(encoding="utf-8")
    result = {}
    for provider, variable in (("codex", "CODEX_VERSION"), ("claude", "CLAUDE_VERSION")):
        match = re.search(rf"^{variable}=([0-9]+\.[0-9]+\.[0-9]+)$", text, re.MULTILINE)
        if match is None:
            raise SystemExit(f"PUBLISHABLE_SURFACE_BLOCKED:PROVIDER_PIN:{provider}")
        result[provider] = match.group(1)
    return result

def version_violation(
    line: str,
    prefix: str,
    version: str,
    candidate_version: str,
    pins: dict[str, str],
    release_references: set[str],
) -> str | None:
    if prefix == "v":
        if version == candidate_version or version in release_references:
            return None
        return f"STALE_PRODUCT_VERSION:actual={version}:expected={candidate_version}"
    lower = line.lower()
    providers = {provider for provider in ("codex", "claude") if provider in lower}
    if providers:
        allowed = {pins[provider] for provider in providers}
        if version in allowed:
            return None
        return f"STALE_PROVIDER_VERSION:actual={version}:allowed={','.join(sorted(allowed))}"
    if version == candidate_version:
        return None
    return f"UNCLASSIFIED_VERSION:{version}"

def scan_notes(text: str, candidate_version: str, pins: dict[str, str], references: set[str]):
    inventory = []
    violations = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for match in SEMVER_TOKEN.finditer(line):
            version = match.group("version")
            violation = version_violation(
                line, match.group("prefix"), version, candidate_version, pins, references
            )
            inventory.append({
                "line": line_number,
                "token": match.group(0),
                "classification": "PASS" if violation is None else violation,
            })
            if violation is not None:
                violations.append((line_number, match.group(0), violation))
    return inventory, violations

def expected_facts() -> dict:
    with (ROOT / "Cargo.toml").open("rb") as handle:
        version = tomllib.load(handle)["package"]["version"]
    pins_text = (ROOT / "scripts/release/provider-pins.sh").read_text(encoding="utf-8")
    def pin(name):
        match = re.search(rf"^{re.escape(name)}=(?:'([^']+)'|([^\s]+))$", pins_text, re.MULTILINE)
        if match is None:
            raise SystemExit(f"PUBLISHABLE_SURFACE_BLOCKED:PIN:{name}")
        return match.group(1) or match.group(2)
    artifact = f"clean-room-launcher-v{version}-aarch64-apple-darwin.tar.gz"
    tag = f"v{version}"
    return {
        "schema_version": "clroom.release-facts.v1",
        "release_version": version,
        "tag_name": tag,
        "release_title": f"{tag} — Clean Room Launcher",
        "draft": True,
        "prerelease": "-rc." in version,
        "platform": {"target": "aarch64-apple-darwin", "os": "macOS", "arch": "Apple Silicon"},
        "apple_platform_signing": "unsigned",
        "providers": {
            "codex": {
                "version": pin("CODEX_VERSION"),
                "package_integrity_sha512": pin("CODEX_SHA512"),
                "platform_integrity_sha512": pin("CODEX_PLATFORM_SHA512"),
                "native_executable_sha256": pin("CODEX_NATIVE_SHA256"),
            },
            "claude": {
                "version": pin("CLAUDE_VERSION"),
                "package_integrity_sha512": pin("CLAUDE_SHA512"),
                "platform_integrity_sha512": pin("CLAUDE_PLATFORM_SHA512"),
            },
        },
        "install_url": "https://github.com/y-sor/clean-room-launcher/releases/latest/download/install.sh",
        "expected_assets": [
            artifact,
            f"{artifact}.provenance.sigstore.json",
            f"{artifact}.sbom.sigstore.json",
            "install.sh",
            "sbom.cdx.json",
            "SHA256SUMS",
        ],
    }

def validate(facts_path: Path, preview_path: Path, notes_path: Path) -> dict:
    facts = json.loads(facts_path.read_text(encoding="utf-8"))
    expected = expected_facts()
    if facts != expected:
        raise SystemExit("PUBLISHABLE_SURFACE_BLOCKED:FACTS_DRIFT")
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    notes = notes_path.read_text(encoding="utf-8")
    notes_sha = sha256(notes_path)
    facts_sha = sha256(facts_path)
    expected_preview = {
        "schema_version": "clroom.publish-preview.v1",
        "release_version": facts["release_version"],
        "tag_name": facts["tag_name"],
        "release_title": facts["release_title"],
        "draft": facts["draft"],
        "prerelease": facts["prerelease"],
        "body": notes,
        "body_sha256": notes_sha,
        "facts_sha256": facts_sha,
        "expected_assets": facts["expected_assets"],
        "install_url": facts["install_url"],
        "public_claims": {
            "codex_version": facts["providers"]["codex"]["version"],
            "claude_version": facts["providers"]["claude"]["version"],
            "platform_target": facts["platform"]["target"],
            "apple_platform_signing": facts["apple_platform_signing"],
        },
    }
    if preview != expected_preview:
        raise SystemExit("PUBLISHABLE_SURFACE_BLOCKED:PREVIEW_DRIFT")

    contract = json.loads((ROOT / "schemas/release/release-contract-v1.json").read_text(encoding="utf-8"))
    changelog_policy = (
        contract["policy"]["public_doc_version_inventory"]
        ["candidate_changelog_version_inventory"]
    )
    references = set(changelog_policy["allowed_release_references"])
    pins = provider_versions()
    inventory, violations = scan_notes(notes, facts["release_version"], pins, references)
    if violations:
        for line_number, token, violation in violations:
            print(
                f"PUBLISHABLE_SURFACE_DRIFT:release-notes.md:{line_number}:{token}:{violation}",
                file=__import__("sys").stderr,
            )
        raise SystemExit("PUBLISHABLE_SURFACE_BLOCKED:SEMANTIC_PUBLIC_CLAIM")
    return {
        "schema_version": "clroom.publishable-surface.v1",
        "result": "PASS",
        "release_version": facts["release_version"],
        "tag_name": facts["tag_name"],
        "release_facts_sha256": facts_sha,
        "publish_preview_sha256": sha256(preview_path),
        "release_notes_sha256": notes_sha,
        "semantic_public_claims": "PASS",
        "version_inventory": inventory,
    }

def self_test() -> None:
    pins = {"codex": "0.161.0", "claude": "2.1.292"}
    refs = {"0.4.4", "0.4.5"}
    fixtures = [
        ("Codex 0.159.0 stale", "", "0.159.0", True),
        ("Codex 0.161.0 current", "", "0.161.0", False),
        ("Claude Code 2.1.292 current", "", "2.1.292", False),
        ("v0.4.6 provider/product facts", "v", "0.4.6", False),
        ("recovery from v0.4.5", "v", "0.4.5", False),
        ("provider/product facts from v0.4.3", "v", "0.4.3", True),
        ("mystery dependency 9.9.9", "", "9.9.9", True),
    ]
    for line, prefix, version, should_fail in fixtures:
        failed = version_violation(line, prefix, version, "0.4.6", pins, refs) is not None
        if failed != should_fail:
            raise SystemExit(f"PUBLISHABLE_SURFACE_SELF_TEST_FAIL:{line}")
    stale_text = "Codex 0.159.0 stale"
    _, stale = scan_notes(stale_text, "0.4.6", pins, refs)
    if not stale:
        raise SystemExit("PUBLISHABLE_SURFACE_SELF_TEST_FAIL:HASH_CORRECT_STALE_CLAIM")
    historical = """## [0.4.6] - 2026-10-02
Codex 0.161.0 current
## [0.4.5] - 2026-09-29
Codex 0.159.0 historical
"""
    current = historical.split("## [0.4.5]", 1)[0]
    _, violations = scan_notes(current, "0.4.6", pins, refs)
    if violations:
        raise SystemExit("PUBLISHABLE_SURFACE_SELF_TEST_FAIL:HISTORICAL_SECTION")
    print("PUBLISHABLE_SURFACE_SELF_TEST_PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--facts")
    parser.add_argument("--preview")
    parser.add_argument("--notes")
    parser.add_argument("--output")
    parser.add_argument("--evidence")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    if not all((args.facts, args.preview, args.notes)):
        raise SystemExit("PUBLISHABLE_SURFACE_BLOCKED:INPUTS_REQUIRED")
    record = validate(Path(args.facts), Path(args.preview), Path(args.notes))
    if args.evidence:
        existing = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
        if existing != record:
            raise SystemExit("PUBLISHABLE_SURFACE_BLOCKED:EVIDENCE_DRIFT")
    if args.output:
        Path(args.output).write_text(
            json.dumps(record, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
    if not args.output and not args.evidence:
        raise SystemExit("PUBLISHABLE_SURFACE_BLOCKED:OUTPUT_OR_EVIDENCE_REQUIRED")
    print(
        f"PUBLISHABLE_SURFACE_PASS tag={record['tag_name']} "
        f"preview_sha256={record['publish_preview_sha256']}"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
