#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'RELEASE_STAGE_RESOLVE_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

[[ $# -eq 3 ]] || fail "USAGE" 64
version=$1
expected=$2
destination=$3
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "VERSION"
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || fail "EXPECTED_SHA"

repository="y-sor/clean-room-launcher"
artifact_name="release-stage-v${version}-${expected}"
command -v gh >/dev/null 2>&1 || fail "GH_REQUIRED"
command -v python3 >/dev/null 2>&1 || fail "PYTHON_REQUIRED"
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-release-stage-resolve.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

gh api -X GET "repos/$repository/actions/artifacts"   -f name="$artifact_name" -f per_page=100 >"$tmp/artifacts.json"   || fail "ARTIFACT_QUERY"

python3 - "$tmp/artifacts.json" "$artifact_name" >"$tmp/candidates" <<'PY'
import json, sys
path, expected = sys.argv[1:]
data = json.load(open(path, encoding="utf-8"))
items = [
    item for item in data.get("artifacts", [])
    if item.get("name") == expected
    and item.get("expired") is False
    and isinstance((item.get("workflow_run") or {}).get("id"), int)
]
items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
for item in items:
    run = item["workflow_run"]
    print(item["id"], run["id"], run.get("head_sha") or "")
PY

[[ -s "$tmp/candidates" ]] || fail "ARTIFACT_NOT_FOUND"

selected_run=
while read -r artifact_id run_id artifact_head; do
  [[ -n "$artifact_id" && -n "$run_id" ]] || continue
  [[ "$artifact_head" == "$expected" ]] || continue
  if ! gh api "repos/$repository/actions/runs/$run_id" >"$tmp/run.json"; then
    continue
  fi
  if python3 - "$tmp/run.json" "$expected" <<'PY'
import json, sys
path, expected = sys.argv[1:]
run = json.load(open(path, encoding="utf-8"))
required = {
    "name": "Release candidate readiness",
    "event": "push",
    "status": "completed",
    "conclusion": "success",
    "path": ".github/workflows/release-candidate.yml",
    "head_branch": "main",
    "head_sha": expected,
}
for key, value in required.items():
    if run.get(key) != value:
        raise SystemExit(1)
PY
  then
    selected_run=$run_id
    break
  fi
done <"$tmp/candidates"

[[ -n "$selected_run" ]] || fail "SUCCESSFUL_ACCEPTED_MAIN_RUN_NOT_FOUND"

rm -rf -- "$destination"
mkdir -p "$destination"
gh run download "$selected_run" -R "$repository" -n "$artifact_name" -D "$destination"   || fail "ARTIFACT_DOWNLOAD"

[[ -s "$destination/stage-manifest.json" ]] || fail "MANIFEST_MISSING"
printf 'RELEASE_STAGE_RESOLVED run=%s artifact=%s\n' "$selected_run" "$artifact_name"
