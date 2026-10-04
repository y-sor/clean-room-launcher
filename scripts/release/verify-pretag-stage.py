#!/usr/bin/env python3
import argparse
import hashlib
import json
import re
from pathlib import Path

SCHEMA = "clroom.pretag-stage.v2"
REQUIRED_CLOSURE = {
    "release_contract",
    "release_readiness",
    "exact_shipping_archive",
    "generic_provider_qualification",
    "codex_exact_archive_runtime",
    "codex_composition_exact_archive_runtime",
    "installer_contract",
    "release_notes_render",
    "release_facts",
    "exact_publish_preview",
    "publishable_surface_semantic",
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
        "codex_composition_exact_archive_runtime": "PASS",
        "publishable_surface_semantic": "PASS",
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
        "release-facts.json",
        "publish-preview.json",
        "publishable-surface.json",
        "codex-qualification.json",
        "claude-qualification.json",
        "codex-stage.json",
        "codex-composition-stage.json",
    }
    if set(files) != required_files:
        raise SystemExit("PRETAG_STAGE_BLOCKED:FILE_SET")
    for name, expected_sha in files.items():
        if not re.fullmatch(r"[0-9a-f]{64}", str(expected_sha)):
            raise SystemExit(f"PRETAG_STAGE_BLOCKED:FILE_DIGEST:{name}")
        path = root / name
        if not path.is_file() or sha256(path) != expected_sha:
            raise SystemExit(f"PRETAG_STAGE_BLOCKED:FILE_BYTES:{name}")

    facts_sha = files["release-facts.json"]
    preview_sha = files["publish-preview.json"]
    surface_sha = files["publishable-surface.json"]
    if record.get("release_facts_sha256") != facts_sha:
        raise SystemExit("PRETAG_STAGE_BLOCKED:RELEASE_FACTS_DIGEST")
    if record.get("publish_preview_sha256") != preview_sha:
        raise SystemExit("PRETAG_STAGE_BLOCKED:PUBLISH_PREVIEW_DIGEST")
    if record.get("publishable_surface_evidence_sha256") != surface_sha:
        raise SystemExit("PRETAG_STAGE_BLOCKED:PUBLISHABLE_SURFACE_EVIDENCE_DIGEST")

    facts = json.loads((root / "release-facts.json").read_text(encoding="utf-8"))
    preview = json.loads((root / "publish-preview.json").read_text(encoding="utf-8"))
    surface = json.loads((root / "publishable-surface.json").read_text(encoding="utf-8"))
    if facts.get("schema_version") != "clroom.release-facts.v1":
        raise SystemExit("PRETAG_STAGE_BLOCKED:RELEASE_FACTS_SCHEMA")
    if facts.get("release_version") != args.version or facts.get("tag_name") != f"v{args.version}":
        raise SystemExit("PRETAG_STAGE_BLOCKED:RELEASE_FACTS_IDENTITY")
    if preview.get("schema_version") != "clroom.publish-preview.v1":
        raise SystemExit("PRETAG_STAGE_BLOCKED:PUBLISH_PREVIEW_SCHEMA")
    if preview.get("release_version") != args.version or preview.get("facts_sha256") != facts_sha:
        raise SystemExit("PRETAG_STAGE_BLOCKED:PUBLISH_PREVIEW_BINDING")
    if preview.get("body_sha256") != files["release-notes.md"]:
        raise SystemExit("PRETAG_STAGE_BLOCKED:PUBLISH_PREVIEW_BODY")
    if surface.get("schema_version") != "clroom.publishable-surface.v1":
        raise SystemExit("PRETAG_STAGE_BLOCKED:PUBLISHABLE_SURFACE_SCHEMA")
    expected_surface = {
        "result": "PASS",
        "release_version": args.version,
        "tag_name": f"v{args.version}",
        "release_facts_sha256": facts_sha,
        "publish_preview_sha256": preview_sha,
        "release_notes_sha256": files["release-notes.md"],
        "semantic_public_claims": "PASS",
    }
    for key, value in expected_surface.items():
        if surface.get(key) != value:
            raise SystemExit(f"PRETAG_STAGE_BLOCKED:PUBLISHABLE_SURFACE:{key}")

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

    composition = json.loads(
        (root / "codex-composition-stage.json").read_text(encoding="utf-8")
    )
    composition_required = {
        "schema_version": "clroom.codex-composition-rehearsal.v1",
        "result": "PASS",
        "source_head": args.source_head,
        "artifact_sha256": files[record["artifact_name"]],
        "platform": "macos-aarch64",
        "plugin_id": "composition@clroom-fixture",
        "plugin_mcp_id": "clroom_plugin",
        "standalone_mcp_id": "clroom_standalone",
        "overlap_conflict_refused": True,
        "ambient_provider_state_unchanged": True,
        "plugin_source_unchanged": True,
        "human_inspection_sanitized": True,
        "json_inspection_sanitized": True,
        "inspection_same_resource_identities": True,
        "interactive_provider_birth": True,
        "plugin_mcp_under_interactive_provider": True,
        "standalone_mcp_under_interactive_provider": True,
        "plugin_mcp_initialize": True,
        "plugin_mcp_tools_list": True,
        "standalone_mcp_initialize": True,
        "standalone_mcp_tools_list": True,
        "standalone_env_admission": True,
        "blocked_env_absent": True,
        "unselected_siblings_absent": True,
        "task_owned_processes_closed": True,
        "model_prompt_sent": False,
        "clean_after_absent": True,
    }
    for key, value in composition_required.items():
        if composition.get(key) != value:
            raise SystemExit(f"PRETAG_STAGE_BLOCKED:CODEX_COMPOSITION:{key}")
    if composition.get("codex_provider_sha256") != providers["codex"]["executable_sha256"]:
        raise SystemExit("PRETAG_STAGE_BLOCKED:CODEX_COMPOSITION:provider_bytes")

    print(
        f"PRETAG_STAGE_VERIFY_PASS version={args.version} "
        f"source={args.source_head} artifact_sha256={files[record['artifact_name']]}"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
