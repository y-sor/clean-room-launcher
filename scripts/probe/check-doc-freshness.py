#!/usr/bin/env python3
"""Fail closed when public release-state wording drifts from the source version."""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import tomllib
from pathlib import Path


class FreshnessError(RuntimeError):
    pass


def fail(message: str) -> None:
    raise FreshnessError(message)


def package_version(root: Path) -> str:
    try:
        with (root / "Cargo.toml").open("rb") as handle:
            value = tomllib.load(handle)["package"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError) as exc:
        fail(f"CARGO_VERSION_UNREADABLE:{exc}")
    if not isinstance(value, str) or not re.fullmatch(r"\d+\.\d+\.\d+", value):
        fail("CARGO_VERSION_INVALID")
    return value


def current_security_row(security: str, version: str) -> str:
    pattern = re.compile(rf"^\|\s*`{re.escape(version)}`\s*\|\s*(.*?)\s*\|$", re.MULTILINE)
    match = pattern.search(security)
    if match is None:
        fail(f"SECURITY_CURRENT_VERSION_MISSING:v{version}")
    return match.group(1)


def validate(root: Path) -> None:
    version = package_version(root)
    tag = f"v{version}"

    try:
        readme = (root / "README.md").read_text(encoding="utf-8")
        security = (root / "SECURITY.md").read_text(encoding="utf-8")
    except OSError as exc:
        fail(f"PUBLIC_STATUS_FILE_UNREADABLE:{exc}")

    expected_readme = f"Current source version: `{tag}`."
    if expected_readme not in readme:
        fail(f"README_CURRENT_SOURCE_VERSION_MISSING:{tag}")

    if "https://github.com/y-sor/clean-room-launcher/releases/latest" not in readme:
        fail("README_LATEST_RELEASE_LINK_MISSING")

    stale_readme_patterns = (
        rf"prepared\s+for\s+`?{re.escape(tag)}`?",
        rf"{re.escape(tag)}[^\n]{{0,80}}\bcandidate\b",
    )
    for pattern in stale_readme_patterns:
        if re.search(pattern, readme, flags=re.IGNORECASE):
            fail(f"README_BOUNDARY_UNSTABLE_STATUS:{tag}")

    status = current_security_row(security, version)
    normalized = status.lower()
    if "current source version" not in normalized:
        fail(f"SECURITY_CURRENT_SOURCE_STATUS_MISSING:{tag}")
    if "github releases" not in normalized:
        fail(f"SECURITY_RELEASE_AUTHORITY_MISSING:{tag}")
    if re.search(r"\b(candidate|prepared|unpublished|draft)\b", normalized):
        fail(f"SECURITY_BOUNDARY_UNSTABLE_STATUS:{tag}")

    print(f"PUBLIC_DOC_FRESHNESS_PASS source={tag}")


def fixture_root(base: Path, version: str, readme_status: str, security_status: str) -> Path:
    root = base / "fixture"
    root.mkdir(parents=True, exist_ok=True)
    (root / "Cargo.toml").write_text(
        f'[package]\nname = "fixture"\nversion = "{version}"\n',
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        readme_status
        + "\n[latest GitHub release](https://github.com/y-sor/clean-room-launcher/releases/latest)\n",
        encoding="utf-8",
    )
    (root / "SECURITY.md").write_text(
        "| Version | Status |\n| --- | --- |\n"
        + f"| `{version}` | {security_status} |\n",
        encoding="utf-8",
    )
    return root


def expect_failure(root: Path, reason: str) -> None:
    try:
        validate(root)
    except FreshnessError as exc:
        if reason not in str(exc):
            fail(f"SELF_TEST_WRONG_FAILURE:expected={reason}:actual={exc}")
        return
    fail(f"SELF_TEST_NEGATIVE_PASSED:{reason}")


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="clroom-doc-freshness-") as temp:
        base = Path(temp)

        positive = fixture_root(
            base / "positive",
            "9.8.7",
            "Current source version: `v9.8.7`.",
            "Current source version; publication status and artifacts are authoritative in GitHub Releases",
        )
        validate(positive)

        stale_readme = fixture_root(
            base / "stale-readme",
            "9.8.7",
            "Current source version: `v9.8.7`. This source tree is prepared for `v9.8.7`.",
            "Current source version; publication status and artifacts are authoritative in GitHub Releases",
        )
        expect_failure(stale_readme, "README_BOUNDARY_UNSTABLE_STATUS")

        stale_security = fixture_root(
            base / "stale-security",
            "9.8.7",
            "Current source version: `v9.8.7`.",
            "Current source version candidate; publication status and artifacts are authoritative in GitHub Releases",
        )
        expect_failure(stale_security, "SECURITY_BOUNDARY_UNSTABLE_STATUS")

        wrong_version = fixture_root(
            base / "wrong-version",
            "9.8.7",
            "Current source version: `v9.8.6`.",
            "Current source version; publication status and artifacts are authoritative in GitHub Releases",
        )
        expect_failure(wrong_version, "README_CURRENT_SOURCE_VERSION_MISSING")

    print("PUBLIC_DOC_FRESHNESS_SELF_TEST_PASS")


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
    except FreshnessError as exc:
        print(f"PUBLIC_DOC_FRESHNESS_FAIL:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
