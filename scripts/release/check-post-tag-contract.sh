#!/usr/bin/env bash
set -euo pipefail

release_workflow=${1:-.github/workflows/release.yml}
ci_workflow=${2:-.github/workflows/ci.yml}

fail() {
  printf 'POST_TAG_CONTRACT_BLOCKED:%s\n' "$1" >&2
  exit 1
}

[[ -f "$release_workflow" && -f "$ci_workflow" ]] || fail "WORKFLOW_MISSING"

for forbidden in   'cargo test'   'cargo build'   'cargo fetch'   'packaging/build-artifacts.sh'   'provision-provider-canaries.sh'   'check-provider-pins.sh'   'local-codex-plugin-activation-smoke.sh'   'local-plugin-activation-smoke.sh'   'npm view'   'immutable-releases'   'check-release-contract.py'   'resolve-release-lifecycle.py'   'git ls-remote --symref origin HEAD'   'refs/heads/main'
do
  if grep -Fq -- "$forbidden" "$release_workflow"; then
    fail "POST_TAG_BLOCKER:$forbidden"
  fi
done

for required in   'resolve-pretag-stage.sh'   'verify-pretag-stage.py'   'uses: actions/attest@'   'gh release upload'   'DRAFT_PROMOTION_RECONCILE_PASS'
do
  grep -Fq -- "$required" "$release_workflow" || fail "PROMOTION_CONTRACT:$required"
done

python3 - "$ci_workflow" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding="utf-8")
on_block = text.split("concurrency:", 1)[0]
if 'tags:' in on_block or '- "v*"' in on_block or "- 'v*'" in on_block:
    raise SystemExit("POST_TAG_CONTRACT_BLOCKED:TAG_CI_TRIGGER")
PY

printf 'POST_TAG_CONTRACT_PASS release=%s ci=%s\n' "$release_workflow" "$ci_workflow"
