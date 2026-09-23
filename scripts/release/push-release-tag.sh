#!/usr/bin/env bash
set -euo pipefail

usage(){ echo "usage: CLROOM_OWNER_TAG_APPROVED=YES:<tag>:<sha> bash scripts/release/push-release-tag.sh <tag> <expected-main-sha>" >&2; exit 64; }
[[ $# -eq 2 ]] || usage
tag=$1
expected=$2
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]] || usage
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || usage
[[ ${CLROOM_OWNER_TAG_APPROVED:-} == "YES:$tag:$expected" ]] || { echo "TAG_GATE_BLOCKED:OWNER_APPROVAL_TOKEN" >&2; exit 65; }

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"
git diff --quiet
git diff --cached --quiet
[[ "$(git rev-parse HEAD)" == "$expected" ]] || { echo "TAG_GATE_BLOCKED:LOCAL_HEAD_NOT_ACCEPTED_MAIN" >&2; exit 67; }
command -v gh >/dev/null 2>&1 || { echo "TAG_GATE_BLOCKED:GH_REQUIRED" >&2; exit 74; }
gh auth status >/dev/null 2>&1 || { echo "TAG_GATE_BLOCKED:GH_AUTH_REQUIRED" >&2; exit 74; }

version=${tag#v}
manifest_version=$(python3 - <<'PY'
import tomllib
print(tomllib.load(open("Cargo.toml","rb"))["package"]["version"])
PY
)
[[ "$manifest_version" == "$version" ]] || { echo "TAG_GATE_BLOCKED:VERSION_MISMATCH" >&2; exit 69; }

ensure_remote_tag_absent(){
  local phase=$1 refs
  refs=$(git ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}") || { echo "TAG_GATE_BLOCKED:REMOTE_TAG_QUERY_$phase" >&2; return 1; }
  [[ -z "$refs" ]] || { echo "TAG_GATE_BLOCKED:REMOTE_TAG_PRESENT_$phase" >&2; return 1; }
}
ensure_release_absent(){
  local phase=$1
  if gh release view "$tag" >/dev/null 2>&1; then
    echo "TAG_GATE_BLOCKED:REMOTE_RELEASE_PRESENT_$phase" >&2
    return 1
  fi
}
verify_immutable_release_policy(){
  local phase=$1 enabled
  enabled=$(gh api repos/y-sor/clean-room-launcher/immutable-releases --jq .enabled 2>/dev/null) || {
    echo "TAG_GATE_BLOCKED:IMMUTABLE_RELEASE_POLICY_UNVERIFIED_$phase" >&2; return 1;
  }
  [[ "$enabled" == true ]] || { echo "TAG_GATE_BLOCKED:IMMUTABLE_RELEASE_POLICY_DISABLED_$phase" >&2; return 1; }
}
verify_tag_ruleset(){
  local tmp
  tmp=$(mktemp "${TMPDIR:-/tmp}/clroom-tag-rulesets.XXXXXX")
  gh api repos/y-sor/clean-room-launcher/rulesets >"$tmp" || { rm -f "$tmp"; echo "TAG_GATE_BLOCKED:RULESET_READ" >&2; return 1; }
  python3 - "$tmp" <<'PY'
import json,subprocess,sys
items=json.load(open(sys.argv[1],encoding="utf-8"))
for item in items:
    if item.get("target")!="tag" or item.get("enforcement")!="active": continue
    d=json.loads(subprocess.check_output(["gh","api",f"repos/y-sor/clean-room-launcher/rulesets/{item['id']}"],text=True))
    refs=d.get("conditions",{}).get("ref_name",{}).get("include",[])
    types={x.get("type") for x in d.get("rules",[])}
    if "refs/tags/v*" in refs and {"update","deletion"} <= types and not d.get("bypass_actors") and d.get("current_user_can_bypass") in (None,"never"):
        print("TAG_RULESET_PASS"); raise SystemExit(0)
raise SystemExit("TAG_GATE_BLOCKED:TAG_RULESET_WEAKENED")
PY
  rc=$?
  rm -f "$tmp"
  return $rc
}

git fetch --quiet origin main
[[ "$(git rev-parse FETCH_HEAD)" == "$expected" ]] || { echo "TAG_GATE_BLOCKED:MAIN_DRIFT" >&2; exit 66; }
ensure_remote_tag_absent INITIAL || exit 68
ensure_release_absent INITIAL || exit 68
verify_tag_ruleset || exit 74
verify_immutable_release_policy INITIAL || exit 74
python3 scripts/release/check-release-contract.py --report

stage_dir=$(mktemp -d "${TMPDIR:-/tmp}/clroom-pretag-stage.XXXXXX")
trap 'rm -rf -- "$stage_dir"' EXIT HUP INT TERM
bash scripts/release/resolve-release-stage.sh "$version" "$expected" "$stage_dir" || exit 80
current_tree=$(git rev-parse 'HEAD^{tree}')
stage_manifest="$stage_dir/release-stage.json"
read -r stage_tree review_digest artifact_name artifact_sha codex_version claude_version < <(
python3 - "$stage_manifest" <<'PY'
import json,sys
r=json.load(open(sys.argv[1],encoding="utf-8"))
a=r["artifact_name"]
print(r["source_tree"],r["reviewed_content_digest"],a,r["files"][a],r["providers"]["codex"]["version"],r["providers"]["claude"]["version"])
PY
)
[[ "$stage_tree" == "$current_tree" ]] || { echo "TAG_GATE_BLOCKED:STAGE_TREE" >&2; exit 80; }

codex_stage="$stage_dir/codex-stage-v${version}-${expected:0:12}.json"
python3 - "$codex_stage" "$version" "$expected" "$current_tree" "$review_digest" "$artifact_sha" "$codex_version" <<'PY'
import json,re,sys
path,version,head,tree,digest,artifact_sha,provider_version=sys.argv[1:]
r=json.load(open(path,encoding="utf-8"))
required={"schema_version":"clroom.codex-plugin-release-smoke.v4","result":"PASS","phase":"stage","release_version":version,"source_head":head,"source_tree":tree,"reviewed_content_digest":digest,"evidence_binding":"content-addressed-runtime-v1","artifact_sha256":artifact_sha,"platform":"macos-aarch64","codex_version":provider_version,"plugin_id":"standalone-mcp@clroom-fixture","expected_mcp":"clroom_fixture","real_provider_runtime_confirmed":True,"expected_mcp_runtime_healthy_confirmed":True,"provider_mcp_initialize_observed":True,"provider_mcp_tools_list_observed":True,"fixture_mcp_tool_call_passed":True,"provider_state_lifecycle_closed":True,"post_runtime_clean_confirmed":True,"model_prompt_sent":False}
for k,v in required.items():
    if r.get(k)!=v: raise SystemExit(f"TAG_GATE_BLOCKED:CODEX_STAGE:{k}")
PY

git_common_dir=$(git rev-parse --git-common-dir)
[[ "$git_common_dir" == /* ]] || git_common_dir="$PWD/$git_common_dir"
evidence_dir=${CLROOM_RELEASE_EVIDENCE_DIR:-"$git_common_dir/clroom-release-evidence"}
claude_stage="$evidence_dir/stage-v${version}-${expected:0:12}.json"
[[ -f "$claude_stage" ]] || { echo "TAG_GATE_BLOCKED:CLAUDE_STAGE_EVIDENCE_MISSING:$claude_stage" >&2; exit 75; }
python3 - "$claude_stage" "$version" "$expected" "$current_tree" "$review_digest" "$artifact_sha" "$claude_version" <<'PY'
import json,sys
path,version,head,tree,digest,artifact_sha,provider_version=sys.argv[1:]
r=json.load(open(path,encoding="utf-8"))
required={"schema_version":"clroom.plugin-release-smoke.v3","result":"PASS","phase":"stage","release_version":version,"source_head":head,"source_tree":tree,"reviewed_content_digest":digest,"evidence_binding":"content-addressed-runtime-v1","artifact_sha256":artifact_sha,"platform":"macos-aarch64","claude_version":provider_version,"clean_system_init":True,"selected_system_init":True,"clean_target_plugin":False,"selected_target_plugin":True,"new_sibling_plugins":0,"selected_plugin_errors":0,"persistent_config_unchanged":True,"interactive_selected_tui_confirmed":True,"automated_probe_prompt_supplied":True,"interactive_no_model_prompt_confirmed":True,"external_ancestor_agents_absent_confirmed":True,"project_agents_retained_confirmed":True,"external_ancestor_agents_sandbox_probe_passed":True}
for k,v in required.items():
    if r.get(k)!=v: raise SystemExit(f"TAG_GATE_BLOCKED:CLAUDE_STAGE:{k}")
PY

title="$tag — Clean Room Launcher"
git tag -a "$tag" "$expected" -m "$title"
cleanup_local_tag(){ git tag -d "$tag" >/dev/null 2>&1 || true; }
[[ "$(git cat-file -t "refs/tags/$tag")" == tag ]] || { cleanup_local_tag; exit 70; }
[[ "$(git rev-parse "$tag^{}")" == "$expected" ]] || { cleanup_local_tag; exit 71; }
[[ "$(git for-each-ref --format='%(contents:subject)' "refs/tags/$tag")" == "$title" ]] || { cleanup_local_tag; exit 72; }

tag_date=$(python3 - "$tag" <<'PY'
import datetime,re,subprocess,sys
raw=subprocess.check_output(["git","cat-file","-p",f"refs/tags/{sys.argv[1]}"],text=True)
line=next(x for x in raw.splitlines() if x.startswith("tagger "))
m=re.search(r" (\d+) ([+-])(\d{2})(\d{2})$",line)
if not m: raise SystemExit(1)
minutes=int(m.group(3))*60+int(m.group(4))
if m.group(2)=="-": minutes=-minutes
tz=datetime.timezone(datetime.timedelta(minutes=minutes))
print(datetime.datetime.fromtimestamp(int(m.group(1)),tz=tz).date().isoformat())
PY
)
python3 scripts/release/check-release-contract.py --tag-date "$tag_date" --report >/dev/null || { cleanup_local_tag; echo "TAG_GATE_BLOCKED:CHANGELOG_DATE_RELATION" >&2; exit 69; }

mkdir -p "$evidence_dir"
closure="$evidence_dir/pretag-closure-v${version}-${expected:0:12}.json"
python3 - "$closure" "$stage_manifest" "$claude_stage" "$tag" "$expected" <<'PY'
import hashlib,json,sys
out,stage,claude,tag,head=sys.argv[1:]
def h(p):
    x=hashlib.sha256()
    with open(p,"rb") as f:
        for c in iter(lambda:f.read(1024*1024),b""): x.update(c)
    return x.hexdigest()
r={"schema_version":"clroom.pretag-closure.v1","result":"PASS","tag":tag,"source_head":head,"stage_manifest_sha256":h(stage),"claude_stage_evidence_sha256":h(claude),"immutable_release_policy":True,"tag_ruleset_no_update_delete_bypass":True,"post_tag_blocker_policy":"promotion-only"}
open(out,"w",encoding="utf-8").write(json.dumps(r,sort_keys=True,indent=2)+"\n")
PY

# Final mutable remote guard. No build/provider/runtime/latest-registry work is allowed after this point.
git fetch --quiet origin main || { cleanup_local_tag; exit 76; }
[[ "$(git rev-parse FETCH_HEAD)" == "$expected" ]] || { cleanup_local_tag; echo "TAG_GATE_BLOCKED:MAIN_DRIFT_ACTION_TIME" >&2; exit 76; }
ensure_remote_tag_absent ACTION_TIME || { cleanup_local_tag; exit 76; }
ensure_release_absent ACTION_TIME || { cleanup_local_tag; exit 76; }
verify_tag_ruleset || { cleanup_local_tag; exit 76; }
verify_immutable_release_policy ACTION_TIME || { cleanup_local_tag; exit 76; }
python3 scripts/release/check-release-contract.py --tag-date "$tag_date" --report >/dev/null || { cleanup_local_tag; exit 77; }

set +e
git push origin "refs/tags/$tag"
push_rc=$?
set -e
set +e
remote_refs=$(git ls-remote --tags origin "refs/tags/$tag" "refs/tags/$tag^{}")
reconcile_rc=$?
set -e
[[ $reconcile_rc -eq 0 ]] || { echo "TAG_PUSH_OUTCOME_UNKNOWN:REMOTE_RECONCILIATION_FAILED tag=$tag push_rc=$push_rc" >&2; exit 82; }
remote_direct=$(printf '%s\n' "$remote_refs" | awk -v ref="refs/tags/$tag" '$2==ref {print $1}')
remote_peeled=$(printf '%s\n' "$remote_refs" | awk -v ref="refs/tags/$tag^{}" '$2==ref {print $1}')
if [[ "$remote_peeled" == "$expected" ]]; then echo "TAG_PUSH_PASS tag=$tag target=$expected"; exit 0; fi
if [[ -n "$remote_direct" || -n "$remote_peeled" ]]; then cleanup_local_tag; echo "TAG_PUSH_BLOCKED:REMOTE_TARGET_MISMATCH" >&2; exit 83; fi
if [[ $push_rc -ne 0 ]]; then cleanup_local_tag; echo "TAG_PUSH_OUTCOME_RECONCILED_ABSENT tag=$tag" >&2; exit "$push_rc"; fi
echo "TAG_PUSH_OUTCOME_UNKNOWN:REMOTE_TARGET_NOT_RECONCILED tag=$tag" >&2
exit 73
