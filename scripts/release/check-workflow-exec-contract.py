#!/usr/bin/env python3
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
LOCAL_SCRIPT = re.compile(r"(?P<path>(?:\./)?(?:scripts|packaging)/[A-Za-z0-9_./-]+\.(?:sh|py))")
WRAPPERS = ("bash", "sh", "python3", "python", "source", ".")

def git_modes() -> dict[str, str]:
    out = subprocess.check_output(
        ["git", "ls-files", "--stage", "scripts", "packaging"],
        cwd=ROOT,
        text=True,
    )
    modes = {}
    for line in out.splitlines():
        meta, path = line.split("\t", 1)
        mode = meta.split(" ", 1)[0]
        modes[path] = mode
    return modes

def normalized(path: str) -> str:
    return path[2:] if path.startswith("./") else path

def needs_exec(line: str, path_start: int) -> bool:
    prefix = line[:path_start].rstrip()
    if not prefix:
        return True
    # YAML's scalar marker is not part of the shell command.
    prefix = re.sub(r"^\s*run:\s*", "", prefix)
    # Shell control keywords may precede a direct command.
    prefix = re.sub(r"(?:^|[;|&])\s*(?:if|then|elif|while|until)\s+$", "", prefix)
    words = re.findall(r"(?:^|\s)([A-Za-z0-9_.-]+)\s*$", prefix)
    if words and words[-1] in WRAPPERS:
        return False
    # Explicit command wrappers can also appear after shell control syntax.
    return re.search(r"(?:^|[;&|()]|\s)(?:bash|sh|python3|python|source|\.)\s+$", prefix) is None

def violations_for_text(text: str, modes: dict[str, str], workflow: str) -> list[str]:
    violations = []
    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.lstrip()
        if stripped.startswith("#"):
            continue
        for match in LOCAL_SCRIPT.finditer(raw):
            path = normalized(match.group("path"))
            mode = modes.get(path)
            if mode is None:
                continue
            if needs_exec(raw, match.start()) and not mode.endswith("755"):
                violations.append(
                    f"{workflow}:{lineno}:{path}:tracked_mode={mode}:direct_invocation_requires_executable"
                )
    return violations

def self_test() -> None:
    modes = {
        "scripts/release/nonexec.sh": "100644",
        "scripts/release/exec.sh": "100755",
        "scripts/release/tool.py": "100644",
    }
    bad = violations_for_text(
        """run: scripts/release/nonexec.sh arg
run: |
  if scripts/release/nonexec.sh arg; then
    true
  fi
""",
        modes,
        "fixture.yml",
    )
    if len(bad) != 2:
        raise SystemExit("WORKFLOW_EXEC_CONTRACT_SELF_TEST_FAIL_DIRECT_NONEXEC")
    for good in (
        "run: bash scripts/release/nonexec.sh arg",
        "run: sh scripts/release/nonexec.sh arg",
        "run: python3 scripts/release/tool.py arg",
        "run: scripts/release/exec.sh arg",
        "  source scripts/release/nonexec.sh",
    ):
        if violations_for_text(good, modes, "fixture.yml"):
            raise SystemExit("WORKFLOW_EXEC_CONTRACT_SELF_TEST_FAIL_WRAPPER")
    print("WORKFLOW_EXEC_CONTRACT_SELF_TEST_PASS")

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    modes = git_modes()
    violations = []
    for path in sorted((*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml"))):
        text = path.read_text(encoding="utf-8")
        violations.extend(violations_for_text(text, modes, str(path.relative_to(ROOT))))
    if violations:
        for item in violations:
            print(f"WORKFLOW_EXEC_CONTRACT_BLOCKED:{item}", file=sys.stderr)
        return 1
    print("WORKFLOW_EXEC_CONTRACT_PASS")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
