#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: CLROOM_OWNER_PUBLISH_APPROVED=YES:<tag>:<sha> bash scripts/release/publish-release.sh <tag> <expected-sha>" >&2
  exit 64
}

[[ $# -eq 2 ]] || usage
tag=$1
expected=$2
[[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]] || usage
[[ $expected =~ ^[0-9a-f]{40}$ ]] || usage
[[ ${CLROOM_OWNER_PUBLISH_APPROVED:-} == "YES:$tag:$expected" ]] || {
  echo "PUBLISH_GATE_BLOCKED:OWNER_APPROVAL_TOKEN" >&2
  exit 65
}

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"
repository="y-sor/clean-room-launcher"
version=${tag#v}

for name in git gh python3; do
  command -v "$name" >/dev/null 2>&1 || {
    echo "PUBLISH_GATE_BLOCKED:COMMAND_MISSING:$name" >&2
    exit 74
  }
done
gh auth status >/dev/null 2>&1 || {
  echo "PUBLISH_GATE_BLOCKED:GH_AUTH_REQUIRED" >&2
  exit 74
}
git diff --quiet
git diff --cached --quiet
git fetch --quiet origin main
[[ "$(git rev-parse FETCH_HEAD)" == "$expected" ]] || {
  echo "PUBLISH_GATE_BLOCKED:MAIN_DRIFT" >&2
  exit 66
}
[[ "$(git rev-parse HEAD)" == "$expected" ]] || {
  echo "PUBLISH_GATE_BLOCKED:LOCAL_HEAD" >&2
  exit 67
}

bash scripts/release/verify-draft-release.sh "$tag" "$expected" || {
  echo "PUBLISH_GATE_BLOCKED:DRAFT_VERIFY" >&2
  exit 70
}

source scripts/release/provider-pins.sh
source_tree=$(git rev-parse 'HEAD^{tree}')
review_digest=$(python3 - "$version" <<'PY'
import json, sys
with open(f"reports/release/v{sys.argv[1]}-review.json", encoding="utf-8") as handle:
    print(json.load(handle)["reviewed_content_digest"])
PY
)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-publish.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM
bash scripts/release/resolve-pretag-stage.sh "$version" "$expected" "$tmp/stage" || {
  echo "PUBLISH_GATE_BLOCKED:PRETAG_STAGE" >&2
  exit 70
}
python3 scripts/release/verify-pretag-stage.py \
  --dir "$tmp/stage" --version "$version" --source-head "$expected" \
  --source-tree "$source_tree" --reviewed-content-digest "$review_digest" \
  --codex-version "$CODEX_VERSION" --claude-version "$CLAUDE_VERSION" || {
  echo "PUBLISH_GATE_BLOCKED:PRETAG_BINDING" >&2
  exit 70
}
python3 scripts/release/verify-publishable-surface.py \
  --dir "$tmp/stage" --version "$version" --source-head "$expected" \
  --source-tree "$source_tree" --codex-version "$CODEX_VERSION" \
  --claude-version "$CLAUDE_VERSION" || {
  echo "PUBLISH_GATE_BLOCKED:PUBLISHABLE_SURFACE" >&2
  exit 70
}

immutable_enabled=$(gh api "repos/$repository/immutable-releases" --jq .enabled 2>/dev/null) || {
  echo "PUBLISH_GATE_BLOCKED:IMMUTABLE_POLICY_UNVERIFIED" >&2
  exit 74
}
[[ "$immutable_enabled" == true ]] || {
  echo "PUBLISH_GATE_BLOCKED:IMMUTABLE_POLICY_DISABLED" >&2
  exit 74
}

git fetch --quiet --force origin "refs/tags/$tag:refs/tags/$tag"
[[ "$(git cat-file -t "refs/tags/$tag")" == tag ]] || {
  echo "PUBLISH_GATE_BLOCKED:ANNOTATED_TAG" >&2
  exit 70
}
[[ "$(git rev-parse "refs/tags/$tag^{}")" == "$expected" ]] || {
  echo "PUBLISH_GATE_BLOCKED:TAG_TARGET" >&2
  exit 70
}

gh release view "$tag" --json tagName,name,isDraft,isPrerelease,body,assets >"$tmp/release.json" || {
  echo "PUBLISH_GATE_BLOCKED:RELEASE_QUERY" >&2
  exit 70
}
python3 - "$tmp/release.json" "$tmp/stage/publish-preview.json" <<'PY' || exit 71
import hashlib, json, sys
release_path, preview_path = sys.argv[1:]
release = json.load(open(release_path, encoding="utf-8"))
preview = json.load(open(preview_path, encoding="utf-8"))
if release.get("tagName") != preview.get("tag_name"):
    raise SystemExit("PUBLISH_GATE_BLOCKED:TAG")
if release.get("name") != preview.get("title"):
    raise SystemExit("PUBLISH_GATE_BLOCKED:TITLE")
if release.get("isDraft") is not True or release.get("isPrerelease") is not preview.get("prerelease"):
    raise SystemExit("PUBLISH_GATE_BLOCKED:STATE")
body = ((release.get("body") or "").rstrip() + "\n").encode("utf-8")
if hashlib.sha256(body).hexdigest() != preview.get("release_notes_sha256"):
    raise SystemExit("PUBLISH_GATE_BLOCKED:BODY")
if {item.get("name") for item in release.get("assets", [])} != set(preview.get("expected_release_assets") or []):
    raise SystemExit("PUBLISH_GATE_BLOCKED:ASSETS")
if preview.get("semantic_validation") != "PASS" or preview.get("manual_draft_repair") != "FORBIDDEN":
    raise SystemExit("PUBLISH_GATE_BLOCKED:PREVIEW")
PY
echo "PUBLISH_ACTION_TIME_PREVIEW_PASS tag=$tag target=$expected"

# Irreversible publication boundary: no build/provider/rewrite work after this point.
gh release edit "$tag" --draft=false

gh api "repos/$repository/releases/tags/$tag" >"$tmp/published.json"
python3 - "$tmp/published.json" "$tag" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
tag = sys.argv[2]
if data.get("tag_name") != tag or data.get("draft") is not False:
    raise SystemExit("PUBLISH_GATE_BLOCKED:POST_PUBLISH_STATE")
if not data.get("published_at"):
    raise SystemExit("PUBLISH_GATE_BLOCKED:POST_PUBLISH_TIMESTAMP")
if data.get("immutable") is not True:
    raise SystemExit("PUBLISH_GATE_BLOCKED:POST_PUBLISH_IMMUTABLE")
PY
echo "RELEASE_PUBLISH_PASS tag=$tag target=$expected"
