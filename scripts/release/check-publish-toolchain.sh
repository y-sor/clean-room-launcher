#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'PUBLISH_TOOLCHAIN_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

repository="${GITHUB_REPOSITORY:-y-sor/clean-room-launcher}"

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
  local create_help='--draft --prerelease --notes-file --title --verify-tag --repo'
  local edit_help='--draft --latest --notes-file --title --verify-tag --repo'
  local view_help='--json --repo'
  local upload_help='--clobber --repo'
  local download_help='--dir --pattern --repo'
  local attest_help='--bundle --source-digest --source-ref --signer-workflow --deny-self-hosted-runners --predicate-type'
  require_help_markers "SELF_CREATE" "$create_help" --draft --prerelease --notes-file --title --verify-tag --repo
  require_help_markers "SELF_EDIT" "$edit_help" --draft --latest --notes-file --title --verify-tag --repo
  require_help_markers "SELF_VIEW" "$view_help" --json --repo
  require_help_markers "SELF_UPLOAD" "$upload_help" --clobber --repo
  require_help_markers "SELF_DOWNLOAD" "$download_help" --dir --pattern --repo
  require_help_markers "SELF_ATTEST" "$attest_help" --bundle --source-digest --source-ref --signer-workflow --deny-self-hosted-runners --predicate-type
  if has_help_markers "$edit_help" --missing-flag; then
    fail "SELF_TEST_NEGATIVE_ACCEPTED"
  fi
  echo "PUBLISH_TOOLCHAIN_SELF_TEST_PASS"
}

case "${1:-}" in
  --self-test)
    [[ $# -eq 1 ]] || fail "USAGE:check-publish-toolchain.sh_[--self-test|--capabilities-only]" 64
    self_test
    exit 0
    ;;
  --capabilities-only)
    [[ $# -eq 1 ]] || fail "USAGE:check-publish-toolchain.sh_[--self-test|--capabilities-only]" 64
    mode=capabilities
    ;;
  "")
    [[ $# -eq 0 ]] || fail "USAGE:check-publish-toolchain.sh_[--self-test|--capabilities-only]" 64
    mode=full
    ;;
  *)
    fail "USAGE:check-publish-toolchain.sh_[--self-test|--capabilities-only]" 64
    ;;
esac

command -v gh >/dev/null 2>&1 || fail "COMMAND_MISSING:gh" 74
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED" 74

create_help=$(gh release create --help) || fail "RELEASE_CREATE_HELP"
edit_help=$(gh release edit --help) || fail "RELEASE_EDIT_HELP"
view_help=$(gh release view --help) || fail "RELEASE_VIEW_HELP"
upload_help=$(gh release upload --help) || fail "RELEASE_UPLOAD_HELP"
download_help=$(gh release download --help) || fail "RELEASE_DOWNLOAD_HELP"

require_help_markers "RELEASE_CREATE_CAPABILITY" "$create_help" --draft --prerelease --notes-file --title --verify-tag --repo
require_help_markers "RELEASE_EDIT_CAPABILITY" "$edit_help" --draft --latest --notes-file --title --verify-tag --repo
require_help_markers "RELEASE_VIEW_CAPABILITY" "$view_help" --json --repo
require_help_markers "RELEASE_UPLOAD_CAPABILITY" "$upload_help" --clobber --repo
require_help_markers "RELEASE_DOWNLOAD_CAPABILITY" "$download_help" --dir --pattern --repo

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-publish-toolchain.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

gh release view --repo "$repository" \
  --json databaseId,tagName,isDraft,isPrerelease,isImmutable,publishedAt,assets \
  >"$tmp/latest-cli.json" || fail "RELEASE_VIEW_JSON_CAPABILITY"

release_id=$(python3 - "$tmp/latest-cli.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
release_id = data.get("databaseId")
if not isinstance(release_id, int):
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
print(release_id)
PY
) || exit 1

[[ "$release_id" =~ ^[0-9]+$ ]] || fail "RELEASE_DATABASE_ID"
gh api "repos/$repository/releases/$release_id" >"$tmp/release-by-id.json" \
  || fail "RELEASE_BY_ID_API_CAPABILITY"
python3 - "$tmp/latest-cli.json" "$tmp/release-by-id.json" <<'PY' || exit 1
import json, sys
cli = json.load(open(sys.argv[1], encoding="utf-8"))
api = json.load(open(sys.argv[2], encoding="utf-8"))
if api.get("id") != cli.get("databaseId"):
    raise SystemExit("PUBLISH_TOOLCHAIN_BLOCKED:RELEASE_ID_SPLIT")
if api.get("tag_name") != cli.get("tagName"):
    raise SystemExit("PUBLISH_TOOLCHAIN_BLOCKED:RELEASE_TAG_SPLIT")
if api.get("draft") is not False or api.get("prerelease") is not False:
    raise SystemExit("PUBLISH_TOOLCHAIN_BLOCKED:RELEASE_API_STATE")
PY

gh api "repos/$repository/releases/latest" >"$tmp/latest-api.json" || fail "LATEST_API_CAPABILITY"

if [[ "$mode" == capabilities ]]; then
  printf 'PUBLISH_TOOLCHAIN_CAPABILITY_PASS mode=capabilities gh=%s\n' "$(gh --version | head -n 1)"
  exit 0
fi

attest_help=$(gh attestation verify --help) || fail "ATTESTATION_VERIFY_HELP"
require_help_markers "ATTESTATION_VERIFY_CAPABILITY" "$attest_help" \
  --bundle --source-digest --source-ref --signer-workflow --deny-self-hosted-runners --predicate-type

gh api "repos/$repository/immutable-releases" --jq .enabled >"$tmp/immutable.txt" \
  || fail "IMMUTABLE_POLICY_API_CAPABILITY"
[[ "$(cat "$tmp/immutable.txt")" == true ]] || fail "IMMUTABLE_POLICY_DISABLED"

printf 'PUBLISH_TOOLCHAIN_CAPABILITY_PASS mode=full gh=%s\n' "$(gh --version | head -n 1)"
