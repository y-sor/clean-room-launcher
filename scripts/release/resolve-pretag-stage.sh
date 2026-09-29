#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'PRETAG_STAGE_RESOLVE_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

[[ $# -eq 3 ]] || fail "USAGE" 64
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
successful_runs="$tmp/successful-runs"
: >"$successful_runs"

current_run_id="${CLROOM_PRETAG_CURRENT_RUN_ID:-}"
if [[ -n "$current_run_id" ]]; then
  [[ "$current_run_id" =~ ^[0-9]+$ ]] || fail "CURRENT_RUN_ID"
  [[ "${GITHUB_ACTIONS:-}" == "true" ]] || fail "CURRENT_RUN_NOT_ACTIONS"
  [[ "${GITHUB_RUN_ID:-}" == "$current_run_id" ]] || fail "CURRENT_RUN_ID_MISMATCH"
  [[ "${GITHUB_EVENT_NAME:-}" == "push" ]] || fail "CURRENT_RUN_EVENT"
  [[ "${GITHUB_REF:-}" == "refs/heads/main" ]] || fail "CURRENT_RUN_REF"
  [[ "${GITHUB_SHA:-}" == "$expected" ]] || fail "CURRENT_RUN_SHA"
  [[ "${GITHUB_REPOSITORY:-}" == "$repository" ]] || fail "CURRENT_RUN_REPOSITORY"
fi

while read -r artifact_id run_id artifact_head; do
  [[ -n "$artifact_id" && -n "$run_id" ]] || continue
  [[ "$artifact_head" == "$expected" ]] || continue
  if ! gh api "repos/$repository/actions/runs/$run_id" >"$tmp/run-$run_id.json"; then
    continue
  fi

  run_args=(
    python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/pretag-run-admission.py"
    --run-json "$tmp/run-$run_id.json"
    --expected-sha "$expected"
    --repository "$repository"
  )
  if [[ -n "$current_run_id" ]]; then
    run_args+=(--current-run-id "$current_run_id")
  fi
  run_mode=$("${run_args[@]}") || continue

  if [[ "$run_mode" == "current" ]]; then
    gh api -X GET "repos/$repository/actions/runs/$run_id/jobs" -f per_page=100 >"$tmp/jobs-$run_id.json" \
      || fail "CURRENT_RUN_JOBS:$run_id"
    python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/pretag-run-admission.py" \
      --jobs-json "$tmp/jobs-$run_id.json" \
      || fail "CURRENT_RUN_UPSTREAM_NOT_COMPLETE:$run_id"
  fi

  printf '%s\n' "$run_id" >>"$successful_runs"
done <"$tmp/candidates"
[[ -s "$successful_runs" ]] || fail "SUCCESSFUL_MAIN_STAGE_RUN_NOT_FOUND"

# shellcheck source=provider-pins.sh
source "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/provider-pins.sh"
bindings="$tmp/bindings"
: >"$bindings"
selected_run=
selected_stage=
while read -r run_id; do
  [[ -n "$run_id" ]] || continue
  download="$tmp/download-$run_id"
  mkdir -p "$download"
  gh run download "$run_id" -R "$repository" -n "$artifact_name" -D "$download" || fail "ARTIFACT_DOWNLOAD:$run_id"
  stage_root=$(python3 - "$download" <<'PY'
import pathlib, sys
root = pathlib.Path(sys.argv[1])
matches = [path.parent for path in root.rglob("pretag-manifest.json") if path.is_file()]
unique = sorted({str(path.resolve()) for path in matches})
if len(unique) != 1:
    raise SystemExit(1)
print(unique[0])
PY
  ) || fail "MANIFEST_COUNT:$run_id"
  python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/verify-pretag-stage.py" \
    --dir "$stage_root" \
    --version "$version" \
    --source-head "$expected" \
    --codex-version "$CODEX_VERSION" \
    --claude-version "$CLAUDE_VERSION" || fail "VERIFY:$run_id"
  binding=$(python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/stage-binding.py" --dir "$stage_root") || fail "BINDING:$run_id"
  printf '%s %s\n' "$run_id" "$binding" >>"$bindings"
  if [[ -z "$selected_run" ]]; then
    selected_run=$run_id
    selected_stage=$stage_root
  fi
done <"$successful_runs"

python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/stage-binding.py" --check "$bindings" || fail "DIVERGENT_SUCCESSFUL_STAGES"
[[ -n "$selected_run" && -n "$selected_stage" ]] || fail "SUCCESSFUL_MAIN_STAGE_RUN_NOT_FOUND"

rm -rf -- "$destination"
mkdir -p "$destination"
cp -R "$selected_stage"/. "$destination"/

python3 "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)/verify-pretag-stage.py" \
  --dir "$destination" \
  --version "$version" \
  --source-head "$expected" \
  --codex-version "$CODEX_VERSION" \
  --claude-version "$CLAUDE_VERSION" || fail "VERIFY"

printf 'PRETAG_STAGE_RESOLVED run=%s artifact=%s\n' "$selected_run" "$artifact_name"
