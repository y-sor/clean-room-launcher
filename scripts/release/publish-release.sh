#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'PUBLISH_GATE_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

[[ $# -eq 2 ]] || fail "USAGE:publish-release.sh_vX.Y.Z_EXPECTED_SHA" 64
tag=$1
expected=$2
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "STABLE_TAG_REQUIRED" 64
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || fail "EXPECTED_SHA_INVALID" 64

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"
repository="y-sor/clean-room-launcher"
version=${tag#v}

for name in git gh python3 shasum; do
  command -v "$name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$name" 74
done
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED" 74
[[ "$(git rev-parse HEAD)" == "$expected" ]] || fail "LOCAL_HEAD_MISMATCH" 66
[[ -z "$(git status --porcelain)" ]] || fail "WORKTREE_NOT_CLEAN" 66

# Full canonical Draft verification immediately precedes the publication guard.
bash scripts/release/verify-draft-release.sh "$tag" "$expected"   || fail "DRAFT_VERIFICATION" 75

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-publish.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM
bash scripts/release/resolve-pretag-stage.sh "$version" "$expected" "$tmp/stage"   || fail "PRETAG_STAGE" 75

notes="$tmp/stage/release-notes.md"
[[ -f "$notes" ]] || fail "STAGED_RELEASE_NOTES_MISSING" 75
notes_sha=$(shasum -a 256 "$notes" | awk '{print $1}')
[[ "$notes_sha" =~ ^[0-9a-f]{64}$ ]] || fail "STAGED_RELEASE_NOTES_DIGEST" 75

approval=${CLROOM_OWNER_PUBLISH_APPROVED:-}
[[ "$approval" == "YES:$tag:$expected:$notes_sha" ]]   || fail "OWNER_APPROVAL_TOKEN" 65
printf 'PUBLIC_PREVIEW_APPROVAL_BOUND sha256=%s\n' "$notes_sha"

# Action-time state: refresh exact tag, Draft identity/body and immutable policy.
git fetch --quiet --force origin "refs/tags/$tag:refs/tags/$tag"   || fail "TAG_REFRESH_ACTION_TIME" 76
[[ "$(git cat-file -t "refs/tags/$tag")" == tag ]]   || fail "ANNOTATED_TAG_REQUIRED_ACTION_TIME" 76
[[ "$(git rev-parse "refs/tags/$tag^{}")" == "$expected" ]]   || fail "TAG_TARGET_MISMATCH_ACTION_TIME" 76
[[ "$(git for-each-ref --format='%(contents:subject)' "refs/tags/$tag")" == "$tag — Clean Room Launcher" ]]   || fail "TAG_TITLE_MISMATCH_ACTION_TIME" 76

immutable_enabled=$(gh api "repos/$repository/immutable-releases" --jq .enabled 2>/dev/null)   || fail "IMMUTABLE_RELEASE_POLICY_UNVERIFIED_ACTION_TIME" 76
[[ "$immutable_enabled" == true ]] || fail "IMMUTABLE_RELEASE_POLICY_DISABLED_ACTION_TIME" 76

gh release view "$tag"   --json tagName,name,isDraft,isPrerelease,isImmutable,body   >"$tmp/release-before.json" || fail "RELEASE_QUERY_ACTION_TIME" 76

python3 - "$tmp/release-before.json" "$tag" "$notes" <<'PY'   || fail "DRAFT_ACTION_TIME_MISMATCH" 76
import json, pathlib, sys
path, tag, notes_path = sys.argv[1:]
data = json.load(open(path, encoding="utf-8"))
if data.get("tagName") != tag:
    raise SystemExit("tag")
if data.get("name") != f"{tag} — Clean Room Launcher":
    raise SystemExit("name")
if data.get("isDraft") is not True or data.get("isPrerelease") is not False:
    raise SystemExit("state")
if data.get("isImmutable") is not False:
    raise SystemExit("unexpected-prepublish-immutability")
expected = pathlib.Path(notes_path).read_text(encoding="utf-8").rstrip()
if (data.get("body") or "").rstrip() != expected:
    raise SystemExit("body")
PY

# Single irreversible publish call. Reconcile remote state before deciding outcome.
set +e
gh release edit "$tag" --draft=false --verify-tag
publish_rc=$?
set -e

set +e
gh release view "$tag"   --json tagName,name,isDraft,isPrerelease,isImmutable,body,publishedAt   >"$tmp/release-after.json"
query_rc=$?
set -e
if [[ $query_rc -ne 0 ]]; then
  echo "PUBLISH_OUTCOME_UNKNOWN:REMOTE_RECONCILIATION_FAILED tag=$tag publish_rc=$publish_rc" >&2
  exit 82
fi

if python3 - "$tmp/release-after.json" "$tag" "$notes" <<'PY'
import json, pathlib, sys
path, tag, notes_path = sys.argv[1:]
data = json.load(open(path, encoding="utf-8"))
expected = pathlib.Path(notes_path).read_text(encoding="utf-8").rstrip()
ok = (
    data.get("tagName") == tag
    and data.get("name") == f"{tag} — Clean Room Launcher"
    and data.get("isDraft") is False
    and data.get("isPrerelease") is False
    and data.get("isImmutable") is True
    and bool(data.get("publishedAt"))
    and (data.get("body") or "").rstrip() == expected
)
raise SystemExit(0 if ok else 1)
PY
then
  echo "RELEASE_PUBLISH_PASS tag=$tag target=$expected public_preview_sha256=$notes_sha"
  exit 0
fi

if [[ $publish_rc -ne 0 ]]; then
  echo "PUBLISH_OUTCOME_RECONCILED_NOT_PUBLISHED tag=$tag" >&2
  exit "$publish_rc"
fi
echo "PUBLISH_OUTCOME_UNKNOWN:REMOTE_STATE_NOT_ACCEPTED tag=$tag" >&2
exit 83
