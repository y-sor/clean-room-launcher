#!/usr/bin/env bash
set -euo pipefail

release_workflow=${1:-.github/workflows/release.yml}
ci_workflow=${2:-.github/workflows/ci.yml}
stage_resolver=${3:-scripts/release/resolve-pretag-stage.sh}
stage_verifier=${4:-scripts/release/verify-pretag-stage.py}

fail() {
  printf 'POST_TAG_CONTRACT_BLOCKED:%s\n' "$1" >&2
  exit 1
}

for path in "$release_workflow" "$ci_workflow" "$stage_resolver" "$stage_verifier"; do
  [[ -f "$path" ]] || fail "SURFACE_MISSING:$path"
done

# The tag workflow is promotion-only. These tokens represent classes of work
# that must have completed during PR/accepted-main rehearsal.
for forbidden in \
  'cargo test' \
  'cargo build' \
  'cargo fetch' \
  'rustup ' \
  'packaging/build-artifacts.sh' \
  'qualify-real-provider.sh' \
  'provision-provider-canaries.sh' \
  'check-provider-pins.sh' \
  'local-codex-plugin-activation-smoke.sh' \
  'local-plugin-activation-smoke.sh' \
  'npm view' \
  'immutable-releases' \
  'check-release-contract.py' \
  'resolve-release-lifecycle.py' \
  'git ls-remote --symref origin HEAD' \
  'refs/heads/main'
do
  if grep -Fq -- "$forbidden" "$release_workflow"; then
    fail "POST_TAG_BLOCKER:$forbidden"
  fi
done

# Do not allow a newly named release helper to smuggle a first-time blocker
# into the tag workflow. Only these source-pinned helpers are callable there.
python3 - "$release_workflow" <<'PY' || exit 1
from pathlib import Path
import re, sys
text = Path(sys.argv[1]).read_text(encoding="utf-8")
actual = set(re.findall(r"scripts/release/[A-Za-z0-9_.-]+", text))
allowed = {
    "scripts/release/provider-pins.sh",
    "scripts/release/resolve-pretag-stage.sh",
    "scripts/release/verify-pretag-stage.py",
}
unexpected = sorted(actual - allowed)
if unexpected:
    raise SystemExit("POST_TAG_CONTRACT_BLOCKED:POST_TAG_SCRIPT_NOT_ALLOWED:" + ",".join(unexpected))
PY

# The two helpers that remain reachable post-tag may only retrieve and verify
# already accepted bytes. They may not rebuild, reprovision, requalify, reopen
# mutable provider decisions, or call repository-admin policy endpoints.
for surface in "$stage_resolver" "$stage_verifier"; do
  for forbidden in \
    'cargo ' \
    'rustup ' \
    'npm ' \
    'curl ' \
    'wget ' \
    'packaging/build-artifacts.sh' \
    'qualify-real-provider.sh' \
    'provision-provider-canaries.sh' \
    'check-provider-pins.sh' \
    'local-codex-plugin-activation-smoke.sh' \
    'local-plugin-activation-smoke.sh' \
    'immutable-releases'
  do
    if grep -Fq -- "$forbidden" "$surface"; then
      fail "POST_TAG_HELPER_BLOCKER:$surface:$forbidden"
    fi
  done
done

for required in \
  'resolve-pretag-stage.sh' \
  'verify-pretag-stage.py' \
  'uses: actions/attest@' \
  'gh release upload' \
  'DRAFT_PROMOTION_RECONCILE_PASS'
do
  grep -Fq -- "$required" "$release_workflow" || fail "PROMOTION_CONTRACT:$required"
done

workflow_dir=$(cd "$(dirname "$release_workflow")" && pwd -P)
release_workflow_abs=$(cd "$(dirname "$release_workflow")" && pwd -P)/$(basename "$release_workflow")
python3 - "$workflow_dir" "$release_workflow_abs" <<'PY'
from pathlib import Path
import re
import sys

workflow_dir = Path(sys.argv[1])
release_workflow = Path(sys.argv[2]).resolve()

def on_block(text: str) -> list[str]:
    lines = text.splitlines()
    start = None
    inline = None
    for index, line in enumerate(lines):
        match = re.match(r"^on:\s*(.*)$", line)
        if match:
            start = index
            inline = match.group(1).strip()
            break
    if start is None:
        return []
    if inline:
        return [f"on: {inline}"]
    block = [lines[start]]
    for line in lines[start + 1:]:
        if line.strip() and not line.startswith((" ", "\t", "#")):
            break
        block.append(line)
    return block

def push_can_match_tags(block: list[str]) -> bool:
    if not block:
        return False
    if len(block) == 1:
        inline = block[0].split(":", 1)[1].strip()
        return bool(re.search(r"(^|[\[, ]+)push([\], ]+|$)", inline))
    index = 1
    while index < len(block):
        line = block[index]
        event = re.match(r"^  push:\s*(.*)$", line)
        if not event:
            index += 1
            continue
        inline = event.group(1).strip()
        if inline:
            return True
        nested = []
        index += 1
        while index < len(block):
            candidate = block[index]
            if candidate.strip() and len(candidate) - len(candidate.lstrip(" ")) <= 2:
                break
            nested.append(candidate)
            index += 1
        joined = "\n".join(nested)
        if re.search(r"^\s+tags(?:-ignore)?:", joined, flags=re.M):
            return True
        if not re.search(r"^\s+branches(?:-ignore)?:", joined, flags=re.M):
            return True
    return False

candidates = sorted(set(workflow_dir.glob("*.yml")) | set(workflow_dir.glob("*.yaml")))
for workflow in candidates:
    if workflow.resolve() == release_workflow:
        continue
    block = on_block(workflow.read_text(encoding="utf-8"))
    if push_can_match_tags(block):
        raise SystemExit(
            "POST_TAG_CONTRACT_BLOCKED:NON_RELEASE_TAG_TRIGGER:" + workflow.name
        )
PY

printf 'POST_TAG_CONTRACT_PASS release=%s ci=%s resolver=%s verifier=%s\n' \
  "$release_workflow" "$ci_workflow" "$stage_resolver" "$stage_verifier"
