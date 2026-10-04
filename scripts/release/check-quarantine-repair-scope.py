#!/usr/bin/env python3
import argparse
import fnmatch
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]

ALLOWED_PATTERNS = (
    ".github/workflows/release*.yml",
    "scripts/release/**",
    "docs/release/**",
    "schemas/release/**",
    "tests/contracts/**",
)

REPAIR_ANCHORS = (
    ".github/workflows/release",
    "scripts/release/",
)


def allowed(path: str) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in ALLOWED_PATTERNS)


def validate_paths(paths: list[str]) -> list[str]:
    errors: list[str] = []
    if not paths:
        errors.append("EMPTY_DIFF")
        return errors
    for path in paths:
        if not allowed(path):
            errors.append(f"OUT_OF_SCOPE:{path}")
    if not any(path.startswith(REPAIR_ANCHORS) for path in paths):
        errors.append("NO_RELEASE_REPAIR_ANCHOR")
    return errors


def changed_paths(base: str, head: str) -> list[str]:
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, head],
        cwd=ROOT,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if ancestor.returncode != 0:
        raise SystemExit("QUARANTINE_REPAIR_SCOPE_BLOCKED:BASE_NOT_ANCESTOR")

    raw = subprocess.check_output(
        ["git", "diff", "--name-only", "--no-renames", "-z", f"{base}..{head}"],
        cwd=ROOT,
    )
    return [item.decode("utf-8") for item in raw.split(b"\0") if item]


def self_test() -> None:
    allowed_paths = [
        ".github/workflows/release-candidate.yml",
        ".github/workflows/release.yml",
        "scripts/release/check-harness-contract.py",
        "scripts/release/check-quarantine-repair-scope.py",
        "docs/release/RELEASE_CONTRACT.md",
        "schemas/release/release-contract-v1.json",
        "tests/contracts/gate_contract.rs",
    ]
    if validate_paths(allowed_paths):
        raise SystemExit("QUARANTINE_REPAIR_SCOPE_SELF_TEST:ALLOWED")

    blocked_sets = (
        ["README.md", "scripts/release/readiness.sh"],
        ["Cargo.toml", "scripts/release/readiness.sh"],
        ["src/main.rs", "scripts/release/readiness.sh"],
        [".github/workflows/ci.yml", "scripts/release/readiness.sh"],
        ["docs/release/RELEASE_CONTRACT.md"],
        [],
    )
    for paths in blocked_sets:
        if not validate_paths(paths):
            raise SystemExit(
                "QUARANTINE_REPAIR_SCOPE_SELF_TEST:BLOCKED_SET_ACCEPTED:"
                + ",".join(paths)
            )
    print("QUARANTINE_REPAIR_SCOPE_SELF_TEST_PASS")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base")
    parser.add_argument("--head")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return
    if not args.base or not args.head:
        parser.error("--base and --head are required")

    paths = changed_paths(args.base, args.head)
    errors = validate_paths(paths)
    if errors:
        for error in errors:
            print(f"QUARANTINE_REPAIR_SCOPE_ERROR:{error}")
        raise SystemExit("QUARANTINE_REPAIR_SCOPE_BLOCKED")

    print(
        "QUARANTINE_REPAIR_SCOPE_PASS "
        f"base={args.base} head={args.head} files={len(paths)}"
    )


if __name__ == "__main__":
    main()
