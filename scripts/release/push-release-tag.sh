#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: CLROOM_OWNER_TAG_APPROVED=YES:<tag>:<sha> bash scripts/release/push-release-tag.sh <tag> <expected-main-sha>" >&2
  exit 64
}

[[ $# -eq 2 ]] || usage
tag=$1
expected=$2
[[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]] || usage
[[ $expected =~ ^[0-9a-f]{40}$ ]] || usage
[[ ${CLROOM_OWNER_TAG_APPROVED:-} == "YES:$tag:$expected" ]] || {
  echo "TAG_GATE_BLOCKED:OWNER_APPROVAL_TOKEN" >&2
  exit 65
}

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"

for name in git gh python3 shasum; do
  command -v "$name" >/dev/null 2>&1 || {
    echo "TAG_GATE_BLOCKED:COMMAND_MISSING:$name" >&2
    exit 74
  }
done
gh auth status >/dev/null 2>&1 || {
  echo "TAG_GATE_BLOCKED:GH_AUTH_REQUIRED" >&2
  exit 74
}

git diff --quiet
git diff --cached --quiet
git fetch --quiet origin main
actual_main=$(git rev-parse FETCH_HEAD)
[[ $actual_main == "$expected" ]] || {
  echo "TAG_GATE_BLOCKED:MAIN_DRIFT expected=$expected actual=$actual_main" >&2
  exit 66
}
[[ $(git rev-parse HEAD) == "$expected" ]] || {
  echo "TAG_GATE_BLOCKED:LOCAL_HEAD_NOT_ACCEPTED_MAIN" >&2
  exit 67
}

version=${tag#v}
manifest_version=$(python3 - <<'PY'
import tomllib
with open("Cargo.toml", "rb") as handle:
    print(tomllib.load(handle)["package"]["version"])
PY
)
[[ "$manifest_version" == "$version" ]] || {
  echo "TAG_GATE_BLOCKED:VERSION_MISMATCH manifest=$manifest_version tag=$tag" >&2
  exit 67
}

# shellcheck source=provider-pins.sh
source "$root/scripts/release/provider-pins.sh"

ensure_remote_tag_absent() {
  local phase=$1
  local remote_refs
  if ! remote_refs=$(git ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}"); then
    echo "TAG_GATE_BLOCKED:REMOTE_TAG_QUERY_$phase" >&2
    return 1
  fi
  if [[ -n "$remote_refs" ]]; then
    echo "TAG_GATE_BLOCKED:REMOTE_TAG_PRESENT_$phase" >&2
    return 1
  fi
}

ensure_release_absent() {
  local phase=$1
  if gh release view "$tag" >/dev/null 2>&1; then
    echo "TAG_GATE_BLOCKED:RELEASE_PRESENT_$phase" >&2
    return 1
  fi
}

verify_immutable_policy() {
  local phase=$1
  local enabled
  if ! enabled=$(gh api repos/y-sor/clean-room-launcher/immutable-releases --jq .enabled 2>/dev/null); then
    echo "TAG_GATE_BLOCKED:IMMUTABLE_RELEASE_POLICY_UNVERIFIED_$phase" >&2
    return 1
  fi
  if [[ "$enabled" != true ]]; then
    echo "TAG_GATE_BLOCKED:IMMUTABLE_RELEASE_POLICY_DISABLED_$phase" >&2
    return 1
  fi
  printf 'IMMUTABLE_RELEASE_POLICY_PASS phase=%s\n' "$phase"
}

verify_tag_ruleset() {
  local ruleset_tmp
  ruleset_tmp=$(mktemp "${TMPDIR:-/tmp}/clroom-tag-rulesets.XXXXXX") || return 1
  if ! gh api repos/y-sor/clean-room-launcher/rulesets > "$ruleset_tmp"; then
    rm -f -- "$ruleset_tmp"
    echo "TAG_GATE_BLOCKED:RULESET_READ" >&2
    return 1
  fi
  if python3 - "$ruleset_tmp" <<'PY'
import json, subprocess, sys
rulesets = json.load(open(sys.argv[1], encoding="utf-8"))
matches = [
    item for item in rulesets
    if item.get("target") == "tag" and item.get("enforcement") == "active"
]
if not matches:
    raise SystemExit("TAG_GATE_BLOCKED:NO_ACTIVE_TAG_RULESET")
ok = False
for item in matches:
    detail = json.loads(subprocess.check_output(
        ["gh", "api", f"repos/y-sor/clean-room-launcher/rulesets/{item['id']}"],
        text=True,
    ))
    refs = detail.get("conditions", {}).get("ref_name", {}).get("include", [])
    rule_types = {rule.get("type") for rule in detail.get("rules", [])}
    if (
        "refs/tags/v*" in refs
        and {"update", "deletion"} <= rule_types
        and not detail.get("bypass_actors")
        and detail.get("current_user_can_bypass") in (None, "never")
    ):
        ok = True
        break
if not ok:
    raise SystemExit("TAG_GATE_BLOCKED:TAG_RULESET_WEAKENED")
print("TAG_RULESET_PASS")
PY
  then
    rm -f -- "$ruleset_tmp"
    return 0
  fi
  rm -f -- "$ruleset_tmp"
  return 1
}

ensure_remote_tag_absent INITIAL || exit 68
ensure_release_absent INITIAL || exit 68
verify_tag_ruleset || exit 74
verify_immutable_policy INITIAL || exit 74
python3 scripts/release/check-release-contract.py --report >/dev/null || {
  echo "TAG_GATE_BLOCKED:RELEASE_CONTRACT" >&2
  exit 77
}

current_tree=$(git rev-parse "HEAD^{tree}")
review_path="reports/release/v${version}-review.json"
[[ -f "$review_path" ]] || {
  echo "TAG_GATE_BLOCKED:REVIEW_FILE_MISSING" >&2
  exit 75
}
reviewed_content_digest=$(python3 - "$review_path" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["reviewed_content_digest"])
PY
)
[[ "$reviewed_content_digest" =~ ^[0-9a-f]{64}$ ]] || {
  echo "TAG_GATE_BLOCKED:REVIEW_CONTENT_DIGEST" >&2
  exit 75
}

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-tag-stage.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM
GH_TOKEN=${GH_TOKEN:-} bash scripts/release/resolve-pretag-stage.sh   "$version" "$expected" "$tmp/stage" || {
    echo "TAG_GATE_BLOCKED:PRETAG_STAGE" >&2
    exit 80
  }
python3 scripts/release/verify-pretag-stage.py   --dir "$tmp/stage"   --version "$version"   --source-head "$expected"   --source-tree "$current_tree"   --reviewed-content-digest "$reviewed_content_digest"   --codex-version "$CODEX_VERSION"   --claude-version "$CLAUDE_VERSION" || {
    echo "TAG_GATE_BLOCKED:PRETAG_STAGE_BINDING" >&2
    exit 80
  }

artifact_name="clean-room-launcher-v${version}-aarch64-apple-darwin.tar.gz"
artifact_sha=$(python3 - "$tmp/stage/pretag-manifest.json" "$artifact_name" <<'PY'
import json, sys
record = json.load(open(sys.argv[1], encoding="utf-8"))
print(record["files"][sys.argv[2]])
PY
)
[[ "$artifact_sha" =~ ^[0-9a-f]{64}$ ]] || {
  echo "TAG_GATE_BLOCKED:STAGED_ARTIFACT_DIGEST" >&2
  exit 80
}

git_common_dir=$(git rev-parse --git-common-dir)
if [[ "$git_common_dir" != /* ]]; then git_common_dir="$root/$git_common_dir"; fi
evidence_dir=${CLROOM_RELEASE_EVIDENCE_DIR:-"$git_common_dir/clroom-release-evidence"}
claude_stage="$evidence_dir/stage-v${version}-${expected:0:12}.json"
[[ -f "$claude_stage" ]] || {
  echo "TAG_GATE_BLOCKED:CLAUDE_STAGE_EVIDENCE_MISSING:$claude_stage" >&2
  exit 75
}
python3 -   "$claude_stage" "$version" "$expected" "$current_tree"   "$reviewed_content_digest" "$artifact_sha" "$CLAUDE_VERSION" <<'PY'
import json, re, sys
path, version, expected, tree, review_digest, artifact_sha, claude_version = sys.argv[1:]
record = json.load(open(path, encoding="utf-8"))
required = {
    "schema_version": "clroom.plugin-release-smoke.v3",
    "result": "PASS",
    "phase": "stage",
    "release_version": version,
    "source_head": expected,
    "source_tree": tree,
    "reviewed_content_digest": review_digest,
    "artifact_sha256": artifact_sha,
    "platform": "macos-aarch64",
    "claude_version": claude_version,
    "clean_system_init": True,
    "selected_system_init": True,
    "clean_target_plugin": False,
    "selected_target_plugin": True,
    "new_sibling_plugins": 0,
    "selected_plugin_errors": 0,
    "persistent_config_unchanged": True,
    "interactive_selected_tui_confirmed": True,
    "automated_probe_prompt_supplied": True,
    "interactive_no_model_prompt_confirmed": True,
    "external_ancestor_agents_absent_confirmed": True,
    "project_agents_retained_confirmed": True,
    "external_ancestor_agents_sandbox_probe_passed": True,
}
for key, value in required.items():
    if record.get(key) != value:
        raise SystemExit(f"TAG_GATE_BLOCKED:CLAUDE_STAGE_EVIDENCE:{key}")
if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("claude_provider_sha256", ""))):
    raise SystemExit("TAG_GATE_BLOCKED:CLAUDE_STAGE_PROVIDER_SHA")
if not record.get("plugin_id"):
    raise SystemExit("TAG_GATE_BLOCKED:CLAUDE_STAGE_PLUGIN_ID")
print("CLAUDE_STAGE_EVIDENCE_PASS")
PY

title="$tag — Clean Room Launcher"
git tag -a "$tag" "$expected" -m "$title"
cleanup_local_tag() {
  git tag -d "$tag" >/dev/null 2>&1 || true
}
[[ $(git cat-file -t "refs/tags/$tag") == tag ]] || {
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:ANNOTATED_TAG_REQUIRED" >&2
  exit 70
}
[[ $(git rev-parse "$tag^{}") == "$expected" ]] || {
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:TAG_TARGET_MISMATCH" >&2
  exit 71
}
[[ $(git for-each-ref --format='%(contents:subject)' "refs/tags/$tag") == "$title" ]] || {
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:TAG_TITLE_MISMATCH" >&2
  exit 72
}

tag_date=$(python3 - "$tag" <<'PY'
import datetime, re, subprocess, sys
raw = subprocess.check_output(["git", "cat-file", "-p", f"refs/tags/{sys.argv[1]}"], text=True)
line = next((line for line in raw.splitlines() if line.startswith("tagger ")), None)
if line is None:
    raise SystemExit("tagger line missing")
match = re.search(r" (\d+) ([+-])(\d{2})(\d{2})$", line)
if match is None:
    raise SystemExit("tagger timestamp malformed")
minutes = int(match.group(3)) * 60 + int(match.group(4))
if match.group(2) == "-":
    minutes = -minutes
tz = datetime.timezone(datetime.timedelta(minutes=minutes))
print(datetime.datetime.fromtimestamp(int(match.group(1)), tz=tz).date().isoformat())
PY
)
python3 scripts/release/check-release-contract.py --tag-date "$tag_date" --report >/dev/null || {
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:CHANGELOG_DATE_RELATION tag_date=$tag_date" >&2
  exit 69
}

# Final mutable action-time guard. No build/provider/runtime qualification may
# execute after this point; the only irreversible action is the single tag push.
git fetch --quiet origin main || {
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:REMOTE_MAIN_REFRESH_ACTION_TIME" >&2
  exit 76
}
actual_main_now=$(git rev-parse FETCH_HEAD)
[[ $actual_main_now == "$expected" ]] || {
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:MAIN_DRIFT_ACTION_TIME expected=$expected actual=$actual_main_now" >&2
  exit 76
}
[[ $(git rev-parse HEAD) == "$expected" ]] || {
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:LOCAL_HEAD_DRIFT_ACTION_TIME" >&2
  exit 76
}
ensure_remote_tag_absent ACTION_TIME || { cleanup_local_tag; exit 76; }
ensure_release_absent ACTION_TIME || { cleanup_local_tag; exit 76; }
verify_tag_ruleset || { cleanup_local_tag; exit 76; }
verify_immutable_policy ACTION_TIME || { cleanup_local_tag; exit 76; }
python3 scripts/release/check-release-contract.py --tag-date "$tag_date" --report >/dev/null || {
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:RELEASE_CONTRACT_ACTION_TIME" >&2
  exit 77
}

set +e
git push origin "refs/tags/$tag"
push_rc=$?
set -e

set +e
remote_refs=$(git ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}")
reconcile_rc=$?
set -e
if [[ $reconcile_rc -ne 0 ]]; then
  echo "TAG_PUSH_OUTCOME_UNKNOWN:REMOTE_RECONCILIATION_FAILED tag=$tag push_rc=$push_rc" >&2
  exit 82
fi
remote_direct=$(printf '%s\n' "$remote_refs" | awk -v ref="refs/tags/$tag" '$2 == ref {print $1}')
remote_peeled=$(printf '%s\n' "$remote_refs" | awk -v ref="refs/tags/$tag^{}" '$2 == ref {print $1}')
if [[ $remote_peeled == "$expected" ]]; then
  echo "TAG_PUSH_PASS tag=$tag target=$expected"
  exit 0
fi
if [[ -n "$remote_direct" || -n "$remote_peeled" ]]; then
  cleanup_local_tag
  echo "TAG_PUSH_BLOCKED:REMOTE_TARGET_MISMATCH tag=$tag direct=${remote_direct:-none} peeled=${remote_peeled:-none} expected=$expected" >&2
  exit 83
fi
if [[ $push_rc -ne 0 ]]; then
  cleanup_local_tag
  echo "TAG_PUSH_OUTCOME_RECONCILED_ABSENT tag=$tag" >&2
  exit "$push_rc"
fi
echo "TAG_PUSH_OUTCOME_UNKNOWN:REMOTE_TARGET_NOT_RECONCILED tag=$tag" >&2
exit 73
