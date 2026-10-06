#!/usr/bin/env python3
"""Validate CLROOM's public problem-language vector inventory."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

MIN_VECTOR_COUNT = 650
MIN_SECTION_COUNT = 47

REQUIRED_VECTORS = {
    "MCP context bloat",
    "Codex plugin and MCP same session",
    "disable global Codex skills keep project skills",
    "Claude subagent inherits MCP tools",
    "inspect Codex resolved launch",
    "Codex MCP bearer token env var missing",
    "thread level plugin MCP profile",
    "disable one Claude plugin skill",
    "coding agent configuration drift",
    "does CLROOM stop prompt injection",
    "verify CLROOM release",
    "CLROOM provenance attestation",
    "Claude skillOverrides",
    "Claude subagent MCP tools missing",
    "CLROOM docs don\'t match installed version",
    "does CLROOM collect telemetry",
    "does CLROOM send my code",
    "does CLROOM need an API key",
    "CLROOM license",
    "coding agent eval clean baseline",
    "has CLROOM been security audited",
    "Claude Code MEMORY.md stale",
    "MCP configured but tools missing",
    "clroom command not found",
}


class VectorError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise VectorError(message)


def normalize(value: str) -> str:
    return " ".join(value.casefold().split())


def parse(markdown: str) -> tuple[list[str], list[str]]:
    vectors = re.findall(r"^- \x60([^\x60]+)\x60$", markdown, flags=re.MULTILINE)
    sections = re.findall(r"^##\s+(.+)$", markdown, flags=re.MULTILINE)
    return vectors, sections


def validate_text(
    markdown: str,
    *,
    min_vectors: int = MIN_VECTOR_COUNT,
    min_sections: int = MIN_SECTION_COUNT,
    required_vectors: set[str] = REQUIRED_VECTORS,
    min_related_groups: int = 20,
) -> tuple[int, int]:
    vectors, sections = parse(markdown)

    if len(vectors) < min_vectors:
        fail(f"VECTOR_COUNT_REGRESSION:actual={len(vectors)}:minimum={min_vectors}")
    if len(sections) < min_sections:
        fail(f"VECTOR_CLUSTER_REGRESSION:actual={len(sections)}:minimum={min_sections}")

    seen: dict[str, str] = {}
    for vector in vectors:
        key = normalize(vector)
        if not key:
            fail("EMPTY_VECTOR")
        if key in seen:
            fail(f"DUPLICATE_VECTOR:{vector}:matches={seen[key]}")
        seen[key] = vector

    missing = sorted(vector for vector in required_vectors if normalize(vector) not in seen)
    if missing:
        fail("REQUIRED_VECTOR_MISSING:" + ",".join(missing))

    if markdown.count("<summary>More related wording and searches</summary>") < min_related_groups:
        fail("RELATED_WORDING_CLUSTER_COVERAGE_LOW")

    return len(vectors), len(sections)


def validate(root: Path) -> None:
    path = root / "docs" / "problem-index.md"
    try:
        markdown = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"PROBLEM_INDEX_UNREADABLE:{exc}")

    vectors, sections = validate_text(markdown)
    print(f"PROBLEM_VECTOR_COVERAGE_PASS vectors={vectors} sections={sections}")


def expect_failure(markdown: str, reason: str, **kwargs: object) -> None:
    try:
        validate_text(markdown, **kwargs)
    except VectorError as exc:
        if reason not in str(exc):
            fail(f"SELF_TEST_WRONG_FAILURE:expected={reason}:actual={exc}")
        return
    fail(f"SELF_TEST_NEGATIVE_PASSED:{reason}")


def self_test() -> None:
    required = {"alpha problem", "beta problem"}
    positive = """# Test

## One

- `alpha problem`
- `other wording`

<details>
<summary>More related wording and searches</summary>
</details>

## Two

- `beta problem`
"""

    # For fixture purposes the production minimums are lowered, while the same
    # duplicate/required-vector parser and normalization path is exercised.
    validate_text(
        positive,
        min_vectors=3,
        min_sections=2,
        required_vectors=required,
        min_related_groups=1,
    )

    expect_failure(
        positive + "- `Alpha   Problem`\n",
        "DUPLICATE_VECTOR",
        min_vectors=3,
        min_sections=2,
        required_vectors=required,
        min_related_groups=1,
    )
    expect_failure(
        positive,
        "VECTOR_COUNT_REGRESSION",
        min_vectors=4,
        min_sections=2,
        required_vectors=required,
        min_related_groups=1,
    )
    expect_failure(
        positive,
        "REQUIRED_VECTOR_MISSING",
        min_vectors=3,
        min_sections=2,
        required_vectors={"missing problem"},
        min_related_groups=1,
    )

    print("PROBLEM_VECTOR_COVERAGE_SELF_TEST_PASS")


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
    except VectorError as exc:
        print(f"PROBLEM_VECTOR_COVERAGE_FAIL:{exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
