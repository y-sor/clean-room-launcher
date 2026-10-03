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

capture_and_validate_draft() {
  local output=$1
  local draft_id
  draft_id=$(gh release view "$tag" --json databaseId --jq .databaseId) || fail "DRAFT_QUERY"
  [[ "$draft_id" =~ ^[0-9]+$ ]] || fail "DRAFT_ID_INVALID"
  gh api "repos/$repository/releases/$draft_id" >"$output" || fail "DRAFT_QUERY"
  python3 - "$output" "$tmp/stage/publish-preview.json" "$tmp/stage/pretag-manifest.json" <<'PY'
import hashlib, json, sys
release = json.load(open(sys.argv[1], encoding="utf-8"))
preview = json.load(open(sys.argv[2], encoding="utf-8"))
manifest = json.load(open(sys.argv[3], encoding="utf-8"))
if release.get("tag_name") != preview["tag_name"] or release.get("name") != preview["release_title"]:
    raise SystemExit("identity")
if release.get("draft") is not True or release.get("prerelease") is not preview["prerelease"]:
    raise SystemExit("state")
if (release.get("body") or "").rstrip() != preview["body"].rstrip():
    raise SystemExit("body")
assets = release.get("assets") or []
if {item.get("name") for item in assets} != set(preview["expected_assets"]):
    raise SystemExit("assets")
for item in assets:
    name = item.get("name")
    if name in manifest["files"]:
        digest = item.get("digest") or ""
        if digest != "sha256:" + manifest["files"][name]:
            raise SystemExit("asset-digest:" + str(name))
fingerprint = {
    "id": release.get("id"),
    "tag_name": release.get("tag_name"),
    "name": release.get("name"),
    "draft": release.get("draft"),
    "prerelease": release.get("prerelease"),
    "body": release.get("body"),
    "updated_at": release.get("updated_at"),
    "assets": sorted(
        ({
            "id": item.get("id"),
            "name": item.get("name"),
            "size": item.get("size"),
            "digest": item.get("digest"),
            "updated_at": item.get("updated_at"),
        } for item in assets),
        key=lambda item: item["name"],
    ),
}
raw = json.dumps(fingerprint, sort_keys=True, separators=(",", ":")).encode()
print(hashlib.sha256(raw).hexdigest())
PY
}

git fetch --quiet origin main || fail "MAIN_REFRESH"
[[ "$(git rev-parse FETCH_HEAD)" == "$expected" ]] || fail "MAIN_DRIFT_ACTION_TIME"
git fetch --quiet --force origin "refs/tags/$tag:refs/tags/$tag" || fail "TAG_REFRESH"
[[ "$(git rev-parse "refs/tags/$tag^{}")" == "$expected" ]] || fail "TAG_TARGET_ACTION_TIME"
[[ "$(gh api "repos/$repository/immutable-releases" --jq .enabled 2>/dev/null)" == true ]] || fail "IMMUTABLE_RELEASE_POLICY_ACTION_TIME"

fingerprint_before=$(capture_and_validate_draft "$tmp/draft-before.json") || fail "DRAFT_FINGERPRINT_BEFORE"
fingerprint_action=$(capture_and_validate_draft "$tmp/draft-action.json") || fail "DRAFT_FINGERPRINT_ACTION"
[[ "$fingerprint_action" == "$fingerprint_before" ]] || fail "DRAFT_CHANGED_BETWEEN_VERIFY_AND_ACTION"
echo "DRAFT_FINGERPRINT_ACTION_TIME=PASS sha256=$fingerprint_action"

title=$(python3 - "$tmp/stage/publish-preview.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["release_title"])
PY
)
gh release edit "$tag" --draft=false --latest --verify-tag \
  --title "$title" --notes-file "$tmp/stage/release-notes.md" || fail "PUBLISH_TRANSITION"

gh api "repos/$repository/releases/tags/$tag" >"$tmp/published.json" || fail "PUBLISHED_QUERY"
python3 - "$tmp/published.json" "$tmp/stage/publish-preview.json" "$tmp/draft-action.json" <<'PY' || fail "PUBLISHED_RECONCILIATION"
import json, sys
published = json.load(open(sys.argv[1], encoding="utf-8"))
preview = json.load(open(sys.argv[2], encoding="utf-8"))
before = json.load(open(sys.argv[3], encoding="utf-8"))
if published.get("tag_name") != preview["tag_name"] or published.get("name") != preview["release_title"]:
    raise SystemExit("identity")
if published.get("draft") is not False or published.get("prerelease") is not preview["prerelease"]:
    raise SystemExit("state")
if not published.get("published_at") or published.get("immutable") is not True:
    raise SystemExit("published-or-immutable")
if (published.get("body") or "").rstrip() != preview["body"].rstrip():
    raise SystemExit("body")
before_assets = {
    (item.get("name"), item.get("id"), item.get("size"), item.get("digest"))
    for item in before.get("assets") or []
}
after_assets = {
    (item.get("name"), item.get("id"), item.get("size"), item.get("digest"))
    for item in published.get("assets") or []
}
if after_assets != before_assets:
    raise SystemExit("asset-drift")
PY

gh release list --limit 100 --json tagName,isDraft,isPrerelease,isLatest,isImmutable,publishedAt >"$tmp/releases.json" || fail "LATEST_QUERY"
python3 - "$tmp/releases.json" "$tag" <<'PY' || fail "LATEST_RECONCILIATION"
import json, sys
items, tag = json.load(open(sys.argv[1], encoding="utf-8")), sys.argv[2]
matches = [item for item in items if item.get("tagName") == tag]
if len(matches) != 1:
    raise SystemExit("release-count")
item = matches[0]
if item.get("isDraft") or item.get("isPrerelease") or not item.get("isLatest") or not item.get("isImmutable") or not item.get("publishedAt"):
    raise SystemExit("latest-state")
PY

echo "GUARDED_PUBLISH_PASS tag=$tag target=$expected"
