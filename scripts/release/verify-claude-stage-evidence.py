#!/usr/bin/env python3
import argparse
import json
import re

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-head", required=True)
    parser.add_argument("--source-tree", required=True)
    parser.add_argument("--reviewed-content-digest", required=True)
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--claude-version", required=True)
    parser.add_argument("--expected-provider-sha256", required=True)
    args = parser.parse_args()

    with open(args.evidence, encoding="utf-8") as handle:
        record = json.load(handle)
    required = {
        "schema_version": "clroom.plugin-release-smoke.v4",
        "result": "PASS",
        "phase": "stage",
        "release_version": args.version,
        "source_head": args.source_head,
        "source_tree": args.source_tree,
        "reviewed_content_digest": args.reviewed_content_digest,
        "artifact_sha256": args.artifact_sha256,
        "platform": "macos-aarch64",
        "claude_version": args.claude_version,
        "plugin_id": "frontend-design@claude-plugins-official",
        "plugin_info_preflight_passed": True,
        "clean_tui_confirmed": True,
        "clean_target_plugin_absent_confirmed": True,
        "selected_tui_confirmed": True,
        "selected_target_plugin_visible_confirmed": True,
        "no_new_sibling_plugins_confirmed": True,
        "selected_plugin_errors_absent_confirmed": True,
        "persistent_config_unchanged": True,
        "automated_probe_prompt_supplied": False,
        "interactive_no_model_prompt_confirmed": True,
        "external_ancestor_agents_absent_confirmed": True,
        "project_agents_retained_confirmed": True,
        "external_ancestor_agents_sandbox_probe_passed": True,
    }
    for key, value in required.items():
        if record.get(key) != value:
            raise SystemExit(f"CLAUDE_STAGE_EVIDENCE_BLOCKED:{key}")
    if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("claude_provider_sha256", ""))):
        raise SystemExit("CLAUDE_STAGE_EVIDENCE_BLOCKED:provider_sha")
    if record.get("claude_provider_sha256") != args.expected_provider_sha256:
        raise SystemExit("CLAUDE_STAGE_EVIDENCE_BLOCKED:provider_bytes")
    if not record.get("plugin_id"):
        raise SystemExit("CLAUDE_STAGE_EVIDENCE_BLOCKED:plugin_id")
    print(
        f"CLAUDE_STAGE_EVIDENCE_PASS version={args.version} "
        f"source={args.source_head} artifact_sha256={args.artifact_sha256}"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
