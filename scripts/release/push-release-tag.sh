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

if git ls-remote --exit-code --tags origin "refs/tags/$tag" >/dev/null 2>&1; then
  echo "TAG_GATE_BLOCKED:TAG_ALREADY_EXISTS" >&2
  exit 68
fi

command -v gh >/dev/null 2>&1 || {
  echo "TAG_GATE_BLOCKED:GH_REQUIRED_FOR_RULESET_CHECK" >&2
  exit 74
}
gh api repos/y-sor/clean-room-launcher/rulesets > /tmp/clroom-tag-rulesets.json
python3 - /tmp/clroom-tag-rulesets.json <<'PY'
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
rm -f /tmp/clroom-tag-rulesets.json

python3 scripts/release/check-release-contract.py --report

version=${tag#v}
evidence="target/release-evidence/pretag-v${version}-${expected:0:12}.json"
[[ -f "$evidence" ]] || {
  echo "TAG_GATE_BLOCKED:PRETAG_EVIDENCE_MISSING:$evidence" >&2
  exit 75
}
python3 - "$evidence" "$version" "$expected" <<'PY'
import json, sys
path, version, expected = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    record = json.load(handle)
required = {
    "schema_version": "clroom.plugin-release-smoke.v1",
    "result": "PASS",
    "phase": "pretag",
    "release_version": version,
    "source_head": expected,
    "platform": "macos-aarch64",
    "clean_system_init": True,
    "selected_system_init": True,
    "clean_target_plugin": False,
    "selected_target_plugin": True,
    "new_sibling_plugins": 0,
    "selected_plugin_errors": 0,
    "persistent_config_unchanged": True,
    "interactive_selected_tui_confirmed": True,
    "model_prompt_sent": False,
}
for key, value in required.items():
    if record.get(key) != value:
        raise SystemExit(f"TAG_GATE_BLOCKED:PRETAG_EVIDENCE:{key}")
if not record.get("artifact_sha256") or not record.get("plugin_id"):
    raise SystemExit("TAG_GATE_BLOCKED:PRETAG_EVIDENCE_INCOMPLETE")
print("PRETAG_EVIDENCE_PASS")
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
match = re.search(r" (\\d+) ([+-])(\\d{2})(\\d{2})$", line)
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
grep -Fxq "## [$version] - $tag_date" CHANGELOG.md || {
  cleanup_local_tag
  echo "TAG_GATE_BLOCKED:CHANGELOG_DATE expected=$tag_date" >&2
  exit 69
}

set +e
git push origin "refs/tags/$tag"
push_rc=$?
set -e

remote_peeled=$(git ls-remote --tags origin "refs/tags/$tag^{}" | awk '{print $1}')
if [[ $remote_peeled == "$expected" ]]; then
  echo "TAG_PUSH_PASS tag=$tag target=$expected"
  exit 0
fi

if [[ $push_rc -ne 0 ]]; then
  cleanup_local_tag
  echo "TAG_PUSH_OUTCOME_RECONCILED_NOT_PRESENT tag=$tag" >&2
  exit "$push_rc"
fi

echo "TAG_PUSH_BLOCKED:REMOTE_TARGET_NOT_RECONCILED" >&2
exit 73
