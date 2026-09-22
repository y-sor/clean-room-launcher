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

# shellcheck source=provider-pins.sh
source "$root/scripts/release/provider-pins.sh"

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

command -v gh >/dev/null 2>&1 || {
  echo "TAG_GATE_BLOCKED:GH_REQUIRED_FOR_RULESET_CHECK" >&2
  exit 74
}

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
    if item.get("target") == "tag"
    and item.get("enforcement") == "active"
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
verify_tag_ruleset || exit 74

python3 scripts/release/check-release-contract.py --report

version=${tag#v}
current_tree=$(git rev-parse "HEAD^{tree}")
reviewed_content_digest=$(python3 - <<'PY'
import json
with open("reports/release/v0.4.2-review.json", encoding="utf-8") as handle:
    print(json.load(handle)["reviewed_content_digest"])
PY
)
[[ "$reviewed_content_digest" =~ ^[0-9a-f]{64}$ ]] || {
  echo "TAG_GATE_BLOCKED:REVIEW_CONTENT_DIGEST" >&2
  exit 75
}
git_common_dir=$(git rev-parse --git-common-dir)
if [[ "$git_common_dir" != /* ]]; then git_common_dir="$PWD/$git_common_dir"; fi
evidence_dir=${CLROOM_RELEASE_EVIDENCE_DIR:-"$git_common_dir/clroom-release-evidence"}
evidence_key=${reviewed_content_digest:0:12}
evidence="$evidence_dir/rehearse-v${version}-${evidence_key}.json"
[[ -f "$evidence" ]] || {
  echo "TAG_GATE_BLOCKED:REHEARSAL_EVIDENCE_MISSING:$evidence" >&2
  exit 75
}
python3 - "$evidence" "$version" "$current_tree" "$reviewed_content_digest" "$CLAUDE_VERSION" <<'PY'
import json, re, sys
path, version, current_tree, reviewed_content_digest, expected_claude_version = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    record = json.load(handle)
required = {
    "schema_version": "clroom.plugin-release-smoke.v3",
    "result": "PASS",
    "phase": "rehearse",
    "release_version": version,
    "source_tree": current_tree,
    "reviewed_content_digest": reviewed_content_digest,
    "evidence_binding": "content-addressed-runtime-v1",
    "platform": "macos-aarch64",
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
        raise SystemExit(f"TAG_GATE_BLOCKED:REHEARSAL_EVIDENCE:{key}")
if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(record.get("source_head", ""))):
    raise SystemExit("TAG_GATE_BLOCKED:REHEARSAL_SOURCE_HEAD")
if not record.get("artifact_sha256") or not record.get("plugin_id"):
    raise SystemExit("TAG_GATE_BLOCKED:REHEARSAL_EVIDENCE_INCOMPLETE")
if not isinstance(record.get("claude_version_output"), str) or not record["claude_version_output"]:
    raise SystemExit("TAG_GATE_BLOCKED:REHEARSAL_CLAUDE_VERSION_MISSING")
if record.get("claude_version") != expected_claude_version:
    raise SystemExit("TAG_GATE_BLOCKED:REHEARSAL_CLAUDE_NOT_CURRENT_STABLE")
if not isinstance(record.get("claude_provider_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", record["claude_provider_sha256"]):
    raise SystemExit("TAG_GATE_BLOCKED:REHEARSAL_CLAUDE_SHA256_MISSING")
print("REHEARSAL_CLAUDE_EVIDENCE_PASS")
PY

codex_evidence="$evidence_dir/codex-rehearse-v${version}-${evidence_key}.json"
if ! bash scripts/release/resolve-codex-rehearsal-evidence.sh \
  "$version" "$current_tree" "$reviewed_content_digest" "$codex_evidence"; then
  echo "TAG_GATE_BLOCKED:CODEX_REHEARSAL_ARTIFACT" >&2
  exit 80
fi
python3 - "$codex_evidence" "$version" "$current_tree" "$reviewed_content_digest" "$CODEX_VERSION" <<'PY'
import json, re, sys
path, version, current_tree, reviewed_content_digest, expected_codex_version = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    record = json.load(handle)
required = {
    "schema_version": "clroom.codex-plugin-release-smoke.v4",
    "result": "PASS",
    "phase": "rehearse",
    "release_version": version,
    "source_tree": current_tree,
    "reviewed_content_digest": reviewed_content_digest,
    "evidence_binding": "content-addressed-runtime-v1",
    "platform": "macos-aarch64",
    "clean_before_expected_mcp": False,
    "selected_expected_mcp": True,
    "selected_mcp_plugin_paths_rebased": True,
    "clean_after_expected_mcp": False,
    "ambient_config_and_plugin_tree_unchanged": True,
    "plugin_source_unchanged": True,
    "real_provider_runtime_confirmed": True,
    "expected_mcp_runtime_healthy_confirmed": True,
    "model_prompt_sent": False,
    "provider_mcp_initialize_observed": True,
    "provider_mcp_tools_list_observed": True,
    "fixture_mcp_tool_call_passed": True,
    "provider_state_lifecycle_closed": True,
    "post_runtime_clean_confirmed": True,
}
for key, value in required.items():
    if record.get(key) != value:
        raise SystemExit(f"TAG_GATE_BLOCKED:CODEX_REHEARSAL_EVIDENCE:{key}")
if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", str(record.get("source_head", ""))):
    raise SystemExit("TAG_GATE_BLOCKED:CODEX_REHEARSAL_SOURCE_HEAD")
if record.get("plugin_id") != "standalone-mcp@clroom-fixture" or record.get("expected_mcp") != "clroom_fixture":
    raise SystemExit("TAG_GATE_BLOCKED:CODEX_REHEARSAL_FIXTURE_IDENTITY")
if not record.get("artifact_sha256"):
    raise SystemExit("TAG_GATE_BLOCKED:CODEX_REHEARSAL_EVIDENCE_INCOMPLETE")
if record.get("codex_version") != expected_codex_version:
    raise SystemExit("TAG_GATE_BLOCKED:CODEX_REHEARSAL_NOT_CURRENT_STABLE")
if not isinstance(record.get("codex_version_output"), str) or not record["codex_version_output"]:
    raise SystemExit("TAG_GATE_BLOCKED:CODEX_REHEARSAL_VERSION_MISSING")
if not isinstance(record.get("codex_provider_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", record["codex_provider_sha256"]):
    raise SystemExit("TAG_GATE_BLOCKED:CODEX_REHEARSAL_SHA256_MISSING")
if not isinstance(record.get("plugin_source_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", record["plugin_source_sha256"]):
    raise SystemExit("TAG_GATE_BLOCKED:CODEX_REHEARSAL_PLUGIN_SOURCE_SHA256_MISSING")
print("REHEARSAL_CODEX_EVIDENCE_PASS")
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
import datetime
import re
import subprocess
import sys

tag = sys.argv[1]
raw = subprocess.check_output(["git", "cat-file", "-p", f"refs/tags/{tag}"], text=True)
line = next((line for line in raw.splitlines() if line.startswith("tagger ")), None)
if line is None:
    raise SystemExit("tagger line missing")
match = re.search(r" (\d+) ([+-])(\d{2})(\d{2})$", line)
if match is None:
    raise SystemExit("tagger timestamp malformed")
epoch = int(match.group(1))
minutes = int(match.group(3)) * 60 + int(match.group(4))
if match.group(2) == "-":
    minutes = -minutes
tz = datetime.timezone(datetime.timedelta(minutes=minutes))
print(datetime.datetime.fromtimestamp(epoch, tz=tz).date().isoformat())
PY
)
if ! python3 scripts/release/check-release-contract.py --tag-date "$tag_date" --report >/dev/null; then
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:CHANGELOG_DATE_RELATION tag_date=$tag_date" >&2
  exit 69
fi

if ! bash scripts/release/check-provider-pins.sh; then
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:PROVIDER_PINS_ACTION_TIME" >&2
  exit 79
fi

evidence_claude_version=$(python3 - "$evidence" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["claude_version_output"])
PY
)
evidence_claude_sha=$(python3 - "$evidence" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["claude_provider_sha256"])
PY
)
if ! claude_executable=$(command -v claude); then
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:CLAUDE_PROVIDER_MISSING_ACTION_TIME" >&2
  exit 78
fi
if ! claude_version_now=$(claude --version 2>&1 | head -1); then
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:CLAUDE_PROVIDER_VERSION_ACTION_TIME" >&2
  exit 78
fi
if ! claude_sha_now=$(shasum -a 256 "$claude_executable" | awk '{print $1}'); then
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:CLAUDE_PROVIDER_HASH_ACTION_TIME" >&2
  exit 78
fi
[[ "$claude_version_now" == "$evidence_claude_version" ]] || {
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:CLAUDE_PROVIDER_DRIFT_ACTION_TIME" >&2
  exit 78
}
[[ "$claude_sha_now" == "$evidence_claude_sha" ]] || {
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:CLAUDE_PROVIDER_BYTES_DRIFT_ACTION_TIME" >&2
  exit 78
}

# Codex rehearsal is reproducible CI evidence from exact registry-pinned packages.
# check-provider-pins.sh above fresh-revalidates both wrapper and darwin-arm64
# package integrity before the final remote guard; no ambient local Codex install
# participates in tag acceptance.

# Final mutable remote release state guard immediately before the irreversible push.
# No provider/network qualification runs after this block; the remaining action is the single push.
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
if ! ensure_remote_tag_absent ACTION_TIME; then
  cleanup_local_tag
  exit 76
fi
if ! verify_tag_ruleset; then
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:TAG_RULESET_ACTION_TIME" >&2
  exit 76
fi
if ! python3 scripts/release/check-release-contract.py --tag-date "$tag_date" --report >/dev/null; then
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:RELEASE_CONTRACT_ACTION_TIME" >&2
  exit 77
fi

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
