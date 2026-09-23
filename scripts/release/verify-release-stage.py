#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib

ROOT = Path(__file__).resolve().parents[2]


def fail(reason: str) -> "NoReturn":
    raise SystemExit(f"RELEASE_STAGE_VERIFY_BLOCKED:{reason}")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage-dir", required=True, type=Path)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-version", default=None)
    args = parser.parse_args()

    stage = args.stage_dir.resolve()
    manifest_path = stage / "stage-manifest.json"
    if not manifest_path.is_file():
        fail("MANIFEST_MISSING")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "clroom.release-stage.v1":
        fail("MANIFEST_SCHEMA")
    if not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        fail("EXPECTED_HEAD")
    if manifest.get("source_head") != args.expected_head:
        fail("SOURCE_HEAD")

    version = tomllib.loads((ROOT / "Cargo.toml").read_text(encoding="utf-8"))["package"]["version"]
    if args.expected_version is not None and version != args.expected_version:
        fail("VERSION_ARGUMENT")
    if manifest.get("release_version") != version:
        fail("VERSION")
    if git("rev-parse", "HEAD") != args.expected_head:
        fail("CHECKOUT_HEAD")
    source_tree = git("rev-parse", "HEAD^{tree}")
    if manifest.get("source_tree") != source_tree:
        fail("SOURCE_TREE")

    review_path = ROOT / f"reports/release/v{version}-review.json"
    review = json.loads(review_path.read_text(encoding="utf-8"))
    if manifest.get("reviewed_content_digest") != review.get("reviewed_content_digest"):
        fail("REVIEW_DIGEST")

    assets_dir = stage / "release-assets"
    artifact_name = manifest.get("artifact_name")
    if artifact_name != f"clean-room-launcher-v{version}-aarch64-apple-darwin.tar.gz":
        fail("ARTIFACT_NAME")
    expected_names = {artifact_name, "sbom.cdx.json", "install.sh", "SHA256SUMS"}
    actual_names = {p.name for p in assets_dir.iterdir() if p.is_file()} if assets_dir.is_dir() else set()
    if actual_names != expected_names:
        fail("ASSET_SET")

    asset_digests = manifest.get("assets")
    if not isinstance(asset_digests, dict) or set(asset_digests) != expected_names:
        fail("ASSET_MANIFEST")
    for name in sorted(expected_names):
        if sha256(assets_dir / name) != asset_digests.get(name):
            fail(f"ASSET_DIGEST:{name}")
    if manifest.get("artifact_sha256") != asset_digests.get(artifact_name):
        fail("ARTIFACT_DIGEST")
    if sha256(stage / "release-notes.md") != manifest.get("release_notes_sha256"):
        fail("RELEASE_NOTES_DIGEST")

    checksum_entries: dict[str, str] = {}
    for line in (assets_dir / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]):
            fail("CHECKSUM_FORMAT")
        checksum_entries[parts[1]] = parts[0]
    if set(checksum_entries) != {artifact_name, "sbom.cdx.json", "install.sh"}:
        fail("CHECKSUM_SET")
    for name, expected in checksum_entries.items():
        if sha256(assets_dir / name) != expected:
            fail(f"CHECKSUM:{name}")

    codex_path = stage / "codex-stage-evidence.json"
    codex = json.loads(codex_path.read_text(encoding="utf-8"))
    required = {
        "schema_version": "clroom.codex-plugin-release-smoke.v4",
        "result": "PASS",
        "phase": "stage",
        "release_version": version,
        "source_head": args.expected_head,
        "source_tree": source_tree,
        "reviewed_content_digest": manifest["reviewed_content_digest"],
        "evidence_binding": "exact-release-artifact-v1",
        "artifact_sha256": manifest["artifact_sha256"],
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

    gates = manifest.get("gates")
    required_gates = {
        "release_contract",
        "locked_tests",
        "installer_self_test",
        "dependency_sca",
        "exact_archive_provider_qualification",
        "codex_whole_plugin_runtime",
        "provider_registry_tuple_frozen",
    }
    if not isinstance(gates, dict) or any(gates.get(name) is not True for name in required_gates):
        fail("GATE_MAP")

    print(
        f"RELEASE_STAGE_VERIFY_PASS version={version} head={args.expected_head} "
        f"artifact_sha256={manifest['artifact_sha256']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
