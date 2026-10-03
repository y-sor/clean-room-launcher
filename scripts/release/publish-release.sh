#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'GUARDED_PUBLISH_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

[[ $# -eq 2 ]] || fail "USAGE:publish-release.sh_vX.Y.Z_EXPECTED_SHA" 64
tag=$1
expected=$2
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "STABLE_TAG_REQUIRED"
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || fail "EXPECTED_SHA_INVALID"
[[ "${CLROOM_OWNER_PUBLISH_APPROVED:-}" == "YES:$tag:$expected" ]] || fail "OWNER_APPROVAL_TOKEN" 65

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"
repository="y-sor/clean-room-launcher"
version=${tag#v}

for name in git gh python3 shasum; do
  command -v "$name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$name" 74
done
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED" 74
[[ "$(git rev-parse HEAD)" == "$expected" ]] || fail "LOCAL_HEAD_MISMATCH"
[[ -z "$(git status --porcelain)" ]] || fail "WORKTREE_NOT_CLEAN"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-guarded-publish.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

bash scripts/release/verify-draft-release.sh "$tag" "$expected" || fail "DRAFT_VERIFY"

bash scripts/release/resolve-pretag-stage.sh "$version" "$expected" "$tmp/stage" || fail "PRETAG_STAGE"
source scripts/release/provider-pins.sh
review_digest=$(python3 - "reports/release/v${version}-review.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["reviewed_content_digest"])
PY
)
python3 scripts/release/verify-pretag-stage.py \
  --dir "$tmp/stage" --version "$version" --source-head "$expected" \
  --source-tree "$(git rev-parse "HEAD^{tree}")" \
  --reviewed-content-digest "$review_digest" \
  --codex-version "$CODEX_VERSION" --claude-version "$CLAUDE_VERSION" || fail "PRETAG_STAGE_BINDING"

git fetch --quiet origin main || fail "MAIN_REFRESH"
[[ "$(git rev-parse FETCH_HEAD)" == "$expected" ]] || fail "MAIN_DRIFT_ACTION_TIME"
git fetch --quiet --force origin "refs/tags/$tag:refs/tags/$tag" || fail "TAG_REFRESH"
[[ "$(git rev-parse "refs/tags/$tag^{}")" == "$expected" ]] || fail "TAG_TARGET_ACTION_TIME"
[[ "$(gh api "repos/$repository/immutable-releases" --jq .enabled 2>/dev/null)" == true ]] || fail "IMMUTABLE_RELEASE_POLICY_ACTION_TIME"

title=$(python3 - "$tmp/stage/publish-preview.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["release_title"])
PY
)
python3 scripts/release/release-external-action.py publish \
  --repository "$repository" \
  --tag "$tag" \
  --title "$title" \
  --notes-file "$tmp/stage/release-notes.md" \
  --preview-json "$tmp/stage/publish-preview.json" \
  --apply || fail "PUBLISH_EXTERNAL_ACTION"
