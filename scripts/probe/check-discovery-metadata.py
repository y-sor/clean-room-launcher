#!/usr/bin/env python3
"""Validate CLROOM's controllable discovery metadata and routing invariants."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path


class DiscoveryMetadataError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise DiscoveryMetadataError(message)


def read(root: Path, relative: str) -> str:
    try:
        return (root / relative).read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"FILE_UNREADABLE:{relative}:{exc}")


def frontmatter_value(markdown: str, key: str) -> str:
    if not markdown.startswith("---\n"):
        fail(f"FRONTMATTER_MISSING:{key}")
    end = markdown.find("\n---", 4)
    if end < 0:
        fail(f"FRONTMATTER_UNTERMINATED:{key}")
    fm = markdown[4:end]
    match = re.search(rf"^{re.escape(key)}:\s*(.+?)\s*$", fm, flags=re.MULTILINE)
    if match is None:
        fail(f"FRONTMATTER_KEY_MISSING:{key}")
    return match.group(1).strip().strip('"').strip("'")


def require_terms(value: str, terms: tuple[str, ...], label: str) -> None:
    lowered = value.casefold()
    missing = [term for term in terms if term.casefold() not in lowered]
    if missing:
        fail(f"DISCOVERY_TERMS_MISSING:{label}:" + ",".join(missing))


def validate_schema(head: str) -> None:
    required = (
        '"@type": "SoftwareSourceCode"',
        '"codeRepository": "https://github.com/y-sor/clean-room-launcher"',
        '"programmingLanguage": "Rust"',
        '"runtimePlatform": "macOS on Apple Silicon"',
        '"license": "https://www.mozilla.org/MPL/2.0/"',
    )
    for item in required:
        if item not in head:
            fail(f"SOFTWARE_SOURCE_SCHEMA_MISSING:{item}")

    if '"@type": "SoftwareApplication"' in head:
        fail("STALE_SOFTWARE_APPLICATION_SCHEMA")
    if '"aggregateRating"' in head or '"review"' in head:
        fail("UNVERIFIED_REVIEW_MARKUP")


def validate_primary_navigation(config: str, install: str) -> None:
    if re.search(r"(?m)^\s*-\s+install\.md\s*$", config) is None:
        fail("INSTALL_NOT_IN_PRIMARY_NAVIGATION")
    if frontmatter_value(install, "nav_title") != "Install":
        fail("INSTALL_NAV_TITLE_DRIFT")

    social_required = (
        "card: summary_large_image",
        "name: Clean Room Launcher (CLROOM)",
        "https://github.com/y-sor/clean-room-launcher",
        "path: /assets/clean-room-launcher-hero.png",
        "alt: Clean Room Launcher (CLROOM) clean and selective coding-agent launch",
    )
    for item in social_required:
        if item not in config:
            fail(f"SOCIAL_DISCOVERY_DEFAULT_MISSING:{item}")


def validate_problem_routing(problem_index: str) -> None:
    start = problem_index.find("## Start from the closest symptom")
    if start < 0:
        fail("PROBLEM_ROUTING_SECTION_MISSING")
    end = problem_index.find('<a id="apps-runners-and-ci"></a>', start)
    if end < 0:
        fail("PROBLEM_ROUTING_BOUNDARY_MISSING")
    routing = problem_index[start:end]

    required_anchors = {
        "mcp-tool-context-overload",
        "mcp-env-var-not-in-process",
        "codex-plugin-mcp-composition",
        "subagents-inherit-mcp-tools",
        "inspect-resolved-launch",
        "codex-global-skills-keep-project-skills",
    }
    routed = set(re.findall(r"\]\(#([^)]+)\)", routing))
    missing = sorted(required_anchors - routed)
    if missing:
        fail("TOP_ROUTING_TARGET_MISSING:" + ",".join(missing))

    for anchor in routed:
        if f'<a id="{anchor}"></a>' not in problem_index:
            fail(f"BROKEN_TOP_ROUTING_ANCHOR:{anchor}")


def validate_llms(llms: str) -> None:
    required = (
        "MCP/tool context overhead",
        "bounded Codex plugin + MCP composition",
        "top-level per-worker resource choices",
        "provider-owned subagent scoping",
        "OpenAI API/Agents tool-search behavior and Codex CLI behavior are separate surfaces",
        "Terminology glossary: https://y-sor.github.io/clean-room-launcher/glossary/",
        "Release verification, provenance, SBOM, and trust boundaries: https://y-sor.github.io/clean-room-launcher/verify-release/",
        "Documentation versions and historical-release routing: https://y-sor.github.io/clean-room-launcher/documentation-versions/",
        "Support and safe issue routing: https://y-sor.github.io/clean-room-launcher/support/",
        'rel="describedby"',
    )
    for item in required:
        if item not in llms:
            fail(f"LLMS_ROUTING_MISSING:{item}")


def validate_descriptions(root: Path) -> None:
    public_pages = (
        "docs/agent-runners.md",
        "docs/claude-code.md",
        "docs/codex.md",
        "docs/configuration-matrix.md",
        "docs/demo.md",
        "docs/documentation-versions.md",
        "docs/faq.md",
        "docs/glossary.md",
        "docs/index.md",
        "docs/install.md",
        "docs/limitations.md",
        "docs/problem-index.md",
        "docs/providers.md",
        "docs/skill-sets.md",
        "docs/SUPPORT.md",
        "docs/threat-model.md",
        "docs/upgrade-rollback.md",
        "docs/use-cases.md",
        "docs/verify-release.md",
        "docs/when-to-use-clroom.md",
        "docs/why-clroom.md",
    )
    seen_descriptions: dict[str, str] = {}
    seen_titles: dict[str, str] = {}

    for relative in public_pages:
        markdown = read(root, relative)
        title = frontmatter_value(markdown, "title")
        description = frontmatter_value(markdown, "description")

        if len(title) > 90:
            fail(f"TITLE_TOO_LONG:{relative}:chars={len(title)}")
        if not 70 <= len(description) <= 160:
            fail(f"DESCRIPTION_LENGTH:{relative}:chars={len(description)}")

        title_key = " ".join(title.casefold().split())
        desc_key = " ".join(description.casefold().split())
        if title_key in seen_titles:
            fail(f"DUPLICATE_TITLE:{relative}:matches={seen_titles[title_key]}")
        if desc_key in seen_descriptions:
            fail(f"DUPLICATE_DESCRIPTION:{relative}:matches={seen_descriptions[desc_key]}")
        seen_titles[title_key] = relative
        seen_descriptions[desc_key] = relative

    requirements = {
        "docs/codex.md": ("mcp", "plugin", "inspect"),
        "docs/use-cases.md": ("mcp", "skill", "ci"),
        "docs/agent-runners.md": ("worker", "mcp"),
        "docs/demo.md": ("first-run", "codex", "claude", "inspect"),
        "docs/documentation-versions.md": ("current", "historical", "release", "qualification"),
        "docs/glossary.md": ("clean", "skill", "plugin", "mcp", "subagent", "qualified"),
        "docs/when-to-use-clroom.md": ("subagent", "mcp"),
        "docs/problem-index.md": ("codex", "claude", "mcp", "clroom"),
        "docs/threat-model.md": ("prompt-injection", "clroom"),
        "docs/SUPPORT.md": ("support", "bug", "security", "version"),
        "docs/verify-release.md": ("checksum", "provenance", "sbom", "immutable"),
    }
    for relative, terms in requirements.items():
        description = frontmatter_value(read(root, relative), "description")
        require_terms(description, terms, relative)


def validate(root: Path) -> None:
    head = read(root, "docs/_includes/head.html")
    footer = read(root, "docs/_includes/footer.html")
    header = read(root, "docs/_includes/header.html")
    analytics_marker = "static.cloudflareinsights.com/beacon.min.js"
    if (head + footer).count(analytics_marker) != 1:
        fail("ANALYTICS_BEACON_COUNT_DRIFT")
    if '<nav class="site-nav" aria-label="Primary navigation">' not in header:
        fail("PRIMARY_NAV_ACCESSIBLE_NAME_MISSING")
    validate_schema(head)
    if 'rel="describedby"' not in head or "'/llms.txt' | relative_url" not in head:
        fail("LLMS_DISCOVERY_RELATION_MISSING")
    validate_primary_navigation(
        read(root, "docs/_config.yml"),
        read(root, "docs/install.md"),
    )
    validate_problem_routing(read(root, "docs/problem-index.md"))
    validate_llms(read(root, "docs/llms.txt"))
    validate_descriptions(root)
    print("DISCOVERY_METADATA_ROUTING_PASS")


def expect_failure(fn, reason: str) -> None:
    try:
        fn()
    except DiscoveryMetadataError as exc:
        if reason not in str(exc):
            fail(f"SELF_TEST_WRONG_FAILURE:expected={reason}:actual={exc}")
        return
    fail(f"SELF_TEST_NEGATIVE_PASSED:{reason}")


def self_test() -> None:
    good_schema = """<script>
{
  "@type": "SoftwareSourceCode",
  "codeRepository": "https://github.com/y-sor/clean-room-launcher",
  "programmingLanguage": "Rust",
  "runtimePlatform": "macOS on Apple Silicon",
  "license": "https://www.mozilla.org/MPL/2.0/"
}
</script>"""
    validate_schema(good_schema)
    expect_failure(
        lambda: validate_schema(good_schema.replace("SoftwareSourceCode", "SoftwareApplication")),
        "SOFTWARE_SOURCE_SCHEMA_MISSING",
    )

    good_problem = """## Start from the closest symptom
