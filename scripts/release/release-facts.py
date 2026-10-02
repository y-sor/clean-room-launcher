#!/usr/bin/env python3
import argparse
import json
import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROVIDER_PINS = ROOT / "scripts/release/provider-pins.sh"

def pin(name: str) -> str:
    text = PROVIDER_PINS.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(name)}=(?:'([^']+)'|([^\\s]+))$", text, re.MULTILINE)
    if match is None:
        raise SystemExit(f"RELEASE_FACTS_BLOCKED:PIN:{name}")
    return match.group(1) or match.group(2)

def facts() -> dict:
    with (ROOT / "Cargo.toml").open("rb") as handle:
        version = tomllib.load(handle)["package"]["version"]
    tag = f"v{version}"
    artifact = f"clean-room-launcher-v{version}-aarch64-apple-darwin.tar.gz"
    assets = [
        artifact,
        f"{artifact}.provenance.sigstore.json",
        f"{artifact}.sbom.sigstore.json",
        "install.sh",
        "sbom.cdx.json",
        "SHA256SUMS",
    ]
    return {
        "schema_version": "clroom.release-facts.v1",
        "release_version": version,
        "tag_name": tag,
        "release_title": f"{tag} — Clean Room Launcher",
        "draft": True,
        "prerelease": "-rc." in version,
        "platform": {
            "target": "aarch64-apple-darwin",
            "os": "macOS",
            "arch": "Apple Silicon",
        },
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
        "expected_assets": assets,
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    record = facts()
    if args.self_test:
        if record["release_title"] != f'{record["tag_name"]} — Clean Room Launcher':
            raise SystemExit("RELEASE_FACTS_SELF_TEST_FAIL:TITLE")
        if len(record["expected_assets"]) != 6 or len(set(record["expected_assets"])) != 6:
            raise SystemExit("RELEASE_FACTS_SELF_TEST_FAIL:ASSETS")
        if not record["install_url"].endswith("/releases/latest/download/install.sh"):
            raise SystemExit("RELEASE_FACTS_SELF_TEST_FAIL:INSTALL_URL")
        print("RELEASE_FACTS_SELF_TEST_PASS")
        return 0
    if not args.output:
        raise SystemExit("RELEASE_FACTS_BLOCKED:OUTPUT_REQUIRED")
    Path(args.output).write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"RELEASE_FACTS_PASS version={record['release_version']} tag={record['tag_name']}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
