#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'CODEX_DRAFT_EVIDENCE_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

[[ $# -eq 3 ]] || fail "USAGE" 64
version=$1
expected=$2
destination=$3
[[ "$version" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "VERSION"
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || fail "EXPECTED_SHA"

repository="y-sor/clean-room-launcher"
tag="v$version"
command -v gh >/dev/null 2>&1 || fail "GH_REQUIRED"
command -v python3 >/dev/null 2>&1 || fail "PYTHON_REQUIRED"
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED"

artifact_name="codex-draft-${tag}-${expected}"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-codex-draft-evidence.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

gh api -X GET "repos/$repository/actions/artifacts" \
  -f name="$artifact_name" -f per_page=100 >"$tmp/artifacts.json" \
  || fail "ARTIFACT_QUERY"

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
  if python3 - "$tmp/run.json" "$tag" "$expected" <<'PY'
import json, sys
path, tag, expected = sys.argv[1:]
run = json.load(open(path, encoding="utf-8"))
required = {
    "name": "Release",
    "event": "push",
    "status": "completed",
    "conclusion": "success",
    "path": ".github/workflows/release.yml",
    "head_branch": tag,
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

[[ -n "$selected_run" ]] || fail "SUCCESSFUL_TAG_RUN_NOT_FOUND"

mkdir -p "$tmp/download"
gh run download "$selected_run" -R "$repository" -n "$artifact_name" -D "$tmp/download" \
  || fail "ARTIFACT_DOWNLOAD"

expected_file="codex-draft-v${version}-${expected:0:12}.json"
mapfile -t matches < <(find "$tmp/download" -type f -name "$expected_file" -print)
[[ ${#matches[@]} -eq 1 ]] || fail "EVIDENCE_FILE_COUNT"
source_path=${matches[0]}

python3 - "$source_path" "$version" "$expected" <<'PY'
import json, re, sys
path, version, expected = sys.argv[1:]
record = json.load(open(path, encoding="utf-8"))
required = {
    "schema_version": "clroom.codex-plugin-release-smoke.v4",
    "result": "PASS",
    "phase": "draft",
    "release_version": version,
    "source_head": expected,
    "platform": "macos-aarch64",
    "plugin_id": "standalone-mcp@clroom-fixture",
    "expected_mcp": "clroom_fixture",
    "real_provider_runtime_confirmed": True,
    "expected_mcp_runtime_healthy_confirmed": True,
    "provider_mcp_initialize_observed": True,
    "provider_mcp_tools_list_observed": True,
    "fixture_mcp_tool_call_passed": True,
    "provider_state_lifecycle_closed": True,
    "post_runtime_clean_confirmed": True,
    "model_prompt_sent": False,
}
for key, value in required.items():
    if record.get(key) != value:
        raise SystemExit(f"invalid:{key}")
for key in ("artifact_sha256", "codex_provider_sha256", "plugin_source_sha256"):
    if not re.fullmatch(r"[0-9a-f]{64}", str(record.get(key, ""))):
        raise SystemExit(f"invalid:{key}")
PY

mkdir -p "$(dirname "$destination")"
install -m 0600 "$source_path" "$destination"
printf 'CODEX_DRAFT_EVIDENCE_RESOLVED run=%s artifact=%s\n' "$selected_run" "$artifact_name"
