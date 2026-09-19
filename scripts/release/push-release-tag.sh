#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 vX.Y.Z EXPECTED_MAIN_SHA" >&2
  exit 2
}

fail() {
  printf 'RELEASE_TAG_PUSH_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

[[ $# -eq 2 ]] || usage
tag=$1
expected_main=$2
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "STABLE_TAG_REQUIRED"
[[ "$expected_main" =~ ^[0-9a-f]{40}$ ]] || fail "EXPECTED_MAIN_SHA"

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"

for command_name in git gh python3; do
  command -v "$command_name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$command_name"
done
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED"
[[ -z "$(git status --porcelain)" ]] || fail "WORKTREE_NOT_CLEAN"

git remote get-url origin >/dev/null 2>&1 || fail "ORIGIN_MISSING"
git fetch --quiet --no-tags origin main
local_head=$(git rev-parse HEAD)
remote_main=$(git rev-parse FETCH_HEAD)
[[ "$local_head" == "$expected_main" ]] || {
  printf 'LOCAL_HEAD=%s EXPECTED=%s\n' "$local_head" "$expected_main" >&2
  fail "LOCAL_HEAD_MOVED"
}
[[ "$remote_main" == "$expected_main" ]] || {
  printf 'REMOTE_MAIN=%s EXPECTED=%s\n' "$remote_main" "$expected_main" >&2
  fail "REMOTE_MAIN_MOVED"
}

python3 scripts/release/check-repository-release-policy.py --mode strict >/dev/null || fail "REPOSITORY_TAG_POLICY"

read -r codex_pin claude_plugin_pin < <(
  python3 - <<'PY'
import json
from pathlib import Path
data = json.loads(Path("release/qualification.json").read_text(encoding="utf-8"))
print(
    data["providers"]["codex"]["clean_exact"],
    data["providers"]["claude"]["plugin_activation_exact"],
)
PY
)
for command_name in codex claude; do
  command -v "$command_name" >/dev/null 2>&1 || fail "PROVIDER_COMMAND_MISSING:$command_name"
done
version_from_output() {
  "$1" --version 2>&1 | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1
}
current_codex=$(version_from_output "$(command -v codex)")
current_claude=$(version_from_output "$(command -v claude)")
[[ "$current_codex" == "$codex_pin" ]] || {
  printf 'PROVIDER_REFRESH_REQUIRED provider=codex installed=%s release_pin=%s\n' "$current_codex" "$codex_pin" >&2
  fail "CODEX_PROVIDER_DRIFT"
}
[[ "$current_claude" == "$claude_plugin_pin" ]] || {
  printf 'PROVIDER_REFRESH_REQUIRED provider=claude capability=plugin_activation installed=%s release_pin=%s\n' "$current_claude" "$claude_plugin_pin" >&2
  fail "CLAUDE_PLUGIN_PROVIDER_DRIFT"
}

if git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1; then
  fail "REMOTE_TAG_ALREADY_EXISTS"
fi
version=${tag#v}
manifest_version=$(python3 - <<'PY'
import tomllib
with open("Cargo.toml", "rb") as handle:
    print(tomllib.load(handle)["package"]["version"])
PY
)
[[ "$manifest_version" == "$version" ]] || fail "PACKAGE_VERSION_MISMATCH"

title="$tag — Clean Room Launcher"
if git show-ref --verify --quiet "refs/tags/$tag"; then
  [[ "$(git cat-file -t "refs/tags/$tag")" == tag ]] || fail "LOCAL_TAG_NOT_ANNOTATED"
  [[ "$(git rev-list -n1 "$tag")" == "$expected_main" ]] || fail "LOCAL_TAG_TARGET_MISMATCH"
  release_date=$(git for-each-ref --format='%(taggerdate:short)' "refs/tags/$tag")
  [[ -n "$release_date" ]] || fail "LOCAL_TAG_DATE_MISSING"
  [[ "$(git for-each-ref --format='%(subject)' "refs/tags/$tag")" == "$title" ]] || fail "LOCAL_TAG_MESSAGE_MISMATCH"
else
  utc_now=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
  release_date=${utc_now%%T*}
  grep -Fqx "## [$version] - $release_date" CHANGELOG.md || fail "CHANGELOG_UTC_DATE_MISMATCH"
  GIT_COMMITTER_DATE="$utc_now" git tag -a "$tag" "$expected_main" -m "$title" || fail "ANNOTATED_TAG_CREATE"
fi

grep -Fqx "## [$version] - $release_date" CHANGELOG.md || fail "CHANGELOG_TAG_DATE_MISMATCH"

short_head=${expected_main:0:12}
evidence="target/release-evidence/pretag-v${version}-${short_head}.json"
[[ -f "$evidence" ]] || fail "PRETAG_SMOKE_EVIDENCE_MISSING"
python3 - "$evidence" "$version" "$expected_main" <<'PY' || fail "PRETAG_SMOKE_EVIDENCE_INVALID"
import json
import sys
from pathlib import Path

path, version, expected_head = sys.argv[1:]
record = json.loads(Path(path).read_text(encoding="utf-8"))
if record.get("schema_version") != "clroom.local-release-smoke.v1":
    raise SystemExit("schema")
if record.get("result") != "PASS" or record.get("phase") != "pretag":
    raise SystemExit("result-phase")
if record.get("release_version") != version or record.get("source_head") != expected_head:
    raise SystemExit("identity")
if not isinstance(record.get("artifact_sha256"), str) or len(record["artifact_sha256"]) != 64:
    raise SystemExit("artifact")
auto = record.get("automated") or {}
human = record.get("human") or {}
for key in (
    "clean_init_only",
    "selected_init_only",
    "plugin_inventory_qualified",
    "persistent_config_unchanged",
):
    if auto.get(key) is not True:
        raise SystemExit("automated:" + key)
for key in (
    "codex_tui_confirmed",
    "claude_clean_tui_confirmed",
    "claude_clean_selected_skill_absent_confirmed",
    "claude_selected_plugin_tui_confirmed",
    "claude_selected_skill_visible_confirmed",
):
    if human.get(key) is not True:
        raise SystemExit("human:" + key)
if auto.get("model_prompt_sent") is not False or human.get("model_prompt_sent") is not False:
    raise SystemExit("model-prompt")
PY

[[ "$(git cat-file -t "refs/tags/$tag")" == tag ]] || fail "ANNOTATED_TAG_TYPE"
[[ "$(git rev-list -n1 "$tag")" == "$expected_main" ]] || fail "TAG_TARGET"
[[ "$(git for-each-ref --format='%(taggerdate:short)' "refs/tags/$tag")" == "$release_date" ]] || fail "TAG_DATE"
[[ "$(git for-each-ref --format='%(subject)' "refs/tags/$tag")" == "$title" ]] || fail "TAG_MESSAGE"

# Action-time refresh. Everything above may take long enough for mutable remote
# or provider state to drift. Revalidate immediately before the irreversible push.
git fetch --quiet --no-tags origin main
remote_main_now=$(git rev-parse FETCH_HEAD)
[[ "$remote_main_now" == "$expected_main" ]] || {
  printf 'REMOTE_MAIN_NOW=%s EXPECTED=%s\n' "$remote_main_now" "$expected_main" >&2
  fail "REMOTE_MAIN_MOVED_ACTION_TIME"
}
python3 scripts/release/check-repository-release-policy.py --mode strict >/dev/null \
  || fail "REPOSITORY_TAG_POLICY_ACTION_TIME"
if git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1; then
  fail "REMOTE_TAG_APPEARED_ACTION_TIME"
fi

read -r evidence_codex_sha evidence_claude_sha < <(
  python3 - "$evidence" <<'PY'
import json
import sys
from pathlib import Path
record = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
hashes = record.get("provider_sha256") or {}
print(hashes.get("codex", ""), hashes.get("claude", ""))
PY
)
[[ "$evidence_codex_sha" =~ ^[0-9a-f]{64}$ ]] || fail "PRETAG_CODEX_HASH_MISSING"
[[ "$evidence_claude_sha" =~ ^[0-9a-f]{64}$ ]] || fail "PRETAG_CLAUDE_HASH_MISSING"

codex_executable_now=$(command -v codex)
claude_executable_now=$(command -v claude)
codex_version_now=$(version_from_output "$codex_executable_now")
claude_version_now=$(version_from_output "$claude_executable_now")
[[ "$codex_version_now" == "$codex_pin" ]] || fail "CODEX_PROVIDER_DRIFT_ACTION_TIME"
[[ "$claude_version_now" == "$claude_plugin_pin" ]] || fail "CLAUDE_PLUGIN_PROVIDER_DRIFT_ACTION_TIME"
codex_sha_now=$(shasum -a 256 "$codex_executable_now" | awk '{print $1}')
claude_sha_now=$(shasum -a 256 "$claude_executable_now" | awk '{print $1}')
[[ "$codex_sha_now" == "$evidence_codex_sha" ]] || fail "CODEX_PROVIDER_BYTES_DRIFT_ACTION_TIME"
[[ "$claude_sha_now" == "$evidence_claude_sha" ]] || fail "CLAUDE_PROVIDER_BYTES_DRIFT_ACTION_TIME"

# The protected remote v* tag is created only after every local invariant above passes.
# A transport failure after the server accepts the ref is an ambiguous outcome:
# never push again until the remote ref is reconciled.
local_object=$(git rev-parse "refs/tags/$tag")
set +e
git push origin "refs/tags/$tag:refs/tags/$tag"
push_rc=$?
set -e

remote_refs=$(git ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}" 2>/dev/null || true)
remote_object=$(printf '%s\n' "$remote_refs" | awk -v ref="refs/tags/$tag" '$2 == ref {print $1}')
remote_target=$(printf '%s\n' "$remote_refs" | awk -v ref="refs/tags/$tag^{}" '$2 == ref {print $1}')

if [[ -n "$remote_object" ]]; then
  [[ "$remote_object" == "$local_object" ]] || {
    printf 'REMOTE_TAG_OBJECT=%s LOCAL_TAG_OBJECT=%s\n' "$remote_object" "$local_object" >&2
    fail "REMOTE_TAG_OBJECT_MISMATCH"
  }
  [[ "$remote_target" == "$expected_main" ]] || {
    printf 'REMOTE_TAG_TARGET=%s EXPECTED=%s\n' "$remote_target" "$expected_main" >&2
    fail "REMOTE_TAG_TARGET_MISMATCH"
  }
  if [[ "$push_rc" -ne 0 ]]; then
    printf 'RELEASE_TAG_PUSH_RECONCILED tag=%s target=%s remote_tag_object=%s\n' \
      "$tag" "$expected_main" "$remote_object"
  else
    printf 'RELEASE_TAG_PUSH_PASS tag=%s target=%s remote_tag_object=%s\n' \
      "$tag" "$expected_main" "$remote_object"
  fi
  exit 0
fi

if [[ "$push_rc" -ne 0 ]]; then
  fail "TAG_PUSH_NOT_DELIVERED"
fi
fail "TAG_PUSH_OUTCOME_UNKNOWN"