- [a](#mcp-tool-context-overload)
- [b](#mcp-env-var-not-in-process)
- [c](#codex-plugin-mcp-composition)
- [d](#subagents-inherit-mcp-tools)
- [e](#inspect-resolved-launch)
- [f](#codex-global-skills-keep-project-skills)

<a id="apps-runners-and-ci"></a>
<a id="mcp-tool-context-overload"></a>
<a id="mcp-env-var-not-in-process"></a>
<a id="codex-plugin-mcp-composition"></a>
<a id="subagents-inherit-mcp-tools"></a>
<a id="inspect-resolved-launch"></a>
<a id="codex-global-skills-keep-project-skills"></a>
"""
    validate_problem_routing(good_problem)
    expect_failure(
        lambda: validate_problem_routing(good_problem.replace(
            '<a id="inspect-resolved-launch"></a>', ""
        )),
        "BROKEN_TOP_ROUTING_ANCHOR",
    )

    sample_desc = "A" * 70
    sample_title = "Sample page"
    fixture = f"""---
title: {sample_title}
description: {sample_desc}
---
"""
    assert frontmatter_value(fixture, "title") == sample_title
    assert frontmatter_value(fixture, "description") == sample_desc

    print("DISCOVERY_METADATA_ROUTING_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--root", type=Path)
    group.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    try:
        if args.root is not None:
            validate(args.root.resolve())
            self_test()
        else:
            self_test()
    except DiscoveryMetadataError as exc:
        print(f"DISCOVERY_METADATA_ROUTING_FAIL:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
