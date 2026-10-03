#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'PUBLISH_TOOLCHAIN_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

repository="y-sor/clean-room-launcher"

has_help_markers() {
  local body=$1
  shift
  local marker
  for marker in "$@"; do
    grep -Fq -- "$marker" <<<"$body" || return 1
  done
  return 0
}

require_help_markers() {
  local label=$1
  local body=$2
  shift 2
  local marker
  for marker in "$@"; do
    grep -Fq -- "$marker" <<<"$body" || fail "$label:$marker"
  done
}

self_test() {
  local edit_help='--draft --latest --notes-file --title --verify-tag'
  local view_help='--json'
  local download_help='--dir --pattern'
  local attest_help='--bundle --source-digest --source-ref --signer-workflow --deny-self-hosted-runners --predicate-type'
  require_help_markers "SELF_EDIT" "$edit_help" --draft --latest --notes-file --title --verify-tag
  require_help_markers "SELF_VIEW" "$view_help" --json
  require_help_markers "SELF_DOWNLOAD" "$download_help" --dir --pattern
  require_help_markers "SELF_ATTEST" "$attest_help" --bundle --source-digest --source-ref --signer-workflow --deny-self-hosted-runners --predicate-type
  if has_help_markers "$edit_help" --missing-flag; then
    fail "SELF_TEST_NEGATIVE_ACCEPTED"
  fi
  echo "PUBLISH_TOOLCHAIN_SELF_TEST_PASS"
}

if [[ "${1:-}" == "--self-test" ]]; then
  self_test
  exit 0
fi
[[ $# -eq 0 ]] || fail "USAGE:check-publish-toolchain.sh_[--self-test]" 64

command -v gh >/dev/null 2>&1 || fail "COMMAND_MISSING:gh" 74
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED" 74

edit_help=$(gh release edit --help) || fail "RELEASE_EDIT_HELP"
view_help=$(gh release view --help) || fail "RELEASE_VIEW_HELP"
download_help=$(gh release download --help) || fail "RELEASE_DOWNLOAD_HELP"
attest_help=$(gh attestation verify --help) || fail "ATTESTATION_VERIFY_HELP"

require_help_markers "RELEASE_EDIT_CAPABILITY" "$edit_help"   --draft --latest --notes-file --title --verify-tag
require_help_markers "RELEASE_VIEW_CAPABILITY" "$view_help" --json
require_help_markers "RELEASE_DOWNLOAD_CAPABILITY" "$download_help" --dir --pattern
require_help_markers "ATTESTATION_VERIFY_CAPABILITY" "$attest_help"   --bundle --source-digest --source-ref --signer-workflow --deny-self-hosted-runners --predicate-type

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-publish-toolchain.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

gh release view --repo "$repository"   --json databaseId,tagName,isDraft,isPrerelease,isImmutable,publishedAt,assets >"$tmp/latest-cli.json"   || fail "RELEASE_VIEW_JSON_CAPABILITY"

python3 - "$tmp/latest-cli.json" <<'PY' || exit 1
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
if not isinstance(data.get("databaseId"), int):
    raise SystemExit("PUBLISH_TOOLCHAIN_BLOCKED:RELEASE_DATABASE_ID")
tag = data.get("tagName") or ""
if not tag.startswith("v"):
    raise SystemExit("PUBLISH_TOOLCHAIN_BLOCKED:LATEST_TAG")
if data.get("isDraft") or data.get("isPrerelease"):
    raise SystemExit("PUBLISH_TOOLCHAIN_BLOCKED:LATEST_STATE")
if data.get("isImmutable") is not True or not data.get("publishedAt"):
    raise SystemExit("PUBLISH_TOOLCHAIN_BLOCKED:LATEST_IMMUTABILITY")
if not isinstance(data.get("assets"), list):
    raise SystemExit("PUBLISH_TOOLCHAIN_BLOCKED:RELEASE_ASSETS_FIELD")
PY

gh api "repos/$repository/releases/latest" >"$tmp/latest-api.json" || fail "LATEST_API_CAPABILITY"
gh api "repos/$repository/immutable-releases" --jq .enabled >"$tmp/immutable.txt"   || fail "IMMUTABLE_POLICY_API_CAPABILITY"
[[ "$(cat "$tmp/immutable.txt")" == true ]] || fail "IMMUTABLE_POLICY_DISABLED"

printf 'PUBLISH_TOOLCHAIN_CAPABILITY_PASS gh=%s\n' "$(gh --version | head -n 1)"
