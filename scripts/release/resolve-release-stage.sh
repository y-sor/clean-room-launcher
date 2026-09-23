#!/usr/bin/env bash
set -euo pipefail
fail(){ printf 'RELEASE_STAGE_RESOLVE_BLOCKED:%s\n' "$1" >&2; exit "${2:-1}"; }
[[ $# -eq 3 ]] || fail USAGE 64
version=$1
expected=$2
destination=$3
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail VERSION
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || fail EXPECTED_SHA
repository="y-sor/clean-room-launcher"
command -v gh >/dev/null 2>&1 || fail GH_REQUIRED
command -v python3 >/dev/null 2>&1 || fail PYTHON_REQUIRED
gh auth status >/dev/null 2>&1 || fail GH_AUTH_REQUIRED
artifact_name="release-stage-v${version}-${expected}"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-release-stage.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM
gh api -X GET "repos/$repository/actions/artifacts" -f name="$artifact_name" -f per_page=100 >"$tmp/artifacts.json" || fail ARTIFACT_QUERY
python3 - "$tmp/artifacts.json" "$artifact_name" >"$tmp/candidates" <<'PY'
import json,sys
data=json.load(open(sys.argv[1],encoding="utf-8")); expected=sys.argv[2]
items=[x for x in data.get("artifacts",[]) if x.get("name")==expected and x.get("expired") is False and isinstance((x.get("workflow_run") or {}).get("id"),int)]
items.sort(key=lambda x:x.get("created_at") or "", reverse=True)
for x in items:
    r=x["workflow_run"]; print(x["id"],r["id"],r.get("head_sha") or "")
PY
[[ -s "$tmp/candidates" ]] || fail ARTIFACT_NOT_FOUND
selected=
while read -r artifact_id run_id artifact_head; do
  [[ "$artifact_head" == "$expected" ]] || continue
  gh api "repos/$repository/actions/runs/$run_id" >"$tmp/run.json" 2>/dev/null || continue
  if python3 - "$tmp/run.json" "$expected" <<'PY'
import json,sys
r=json.load(open(sys.argv[1],encoding="utf-8")); expected=sys.argv[2]
required={"name":"Release candidate readiness","event":"push","status":"completed","conclusion":"success","path":".github/workflows/release-candidate.yml","head_branch":"main","head_sha":expected}
for k,v in required.items():
    if r.get(k)!=v: raise SystemExit(1)
PY
  then selected=$run_id; break; fi
done <"$tmp/candidates"
[[ -n "$selected" ]] || fail SUCCESSFUL_MAIN_STAGE_RUN_NOT_FOUND
rm -rf "$destination"; mkdir -p "$destination"
gh run download "$selected" -R "$repository" -n "$artifact_name" -D "$destination" || fail ARTIFACT_DOWNLOAD
python3 scripts/release/stage-manifest.py verify --root "$destination" --version "$version" --source-head "$expected" || fail MANIFEST
printf 'RELEASE_STAGE_RESOLVED run=%s artifact=%s destination=%s\n' "$selected" "$artifact_name" "$destination"
