#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'PROVIDER_PIN_CHECK_BLOCKED:%s\n' "$1" >&2
  exit 1
}

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
# shellcheck source=provider-pins.sh
source "$root/scripts/release/provider-pins.sh"

command -v npm >/dev/null 2>&1 || fail "NPM_REQUIRED"

mismatch=0
verify_latest() {
  local package=$1 expected=$2 latest
  latest=$(npm view "$package" dist-tags.latest --silent) || fail "LATEST_LOOKUP_FAILED"
  if [[ "$latest" != "$expected" ]]; then
    printf 'PROVIDER_LATEST_MISMATCH package=%s pinned=%s latest=%s\n' "$package" "$expected" "$latest" >&2
    mismatch=1
  fi
}

verify_integrity() {
  local spec=$1 expected_sha512=$2 actual
  actual=$(npm view "$spec" dist.integrity --silent) || fail "INTEGRITY_LOOKUP_FAILED"
  if [[ "$actual" != "sha512-$expected_sha512" ]]; then
    printf 'PROVIDER_REGISTRY_INTEGRITY_MISMATCH spec=%s expected=sha512-%s actual=%s\n' \
      "$spec" "$expected_sha512" "$actual" >&2
    mismatch=1
  fi
}

verify_latest '@openai/codex' "$CODEX_VERSION"
verify_latest '@anthropic-ai/claude-code' "$CLAUDE_VERSION"
verify_latest '@anthropic-ai/claude-code-darwin-arm64' "$CLAUDE_VERSION"
verify_integrity "@openai/codex@$CODEX_VERSION" "$CODEX_SHA512"
verify_integrity "@openai/codex@$CODEX_VERSION-darwin-arm64" "$CODEX_PLATFORM_SHA512"
verify_integrity "@anthropic-ai/claude-code@$CLAUDE_VERSION" "$CLAUDE_SHA512"
verify_integrity "@anthropic-ai/claude-code-darwin-arm64@$CLAUDE_VERSION" "$CLAUDE_PLATFORM_SHA512"

[[ $mismatch -eq 0 ]] || fail "PIN_REGISTRY_MISMATCH"
printf 'PROVIDER_PIN_CHECK_PASS codex=%s claude=%s\n' "$CODEX_VERSION" "$CLAUDE_VERSION"
