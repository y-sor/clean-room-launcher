#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'ACCEPTED_MAIN_CLAUDE_STAGE_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

usage() {
  echo "usage: bash scripts/release/run-accepted-main-claude-stage.sh --version X.Y.Z" >&2
  echo "       bash scripts/release/run-accepted-main-claude-stage.sh --prepare-only" >&2
  exit 64
}

mode=stage
version=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --version) version=${2:-}; shift 2 ;;
    --prepare-only) mode=prepare; shift ;;
    *) usage ;;
  esac
done
if [[ "$mode" == stage ]]; then
  [[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || usage
else
  [[ -z "$version" ]] || usage
fi

repository="y-sor/clean-room-launcher"
plugin_id="frontend-design@claude-plugins-official"

[[ "$(uname -s)" == "Darwin" ]] || fail "MACOS_REQUIRED"
[[ "$(uname -m)" == "arm64" ]] || fail "APPLE_SILICON_REQUIRED"
for name in git gh python3; do
  command -v "$name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$name"
done
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED"

root=$(git rev-parse --show-toplevel 2>/dev/null) || fail "NOT_IN_GIT_REPOSITORY"
cd "$root"

resolved_repository=$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null)   || fail "REPOSITORY_IDENTITY_UNAVAILABLE"
[[ "$resolved_repository" == "$repository" ]]   || fail "WRONG_REPOSITORY:$resolved_repository"

accepted_before=$(gh api "repos/$repository/git/ref/heads/main" --jq .object.sha)   || fail "MAIN_QUERY_INITIAL"
[[ "$accepted_before" =~ ^[0-9a-f]{40}$ ]] || fail "MAIN_SHA_INITIAL"

git fetch --quiet --tags "https://github.com/$repository.git" main   || fail "CANONICAL_FETCH"
fetched=$(git rev-parse FETCH_HEAD) || fail "FETCH_HEAD"
accepted_after_fetch=$(gh api "repos/$repository/git/ref/heads/main" --jq .object.sha)   || fail "MAIN_QUERY_AFTER_FETCH"
[[ "$accepted_before" == "$accepted_after_fetch" ]]   || fail "MAIN_MOVED_DURING_FETCH:before=$accepted_before:after=$accepted_after_fetch"
[[ "$fetched" == "$accepted_before" ]]   || fail "FETCH_HEAD_MISMATCH:expected=$accepted_before:actual=$fetched"

: "${HOME:?HOME is required}"
worktree_root=${CLROOM_RELEASE_WORKTREE_ROOT:-"$HOME/projects-worktrees/clean-room-launcher"}
stage_root=${CLROOM_RELEASE_STAGE_ROOT:-"$worktree_root/.release-stage"}
worktree="$worktree_root/release-${version:-accepted-main}-${accepted_before:0:12}"

mkdir -p "$worktree_root" "$stage_root"

real_common_dir() {
  python3 - "$1" "$2" <<'PY'
import os, sys
root, raw = sys.argv[1:]
if not os.path.isabs(raw):
    raw = os.path.join(root, raw)
print(os.path.realpath(raw))
PY
}

root_common_raw=$(git rev-parse --git-common-dir) || fail "PRIMARY_COMMON_DIR"
root_common=$(real_common_dir "$root" "$root_common_raw") || fail "PRIMARY_COMMON_DIR_REALPATH"

if [[ -e "$worktree" ]]; then
  [[ -d "$worktree" ]] || fail "WORKTREE_PATH_NOT_DIRECTORY:$worktree"
  worktree_head=$(git -C "$worktree" rev-parse HEAD 2>/dev/null)     || fail "WORKTREE_NOT_GIT:$worktree"
  [[ "$worktree_head" == "$accepted_before" ]]     || fail "WORKTREE_HEAD_MISMATCH:expected=$accepted_before:actual=$worktree_head"
  [[ -z "$(git -C "$worktree" status --porcelain)" ]]     || fail "WORKTREE_NOT_CLEAN:$worktree"
  worktree_common_raw=$(git -C "$worktree" rev-parse --git-common-dir)     || fail "WORKTREE_COMMON_DIR"
  worktree_common=$(real_common_dir "$worktree" "$worktree_common_raw")     || fail "WORKTREE_COMMON_DIR_REALPATH"
  [[ "$worktree_common" == "$root_common" ]]     || fail "WORKTREE_WRONG_REPOSITORY:$worktree"
  echo "ACCEPTED_MAIN_WORKTREE_REUSED source=$accepted_before"
else
  git worktree add --detach "$worktree" "$accepted_before"     || fail "WORKTREE_CREATE:$worktree"
  [[ -z "$(git -C "$worktree" status --porcelain)" ]]     || fail "WORKTREE_NOT_CLEAN_AFTER_CREATE:$worktree"
  echo "ACCEPTED_MAIN_WORKTREE_CREATED source=$accepted_before"
fi

manifest_version=$(python3 - "$worktree/Cargo.toml" <<'PY'
import sys, tomllib
with open(sys.argv[1], "rb") as handle:
    print(tomllib.load(handle)["package"]["version"])
PY
) || fail "MANIFEST_VERSION"
[[ "$manifest_version" == "$version" ]]   || fail "VERSION_MISMATCH:expected=$version:manifest=$manifest_version"

bash "$worktree/scripts/release/resolve-pretag-stage.sh"   "$version" "$accepted_before" "$stage_dir"   || fail "PRETAG_STAGE_RESOLVE"

artifact_name=$(python3 - "$stage_dir/pretag-manifest.json" "$version" "$accepted_before" <<'PY'
import json, sys
path, version, source = sys.argv[1:]
record = json.load(open(path, encoding="utf-8"))
if record.get("release_version") != version:
    raise SystemExit("release-version")
if record.get("source_head") != source:
    raise SystemExit("source-head")
name = record.get("artifact_name")
if not isinstance(name, str) or not name.endswith(".tar.gz"):
    raise SystemExit("artifact-name")
print(name)
PY
) || fail "PRETAG_MANIFEST_BINDING"
artifact="$stage_dir/$artifact_name"
[[ -f "$artifact" ]] || fail "STAGED_ARTIFACT_MISSING:$artifact"
artifact_sha=$(python3 - "$stage_dir/pretag-manifest.json" "$artifact_name" <<'PY'
import json, sys
record = json.load(open(sys.argv[1], encoding="utf-8"))
print(record["files"][sys.argv[2]])
PY
) || fail "ARTIFACT_SHA"

if [[ "$mode" == prepare ]]; then
  accepted_final=$(gh api "repos/$repository/git/ref/heads/main" --jq .object.sha) \
    || fail "MAIN_QUERY_FINAL"
  [[ "$accepted_final" == "$accepted_before" ]] \
    || fail "MAIN_MOVED_AFTER_PREPARE:before=$accepted_before:after=$accepted_final"
  printf 'ACCEPTED_MAIN_CLAUDE_STAGE_PREPARE_PASS version=%s source=%s artifact_sha256=%s\n' \
    "$version" "$accepted_before" "$artifact_sha"
  exit 0
fi

(
  cd "$worktree"
  bash scripts/release/local-plugin-activation-smoke.sh stage     --expected-head "$accepted_before"     --artifact "$artifact"     --plugin-id "$plugin_id"
) || fail "CLAUDE_STAGE_SMOKE"

source "$worktree/scripts/release/provider-pins.sh"
source_tree=$(git -C "$worktree" rev-parse "HEAD^{tree}") || fail "SOURCE_TREE"
reviewed_content_digest=$(python3 - "$worktree/reports/release/v${version}-review.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["reviewed_content_digest"])
PY
) || fail "REVIEW_DIGEST"
claude_provider_sha=$(python3 - "$stage_dir/pretag-manifest.json" <<'PY'
import json, sys
record = json.load(open(sys.argv[1], encoding="utf-8"))
print(record["providers"]["claude"]["executable_sha256"])
PY
) || fail "CLAUDE_PROVIDER_SHA"

evidence_dir="$root_common/clroom-release-evidence"
evidence="$evidence_dir/stage-v${version}-${accepted_before:0:12}.json"
[[ -f "$evidence" ]] || fail "CLAUDE_STAGE_EVIDENCE_MISSING:$evidence"

python3 "$worktree/scripts/release/verify-claude-stage-evidence.py"   --evidence "$evidence"   --version "$version"   --source-head "$accepted_before"   --source-tree "$source_tree"   --reviewed-content-digest "$reviewed_content_digest"   --artifact-sha256 "$artifact_sha"   --claude-version "$CLAUDE_VERSION"   --expected-provider-sha256 "$claude_provider_sha"   || fail "CLAUDE_STAGE_EVIDENCE_VERIFY"

accepted_final=$(gh api "repos/$repository/git/ref/heads/main" --jq .object.sha)   || fail "MAIN_QUERY_FINAL"
[[ "$accepted_final" == "$accepted_before" ]]   || fail "MAIN_MOVED_AFTER_EVIDENCE:before=$accepted_before:after=$accepted_final"

printf 'ACCEPTED_MAIN_CLAUDE_STAGE_PASS version=%s source=%s tree=%s artifact_sha256=%s evidence=%s\n'   "$version" "$accepted_before" "$source_tree" "$artifact_sha" "$evidence"
