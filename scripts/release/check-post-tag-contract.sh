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

python3 - "$ci_workflow" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text(encoding="utf-8")
on_block = text.split("concurrency:", 1)[0]
if 'tags:' in on_block or '- "v*"' in on_block or "- 'v*'" in on_block:
    raise SystemExit("POST_TAG_CONTRACT_BLOCKED:TAG_CI_TRIGGER")
PY

printf 'POST_TAG_CONTRACT_PASS release=%s ci=%s resolver=%s verifier=%s\n' \
  "$release_workflow" "$ci_workflow" "$stage_resolver" "$stage_verifier"
