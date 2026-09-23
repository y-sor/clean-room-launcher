#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from pathlib import Path

SCHEMA = "clroom.pretag-stage.v1"
REQUIRED_CLOSURE = {
    "release_contract",
    "release_readiness",
    "exact_shipping_archive",
    "generic_provider_qualification",
    "codex_exact_archive_runtime",
    "installer_contract",
    "release_notes_render",
    "provider_registry_freeze",
}
POST_TAG_ONLY = {
    "tag_bound_attestation",
    "draft_promotion",
    "draft_reconciliation",
}

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--source-tree")
    parser.add_argument("--reviewed-content-digest")
    parser.add_argument("--codex-version")
    parser.add_argument("--claude-version")
    args = parser.parse_args()

    root = Path(args.dir)
    manifest_path = root / "pretag-manifest.json"
    if not manifest_path.is_file():
        raise SystemExit("PRETAG_STAGE_BLOCKED:MANIFEST_MISSING")
    record = json.loads(manifest_path.read_text(encoding="utf-8"))

    expected = {
        "schema_version": SCHEMA,
        "release_version": args.version,
        "source_head": args.source_head,
        "artifact_name": f"clean-room-launcher-v{args.version}-aarch64-apple-darwin.tar.gz",
        "provider_registry_freshness": "PASS",
        "generic_provider_qualification": "PASS",
        "codex_exact_archive_runtime": "PASS",
    }
    if args.source_tree:
        expected["source_tree"] = args.source_tree
    if args.reviewed_content_digest:
        expected["reviewed_content_digest"] = args.reviewed_content_digest
    for key, value in expected.items():
        if record.get(key) != value:
            raise SystemExit(f"PRETAG_STAGE_BLOCKED:{key}")

    if not re.fullmatch(r"[0-9a-f]{40}", str(record.get("source_head", ""))):
        raise SystemExit("PRETAG_STAGE_BLOCKED:SOURCE_HEAD")
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(record.get("source_tree", ""))):
        raise SystemExit("PRETAG_STAGE_BLOCKED:SOURCE_TREE")
    if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("reviewed_content_digest", ""))):
        raise SystemExit("PRETAG_STAGE_BLOCKED:REVIEW_DIGEST")

    providers = record.get("providers")
    if not isinstance(providers, dict):
        raise SystemExit("PRETAG_STAGE_BLOCKED:PROVIDERS")
    if args.codex_version and (providers.get("codex") or {}).get("version") != args.codex_version:
        raise SystemExit("PRETAG_STAGE_BLOCKED:CODEX_VERSION")
    if args.claude_version and (providers.get("claude") or {}).get("version") != args.claude_version:
        raise SystemExit("PRETAG_STAGE_BLOCKED:CLAUDE_VERSION")
    for provider in ("codex", "claude"):
        item = providers.get(provider) or {}
        if not re.fullmatch(r"[A-Za-z0-9+/=]{40,}", str(item.get("package_integrity_sha512", ""))):
            raise SystemExit(f"PRETAG_STAGE_BLOCKED:{provider.upper()}_PACKAGE_INTEGRITY")
        if not re.fullmatch(r"[A-Za-z0-9+/=]{40,}", str(item.get("platform_integrity_sha512", ""))):
            raise SystemExit(f"PRETAG_STAGE_BLOCKED:{provider.upper()}_PLATFORM_INTEGRITY")
        if not re.fullmatch(r"[0-9a-f]{64}", str(item.get("executable_sha256", ""))):
            raise SystemExit(f"PRETAG_STAGE_BLOCKED:{provider.upper()}_EXECUTABLE_SHA256")

    if set(record.get("blocker_closure") or []) != REQUIRED_CLOSURE:
        raise SystemExit("PRETAG_STAGE_BLOCKED:BLOCKER_CLOSURE")
    if set(record.get("post_tag_only") or []) != POST_TAG_ONLY:
        raise SystemExit("PRETAG_STAGE_BLOCKED:POST_TAG_ONLY")

    files = record.get("files")
    if not isinstance(files, dict):
        raise SystemExit("PRETAG_STAGE_BLOCKED:FILES")
    required_files = {
        record["artifact_name"],
        "SHA256SUMS",
        "sbom.cdx.json",
        "install.sh",
        "release-notes.md",
        "codex-qualification.json",
        "claude-qualification.json",
        "codex-stage.json",
    }
    if set(files) != required_files:
        raise SystemExit("PRETAG_STAGE_BLOCKED:FILE_SET")
    for name, expected_sha in files.items():
        if not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha)):
            raise SystemExit(f"PRETAG_STAGE_BLOCKED:FILE_DIGEST:{name}")
        path = root / name
        if not path.is_file() or sha256(path) != expected_sha:
            raise SystemExit(f"PRETAG_STAGE_BLOCKED:FILE_BYTES:{name}")

    codex = json.loads((root / "codex-stage.json").read_text(encoding="utf-8"))
    runtime_required = {
        "schema_version": "clroom.codex-plugin-release-smoke.v4",
        "result": "PASS",
        "phase": "stage",
        "release_version": args.version,
        "source_head": args.source_head,
        "artifact_sha256": files[record["artifact_name"]],
        "real_provider_runtime_confirmed": True,
        "expected_mcp_runtime_healthy_confirmed": True,
        "provider_mcp_initialize_observed": True,
        "provider_mcp_tools_list_observed": True,
        "fixture_mcp_tool_call_passed": True,
        "provider_state_lifecycle_closed": True,
        "post_runtime_clean_confirmed": True,
        "model_prompt_sent": False,
    }
    for key, value in runtime_required.items():
        if codex.get(key) != value:
            raise SystemExit(f"PRETAG_STAGE_BLOCKED:CODEX_RUNTIME:{key}")
    if codex.get("codex_provider_sha256") != providers["codex"]["executable_sha256"]:
        raise SystemExit("PRETAG_STAGE_BLOCKED:CODEX_RUNTIME:provider_bytes")

    print(
        f"PRETAG_STAGE_VERIFY_PASS version={args.version} "
        f"source={args.source_head} artifact_sha256={files[record['artifact_name']]}"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
