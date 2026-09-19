#!/usr/bin/env python3
"""Fail closed when provider qualification truth drifts across code, CI, or docs."""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUALIFICATION = ROOT / "release/qualification.json"


def fail(message: str) -> None:
    raise SystemExit("PROVIDER_VERSION_SYNC_BLOCKED:" + message)


def require_text(path: str, needles: list[str]) -> None:
    text = (ROOT / path).read_text(encoding="utf-8")
    missing = [needle for needle in needles if needle not in text]
    if missing:
        fail(f"{path}:missing:" + ",".join(missing))


def tuple_version(source: str, constant: str) -> str:
    pattern = re.compile(
        rf"pub const {re.escape(constant)}:\s*\(u64, u64, u64\)\s*=\s*"
        r"\((\d+),\s*(\d+),\s*(\d+)\);"
    )
    match = pattern.search(source)
    if not match:
        fail(f"rust-constant-missing:{constant}")
    return ".".join(match.groups())


def current_changelog_section(text: str) -> str:
    lines = text.splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.startswith("## [") and line != "## [Unreleased]":
            start = index
            break
    if start is None:
        fail("CHANGELOG.md:no-release-section")
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("## ["):
            end = index
            break
    return "\n".join(lines[start:end])


def main() -> None:
    try:
        data = json.loads(QUALIFICATION.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        fail(f"qualification-json:{exc}")

    if data.get("schema_version") != "clroom.release-qualification.v1":
        fail("qualification-schema")

    providers = data.get("providers")
    if not isinstance(providers, dict):
        fail("qualification-providers")

    try:
        codex_min = providers["codex"]["minimum"]
        codex_exact = providers["codex"]["clean_exact"]
        claude_min = providers["claude"]["minimum"]
        claude_clean = providers["claude"]["clean_exact"]
        claude_plugin = providers["claude"]["plugin_activation_exact"]
    except (KeyError, TypeError):
        fail("qualification-provider-fields")

    version_re = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
    for label, value in {
        "codex-min": codex_min,
        "codex-exact": codex_exact,
        "claude-min": claude_min,
        "claude-clean": claude_clean,
        "claude-plugin": claude_plugin,
    }.items():
        if not isinstance(value, str) or not version_re.fullmatch(value):
            fail(f"invalid-version:{label}")

    source = (ROOT / "src/catalog/provider_inventory.rs").read_text(encoding="utf-8")
    actual = {
        "CODEX_CLEAN_EXACT": tuple_version(source, "CODEX_CLEAN_EXACT"),
        "CLAUDE_CLEAN_EXACT": tuple_version(source, "CLAUDE_CLEAN_EXACT"),
        "CLAUDE_PLUGIN_ACTIVATION_EXACT": tuple_version(
            source, "CLAUDE_PLUGIN_ACTIVATION_EXACT"
        ),
    }
    expected = {
        "CODEX_CLEAN_EXACT": codex_exact,
        "CLAUDE_CLEAN_EXACT": claude_clean,
        "CLAUDE_PLUGIN_ACTIVATION_EXACT": claude_plugin,
    }
    for constant, expected_version in expected.items():
        if actual[constant] != expected_version:
            fail(
                f"rust-drift:{constant}:expected={expected_version}:actual={actual[constant]}"
            )

    provisioner = (
        ROOT / "scripts/release/provision-provider-canaries.sh"
    ).read_text(encoding="utf-8")
    for needle in [
        f"'@openai/codex@{codex_exact}'",
        f"'@openai/codex@{codex_exact}-darwin-arm64'",
        f"'@anthropic-ai/claude-code@{claude_clean}'",
        f"'@anthropic-ai/claude-code-darwin-arm64@{claude_clean}'",
    ]:
        if needle not in provisioner:
            fail("provider-canary-drift:" + needle)

    require_text(
        "README.md",
        [codex_min, codex_exact, claude_min, claude_clean, claude_plugin],
    )
    require_text(
        "SECURITY.md",
        [codex_exact, claude_clean, claude_plugin],
    )
    require_text(
        "docs/claude-code.md",
        [claude_min, claude_clean, claude_plugin],
    )
    require_text(
        "docs/configuration-matrix.md",
        [claude_clean, claude_plugin],
    )
    require_text(
        "docs/limitations.md",
        [codex_min, codex_exact, claude_min, claude_clean, claude_plugin],
    )

    changelog = current_changelog_section(
        (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    )
    for version in [codex_min, codex_exact, claude_min, claude_clean, claude_plugin]:
        if version not in changelog:
            fail("CHANGELOG.md:current-release-missing:" + version)

    verify_source = (
        ROOT / "scripts/release/verify-qualification.py"
    ).read_text(encoding="utf-8")
    if "release/qualification.json" not in verify_source:
        fail("verify-qualification-not-bound-to-pin-source")

    print(
        "PROVIDER_VERSION_SYNC_PASS "
        f"codex={codex_exact} "
        f"claude_clean={claude_clean} "
        f"claude_plugin={claude_plugin}"
    )


if __name__ == "__main__":
    main()
