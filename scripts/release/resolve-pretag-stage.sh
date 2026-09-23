#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'PRETAG_STAGE_RESOLVE_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

rehearse_run_id=
if [[ $# -eq 5 && ${4:-} == "--rehearse-run-id" && ${5:-} =~ ^[0-9]+$ ]]; then
  rehearse_run_id=$5
elif [[ $# -ne 3 ]]; then
  fail "USAGE" 64
fi
version=$1
expected=$2
destination=$3
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "VERSION"
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || fail "EXPECTED_SHA"

repository="y-sor/clean-room-launcher"
artifact_name="pretag-stage-v${version}-${expected}"
for name in gh python3; do
  command -v "$name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$name"
done
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-pretag-stage-resolve.XXXXXX")
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
  if [[ -n "$rehearse_run_id" && "$run_id" != "$rehearse_run_id" ]]; then
    continue
  fi
  if ! gh api "repos/$repository/actions/runs/$run_id" >"$tmp/run.json"; then
    continue
  fi
  if python3 - "$tmp/run.json" "$expected" "$rehearse_run_id" <<'PY'
import json, sys
path, expected, rehearse_run_id = sys.argv[1:]
run = json.load(open(path, encoding="utf-8"))
required = {
    "name": "Release candidate readiness",
    "event": "push",
    "path": ".github/workflows/release-candidate.yml",
    "head_branch": "main",
    "head_sha": expected,
}
for key, value in required.items():
    if run.get(key) != value:
        raise SystemExit(1)
if rehearse_run_id:
    if str(run.get("id")) != rehearse_run_id:
        raise SystemExit(1)
    if run.get("status") not in {"in_progress", "completed"}:
        raise SystemExit(1)
    if run.get("status") == "completed" and run.get("conclusion") != "success":
        raise SystemExit(1)
else:
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise SystemExit(1)
PY
  then
    selected_run=$run_id
    break
  fi
done <"$tmp/candidates"
if [[ -n "$rehearse_run_id" ]]; then
  [[ -n "$selected_run" ]] || fail "CURRENT_MAIN_STAGE_RUN_NOT_FOUND"
else
  [[ -n "$selected_run" ]] || fail "SUCCESSFUL_MAIN_STAGE_RUN_NOT_FOUND"
fi

mkdir -p "$tmp/download"
gh run download "$selected_run" -R "$repository" -n "$artifact_name" -D "$tmp/download"   || fail "ARTIFACT_DOWNLOAD"

stage_root=$(python3 - "$tmp/download" <<'PY'
import pathlib, sys
root = pathlib.Path(sys.argv[1])
matches = [path.parent for path in root.rglob("pretag-manifest.json") if path.is_file()]
unique = sorted({str(path.resolve()) for path in matches})
if len(unique) != 1:
    raise SystemExit(1)
print(unique[0])
PY
) || fail "MANIFEST_COUNT"

rm -rf -- "$destination"
mkdir -p "$destination"
cp -R "$stage_root"/. "$destination"/

# shellcheck source=provider-pins.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/provider-pins.sh"
python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/verify-pretag-stage.py"   --dir "$destination"   --version "$version"   --source-head "$expected"   --codex-version "$CODEX_VERSION"   --claude-version "$CLAUDE_VERSION"   || fail "VERIFY"

if [[ -n "$rehearse_run_id" ]]; then
  printf 'PRETAG_STAGE_REHEARSAL_RESOLVED run=%s artifact=%s\n' "$selected_run" "$artifact_name"
else
  printf 'PRETAG_STAGE_RESOLVED run=%s artifact=%s\n' "$selected_run" "$artifact_name"
fi