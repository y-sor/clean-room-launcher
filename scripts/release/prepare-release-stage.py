#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[2]
PIN_NAMES = (
    "CODEX_VERSION",
    "CODEX_SHA512",
    "CODEX_PLATFORM_SHA512",
    "CLAUDE_VERSION",
    "CLAUDE_SHA512",
    "CLAUDE_PLATFORM_SHA512",
)


def fail(reason: str) -> "NoReturn":
    raise SystemExit(f"RELEASE_STAGE_BLOCKED:{reason}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def provider_pins() -> dict[str, str]:
    text = (ROOT / "scripts/release/provider-pins.sh").read_text(encoding="utf-8")
    values: dict[str, str] = {}
    for name in PIN_NAMES:
        match = re.search(rf"^{name}=([^\n]+)$", text, flags=re.M)
        if match is None:
            fail(f"PROVIDER_PIN_MISSING:{name}")
        raw = match.group(1).strip()
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            raw = raw[1:-1]
        if not raw:
            fail(f"PROVIDER_PIN_EMPTY:{name}")
        values[name] = raw
    return values


def release_notes(version: str, artifact: str) -> str:
    lines = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    start = None
    body: list[str] = []
    for index, line in enumerate(lines):
        if line.startswith(f"## [{version}] - "):
            start = index + 1
            continue
        if start is not None and line.startswith("## ["):
            break
        if start is not None:
            body.append(line)
    if start is None:
        fail("CHANGELOG_SECTION_MISSING")
    text = "\n".join(body).strip()
    footer = f"""
## Install

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/y-sor/clean-room-launcher/releases/latest/download/install.sh | sh
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

The distributed archive is currently unsigned at the Apple platform-signing layer. Verify the checksums and release-visible GitHub attestation bundles before use.
""".strip()
    return text + "\n\n" + footer + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-dir", required=True, type=Path)
    parser.add_argument("--artifact", required=True, type=Path)
    parser.add_argument("--sbom", required=True, type=Path)
    parser.add_argument("--install", required=True, type=Path)
    parser.add_argument("--codex-evidence", required=True, type=Path)
    parser.add_argument("--codex-qualification", required=True, type=Path)
    parser.add_argument("--claude-qualification", required=True, type=Path)
    parser.add_argument("--source-head", required=True)
    args = parser.parse_args()

    version = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["package"]["version"]
    expected_artifact = f"clean-room-launcher-v{version}-aarch64-apple-darwin.tar.gz"
    if args.artifact.name != expected_artifact:
        fail("ARTIFACT_NAME")
    if not re.fullmatch(r"[0-9a-f]{40}", args.source_head):
        fail("SOURCE_HEAD")
    if git("rev-parse", "HEAD") != args.source_head:
        fail("HEAD_MISMATCH")
    source_tree = git("rev-parse", "HEAD^{tree}")

    review_path = ROOT / f"reports/release/v{version}-review.json"
    if not review_path.is_file():
        fail("REVIEW_MISSING")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if review.get("release") != f"v{version}":
        fail("REVIEW_VERSION")
    reviewed_content_digest = review.get("reviewed_content_digest")
    if not isinstance(reviewed_content_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", reviewed_content_digest):
        fail("REVIEW_DIGEST")

    for path, label in (
        (args.artifact, "ARTIFACT"),
        (args.sbom, "SBOM"),
        (args.install, "INSTALL"),
        (args.codex_evidence, "CODEX_EVIDENCE"),
        (args.codex_qualification, "CODEX_QUALIFICATION"),
        (args.claude_qualification, "CLAUDE_QUALIFICATION"),
    ):
        if not path.is_file() or path.stat().st_size == 0:
            fail(f"{label}_MISSING")

    pins = provider_pins()
    codex = json.loads(args.codex_evidence.read_text(encoding="utf-8"))
    required = {
        "schema_version": "clroom.codex-plugin-release-smoke.v4",
        "result": "PASS",
        "phase": "stage",
        "release_version": version,
        "source_head": args.source_head,
        "source_tree": source_tree,
        "reviewed_content_digest": reviewed_content_digest,
        "evidence_binding": "exact-release-artifact-v1",
        "platform": "macos-aarch64",
        "codex_version": pins["CODEX_VERSION"],
        "real_provider_runtime_confirmed": True,
        "expected_mcp_runtime_healthy_confirmed": True,
        "provider_mcp_initialize_observed": True,
        "provider_mcp_tools_list_observed": True,
        "fixture_mcp_tool_call_passed": True,
        "provider_state_lifecycle_closed": True,
        "ambient_config_and_plugin_tree_unchanged": True,
        "plugin_source_unchanged": True,
        "post_runtime_clean_confirmed": True,
        "model_prompt_sent": False,
    }
    for key, value in required.items():
        if codex.get(key) != value:
            fail(f"CODEX_EVIDENCE:{key}")
    artifact_sha = sha256(args.artifact)
    if codex.get("artifact_sha256") != artifact_sha:
        fail("CODEX_ARTIFACT_DIGEST")

    stage = args.stage_dir.resolve()
    if stage.exists():
        shutil.rmtree(stage)
    assets = stage / "release-assets"
    qualifications = stage / "qualification"
    assets.mkdir(parents=True)
    qualifications.mkdir(parents=True)

    copied = {
        expected_artifact: args.artifact,
        "sbom.cdx.json": args.sbom,
        "install.sh": args.install,
    }
    for name, source in copied.items():
        shutil.copy2(source, assets / name)
    os.chmod(assets / "install.sh", 0o755)
    shutil.copy2(args.codex_evidence, stage / "codex-stage-evidence.json")
    shutil.copy2(args.codex_qualification, qualifications / "codex.json")
    shutil.copy2(args.claude_qualification, qualifications / "claude.json")

    checksum_lines = [
        f"{sha256(assets / name)}  {name}"
        for name in (expected_artifact, "sbom.cdx.json", "install.sh")
    ]
    (assets / "SHA256SUMS").write_text("\n".join(checksum_lines) + "\n", encoding="utf-8")

    notes = release_notes(version, expected_artifact)
    (stage / "release-notes.md").write_text(notes, encoding="utf-8")

    asset_digests = {
        name: sha256(assets / name)
        for name in (expected_artifact, "sbom.cdx.json", "install.sh", "SHA256SUMS")
    }
    manifest = {
        "schema_version": "clroom.release-stage.v1",
        "release_version": version,
        "source_head": args.source_head,
        "source_tree": source_tree,
        "reviewed_content_digest": reviewed_content_digest,
        "artifact_name": expected_artifact,
        "artifact_sha256": artifact_sha,
        "release_notes_sha256": sha256(stage / "release-notes.md"),
        "assets": asset_digests,
        "providers": {
            "codex": {
                "version": pins["CODEX_VERSION"],
                "package_sha512": pins["CODEX_SHA512"],
                "platform_sha512": pins["CODEX_PLATFORM_SHA512"],
            },
            "claude": {
                "version": pins["CLAUDE_VERSION"],
                "package_sha512": pins["CLAUDE_SHA512"],
                "platform_sha512": pins["CLAUDE_PLATFORM_SHA512"],
            },
        },
        "gates": {
            "release_contract": True,
            "locked_tests": True,
            "installer_self_test": True,
            "dependency_sca": True,
            "exact_archive_provider_qualification": True,
            "codex_whole_plugin_runtime": True,
            "provider_registry_tuple_frozen": True,
        },
    }
    (stage / "stage-manifest.json").write_text(
        json.dumps(manifest, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        f"RELEASE_STAGE_PREPARED version={version} head={args.source_head} "
        f"artifact_sha256={artifact_sha}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
