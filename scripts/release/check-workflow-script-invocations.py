#!/usr/bin/env python3
import argparse
import pathlib
import re
import subprocess
import sys

SCRIPT_RE = re.compile(r"(?P<path>(?:\./)?scripts/[A-Za-z0-9_./-]+\.sh)\b")
EXPLICIT_INTERPRETER_RE = re.compile(r"(?:^|[;&|()]|\b(?:if|then|while|until|do)\s+)\s*(?:bash|sh|source|\.)\s*$")

def fail(reason: str) -> None:
    raise SystemExit(f"WORKFLOW_SCRIPT_INVOCATION_BLOCKED:{reason}")

def normalize_path(raw: str) -> str:
    return raw[2:] if raw.startswith("./") else raw

def tracked_mode(path: str) -> str | None:
    proc = subprocess.run(
        ["git", "ls-files", "-s", "--", path],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        fail(f"GIT_MODE_QUERY:{path}")
    line = proc.stdout.strip()
    if not line:
        return None
    return line.split()[0]

def shell_payload(line: str) -> str:
    stripped = line.strip()
    if stripped.startswith("run:"):
        return stripped[4:].lstrip()
    return stripped

def direct_invocations(line: str) -> list[str]:
    payload = shell_payload(line)
    found: list[str] = []
    for match in SCRIPT_RE.finditer(payload):
        before = payload[: match.start()]
        if EXPLICIT_INTERPRETER_RE.search(before):
            continue
        path = normalize_path(match.group("path"))
        found.append(path)
    return found

def validate_lines(lines: list[str], mode_lookup) -> list[str]:
    errors: list[str] = []
    for number, line in enumerate(lines, 1):
        for path in direct_invocations(line):
            mode = mode_lookup(path)
            if mode is None:
                errors.append(f"UNTRACKED:{path}:line={number}")
            elif mode != "100755":
                errors.append(f"NOT_EXECUTABLE:{path}:mode={mode}:line={number}")
    return errors

def self_test() -> None:
    modes = {
        "scripts/release/helper.sh": "100644",
        "scripts/release/executable.sh": "100755",
    }
    lookup = modes.get

    bad = validate_lines(
        [
            "run: scripts/release/helper.sh --flag",
            "  if scripts/release/helper.sh; then",
        ],
        lookup,
    )
    if len(bad) != 2 or not all("NOT_EXECUTABLE" in item for item in bad):
        fail("SELF_TEST_DIRECT_NONEXEC")

    for line in [
        "run: bash scripts/release/helper.sh --flag",
        "  bash scripts/release/helper.sh --flag",
        "  if bash scripts/release/helper.sh --flag; then",
        "  source scripts/release/helper.sh",
        "  . scripts/release/helper.sh",
        "run: scripts/release/executable.sh --flag",
        "  ./scripts/release/executable.sh --flag",
    ]:
        if validate_lines([line], lookup):
            fail("SELF_TEST_SAFE_INVOCATION")

    missing = validate_lines(["run: scripts/release/missing.sh"], lookup)
    if missing != ["UNTRACKED:scripts/release/missing.sh:line=1"]:
        fail("SELF_TEST_UNTRACKED")

    print("WORKFLOW_SCRIPT_INVOCATION_SELF_TEST_PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--workflow-dir", default=".github/workflows")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    root = pathlib.Path(args.workflow_dir)
    if not root.is_dir():
        fail(f"WORKFLOW_DIR_MISSING:{root}")

    errors: list[str] = []
    for path in sorted([*root.glob("*.yml"), *root.glob("*.yaml")]):
        file_errors = validate_lines(path.read_text(encoding="utf-8").splitlines(), tracked_mode)
        errors.extend(f"{path}:{item}" for item in file_errors)

    if errors:
        for item in errors:
            print(item, file=sys.stderr)
        fail("DIRECT_NONEXECUTABLE_HELPER")

    print("WORKFLOW_SCRIPT_INVOCATION_CONTRACT_PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
