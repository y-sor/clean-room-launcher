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

def yaml_key(line: str):
    match = re.match(
        r"^(?P<indent>[ \\t]*)(?:(?P<dq>\"[^\"]+\")|(?P<sq>'[^']+')|(?P<bare>[A-Za-z0-9_-]+))\\s*:\\s*(?P<rest>.*)$",
        line,
    )
    if not match:
        return None
    raw = match.group("dq") or match.group("sq") or match.group("bare")
    key = raw[1:-1] if raw[:1] in ("\"", "'") else raw
    return len(match.group("indent").replace("\\t", "  ")), key, match.group("rest").strip()

def on_block(text: str) -> list[str]:
    lines = text.splitlines()
    start = None
    inline = None
    for index, line in enumerate(lines):
        parsed = yaml_key(line)
        if parsed and parsed[0] == 0 and parsed[1] == "on":
            start = index
            inline = parsed[2]
            break
    if start is None:
        return []
    if inline:
        return [f"on: {inline}"]
    block = [lines[start]]
    for line in lines[start + 1:]:
        parsed = yaml_key(line)
        if parsed and parsed[0] == 0:
            break
        block.append(line)
    return block

def push_can_match_tags(block: list[str]) -> bool:
    if not block:
        return False
    if len(block) == 1:
        inline = block[0].split(":", 1)[1].strip()
        return bool(re.search(r"(^|[\\[, {]+)[\"']?push[\"']?([\\], }:]+|$)", inline))

    event_indents = []
    parsed_lines = []
    for index, line in enumerate(block[1:], start=1):
        parsed = yaml_key(line)
        parsed_lines.append((index, parsed))
        if parsed and parsed[0] > 0:
            event_indents.append(parsed[0])
    if not event_indents:
        return False
    event_indent = min(event_indents)

    for index, parsed in parsed_lines:
        if not parsed or parsed[0] != event_indent or parsed[1] != "push":
            continue
        inline = parsed[2]
        if inline:
            # Inline push mappings are deliberately treated as tag-capable.
            # Branch-only push filters must use block form so this guard can
            # prove their semantics instead of guessing.
            return True
        nested_keys = []
        cursor = index + 1
        while cursor < len(block):
            child = yaml_key(block[cursor])
            if child and child[0] <= event_indent:
                break
            if child and child[0] > event_indent:
                nested_keys.append((child[0], child[1]))
            cursor += 1
        if not nested_keys:
            return True
        filter_indent = min(indent for indent, _ in nested_keys)
        filters = {key for indent, key in nested_keys if indent == filter_indent}
        if "tags" in filters or "tags-ignore" in filters:
            return True
        if "branches" not in filters and "branches-ignore" not in filters:
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
