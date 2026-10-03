#!/usr/bin/env python3
import argparse
import json
import re
from types import SimpleNamespace

SCHEMA_VERSION = "clroom.plugin-release-smoke.v6"

ARG_NAMES = (
    "version",
    "source_head",
    "source_tree",
    "reviewed_content_digest",
    "artifact_sha256",
    "claude_version",
    "expected_provider_sha256",
)


def validate_record(record: dict, args: SimpleNamespace) -> None:
    required = {
        "schema_version": SCHEMA_VERSION,
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
        "clean_tui_supervised": True,
        "selected_tui_supervised": True,
        "interactive_human_bytes_forwarded": False,
        "interactive_submit_bytes_blocked_by_supervisor": True,
        "interactive_harness_owned_teardown": True,
        "physical_terminal_preflight_passed": True,
        "interactive_terminal_state_restored": True,
        "clean_observation_ready_acknowledged": True,
        "selected_observation_ready_acknowledged": True,
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


def self_test() -> int:
    digest = "a" * 64
    provider = "b" * 64
    args = SimpleNamespace(
        version="0.4.6",
        source_head="c" * 40,
        source_tree="d" * 40,
        reviewed_content_digest="e" * 64,
        artifact_sha256=digest,
        claude_version="2.1.287",
        expected_provider_sha256=provider,
    )
    record = {
        "schema_version": SCHEMA_VERSION,
        "result": "PASS",
        "phase": "stage",
        "release_version": args.version,
        "source_head": args.source_head,
        "source_tree": args.source_tree,
        "reviewed_content_digest": args.reviewed_content_digest,
        "artifact_sha256": args.artifact_sha256,
        "platform": "macos-aarch64",
        "claude_version": args.claude_version,
        "claude_provider_sha256": provider,
        "plugin_id": "frontend-design@claude-plugins-official",
        "plugin_info_preflight_passed": True,
        "clean_tui_confirmed": True,
        "clean_tui_supervised": True,
        "selected_tui_supervised": True,
        "interactive_human_bytes_forwarded": False,
        "interactive_submit_bytes_blocked_by_supervisor": True,
        "interactive_harness_owned_teardown": True,
        "physical_terminal_preflight_passed": True,
        "interactive_terminal_state_restored": True,
        "clean_observation_ready_acknowledged": True,
        "selected_observation_ready_acknowledged": True,
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
    validate_record(record, args)

    for field in (
        "clean_observation_ready_acknowledged",
        "selected_observation_ready_acknowledged",
    ):
        invalid = dict(record)
        invalid[field] = False
        try:
            validate_record(invalid, args)
        except SystemExit as exc:
            if str(exc) != f"CLAUDE_STAGE_EVIDENCE_BLOCKED:{field}":
                raise SystemExit(f"CLAUDE_STAGE_EVIDENCE_SELF_TEST_FAIL:{field}:wrong_error")
        else:
            raise SystemExit(f"CLAUDE_STAGE_EVIDENCE_SELF_TEST_FAIL:{field}:accepted")

    legacy = dict(record)
    legacy["schema_version"] = "clroom.plugin-release-smoke.v5"
    try:
        validate_record(legacy, args)
    except SystemExit as exc:
        if str(exc) != "CLAUDE_STAGE_EVIDENCE_BLOCKED:schema_version":
            raise SystemExit("CLAUDE_STAGE_EVIDENCE_SELF_TEST_FAIL:legacy_schema:wrong_error")
    else:
        raise SystemExit("CLAUDE_STAGE_EVIDENCE_SELF_TEST_FAIL:legacy_schema:accepted")

    print("CLAUDE_STAGE_EVIDENCE_SELF_TEST_PASS")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--evidence")
    parser.add_argument("--version")
    parser.add_argument("--source-head")
    parser.add_argument("--source-tree")
    parser.add_argument("--reviewed-content-digest")
    parser.add_argument("--artifact-sha256")
    parser.add_argument("--claude-version")
    parser.add_argument("--expected-provider-sha256")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    missing = [name for name in ("evidence", *ARG_NAMES) if getattr(args, name) is None]
    if missing:
        parser.error("missing required arguments: " + ", ".join("--" + name.replace("_", "-") for name in missing))

    with open(args.evidence, encoding="utf-8") as handle:
        record = json.load(handle)
    validate_record(record, args)
    print(
        f"CLAUDE_STAGE_EVIDENCE_PASS version={args.version} "
        f"source={args.source_head} artifact_sha256={args.artifact_sha256}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
