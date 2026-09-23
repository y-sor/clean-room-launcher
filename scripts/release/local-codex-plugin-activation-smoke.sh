#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: scripts/release/local-codex-plugin-activation-smoke.sh rehearse --expected-head SHA --fixture-standalone-mcp" >&2
  echo "       scripts/release/local-codex-plugin-activation-smoke.sh stage --expected-head SHA --artifact PATH --fixture-standalone-mcp" >&2
  exit 64
}

fail() {
  echo "CODEX_PLUGIN_RELEASE_SMOKE_BLOCKED:$1" >&2
  exit "${2:-1}"
}

fail_from_stderr() {
  local label=$1
  local stderr_path=$2
  local fixture_detail=
  local root_code=
  fixture_detail=$(sed -n 's/^CODEX_MCP_FIXTURE_BLOCKED://p' "$stderr_path" 2>/dev/null | tail -1 || true)
  if [[ -n "$fixture_detail" ]]; then
    fail "$label:$fixture_detail"
  fi
  root_code=$(grep -Eo 'CLROOM_[A-Z0-9_]+' "$stderr_path" 2>/dev/null | tail -1 || true)
  if [[ -n "$root_code" ]]; then
    fail "$label:$root_code"
  fi
  fail "$label"
}

phase=${1:-}
[[ "$phase" == "rehearse" || "$phase" == "stage" ]] || usage
shift || true

artifact_input=
expected_head=
plugin_id=
expected_mcp=
fixture_standalone_mcp=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact) artifact_input=${2:-}; shift 2 ;;
    --expected-head) expected_head=${2:-}; shift 2 ;;
    --plugin-id) plugin_id=${2:-}; shift 2 ;;
    --expected-mcp) expected_mcp=${2:-}; shift 2 ;;
    --fixture-standalone-mcp) fixture_standalone_mcp=true; shift ;;
    *) usage ;;
  esac
done
if [[ "$fixture_standalone_mcp" == true ]]; then
  [[ -z "$plugin_id" && -z "$expected_mcp" ]] || usage
  plugin_id=standalone-mcp@clroom-fixture
  expected_mcp=clroom_fixture
else
  fail "STANDALONE_FIXTURE_REQUIRED"
fi
[[ "$expected_head" =~ ^[0-9a-f]{40}$|^[0-9a-f]{64}$ ]] || fail "EXPECTED_HEAD_REQUIRED"
if [[ "$phase" == "stage" ]]; then
  [[ -n "$artifact_input" && -f "$artifact_input" ]] || fail "STAGE_ARTIFACT_REQUIRED"
else
  [[ -z "$artifact_input" ]] || usage
fi

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"

[[ "$(uname -s)" == "Darwin" ]] || fail "MACOS_REQUIRED"
[[ "$(uname -m)" == "arm64" ]] || fail "APPLE_SILICON_REQUIRED"
for name in git cargo python3 codex npm shasum tar; do
  command -v "$name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$name"
done
[[ -z "$(git status --porcelain)" ]] || fail "WORKTREE_NOT_CLEAN"

# shellcheck source=provider-pins.sh
source "$root/scripts/release/provider-pins.sh"
bash "$root/scripts/release/check-provider-pins.sh" || fail "PROVIDER_PINS"
codex_executable=$(command -v codex)
codex_version_output=$(codex --version 2>&1 | head -1) || fail "CODEX_VERSION"
codex_version=$(python3 - "$codex_version_output" <<'PY'
import re, sys
match = re.search(r"([0-9]+\.[0-9]+\.[0-9]+)", sys.argv[1])
if match is None:
    raise SystemExit(1)
print(match.group(1))
PY
) || fail "CODEX_VERSION_PARSE"
[[ "$codex_version" == "$CODEX_VERSION" ]] || fail "CODEX_NOT_CURRENT_STABLE"
codex_provider_sha=$(shasum -a 256 "$codex_executable" | awk '{print $1}')
[[ "$codex_provider_sha" =~ ^[0-9a-f]{64}$ ]] || fail "CODEX_PROVIDER_SHA256"

version=$(python3 - <<'PY'
import tomllib
with open("Cargo.toml", "rb") as handle:
    print(tomllib.load(handle)["package"]["version"])
PY
)
head=$(git rev-parse HEAD)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-codex-plugin-release-smoke.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

artifact=
source_head="$head"
source_tree=$(git rev-parse "HEAD^{tree}")
reviewed_content_digest=
assets="$tmp/assets"
mkdir -p "$assets"

[[ "$head" == "$expected_head" ]] || fail "HEAD_NOT_EXPECTED_CANDIDATE"
python3 scripts/release/check-release-contract.py --report >/dev/null || fail "RELEASE_CONTRACT"
review_path="reports/release/v${version}-review.json"
[[ -f "$review_path" ]] || fail "REVIEW_FILE_MISSING"
reviewed_content_digest=$(python3 - "$review_path" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["reviewed_content_digest"])
PY
)
[[ "$reviewed_content_digest" =~ ^[0-9a-f]{64}$ ]] || fail "REVIEW_CONTENT_DIGEST"

if [[ "$phase" == "rehearse" ]]; then
  cargo fetch --locked >/dev/null
  CLROOM_SOURCE_COMMIT="$source_head" CLROOM_TARGET='' \
    ./packaging/build-artifacts.sh "$assets" >"$tmp/build.log"
  artifact=$(sed -n 's/^ARTIFACT=//p' "$tmp/build.log" | tail -1)
  [[ -n "$artifact" && -f "$artifact" ]] || fail "ARTIFACT_MISSING"
else
  artifact="$artifact_input"
fi

python3 packaging/verify-artifact.py "$artifact" >/dev/null || fail "ARTIFACT_METADATA"
artifact_sha=$(shasum -a 256 "$artifact" | awk '{print $1}')

mkdir "$tmp/unpack"
tar -xzf "$artifact" -C "$tmp/unpack"
archive_root=$(find "$tmp/unpack" -mindepth 1 -maxdepth 1 -type d -print -quit)
[[ -n "$archive_root" ]] || fail "ARCHIVE_ROOT_MISSING"
clroom="$archive_root/bin/clroom"
[[ -x "$clroom" ]] || fail "ARCHIVE_CLROOM_MISSING"
grep -Fqx "version=$version" "$archive_root/VERSION" || fail "ARCHIVE_VERSION"
grep -Fqx "source_commit=$source_head" "$archive_root/VERSION" || fail "ARCHIVE_SOURCE"

fixture_home="$tmp/fixture-home"
mkdir -p "$fixture_home"
chmod 0700 "$fixture_home"
ambient_codex_home="$fixture_home/.codex"
fixture_log="$tmp/codex-mcp.log"
fixture_plugin=$(python3 "$root/scripts/release/codex-mcp-fixture.py" install \
  --codex-home "$ambient_codex_home" --log "$fixture_log") \
  || fail "STANDALONE_FIXTURE_INSTALL"
export HOME="$fixture_home"
export CODEX_HOME="$ambient_codex_home"

plugin_source=$(python3 - "$ambient_codex_home" "$plugin_id" <<'PY'
import os, pathlib, re, sys
home = pathlib.Path(sys.argv[1]).expanduser()
plugin_id = sys.argv[2]
try:
    plugin, marketplace = plugin_id.rsplit("@", 1)
except ValueError:
    raise SystemExit(1)
if not re.fullmatch(r"[A-Za-z0-9_.-]+", plugin) or plugin in {".", ".."}:
    raise SystemExit(1)
if not re.fullmatch(r"[A-Za-z0-9_-]+", marketplace):
    raise SystemExit(1)
cache = (home / "plugins" / "cache").resolve()
base = cache / marketplace / plugin
if not base.is_dir() or base.is_symlink():
    raise SystemExit(1)
local = base / "local"
if local.is_dir() and not local.is_symlink():
    candidates = [local]
else:
    candidates = sorted(
        path for path in base.iterdir()
        if path.is_dir() and not path.is_symlink()
    )
if len(candidates) != 1:
    raise SystemExit(1)
root = candidates[0].resolve()
if cache not in root.parents:
    raise SystemExit(1)
print(root)
PY
) || fail "PLUGIN_ROOT_NOT_EXACT"

fingerprint_tree() {
  python3 - "$@" <<'PY'
import hashlib, os, pathlib, stat, sys
h = hashlib.sha256()
for raw in sys.argv[1:]:
    root = pathlib.Path(raw).expanduser()
    h.update(str(root).encode() + b"\0")
    if not root.exists() and not root.is_symlink():
        h.update(b"<missing>\0")
        continue
    paths = [root]
    if root.is_dir() and not root.is_symlink():
        paths.extend(sorted(root.rglob("*"), key=lambda p: str(p)))
    for path in paths:
        rel = "." if path == root else str(path.relative_to(root))
        st = path.lstat()
        h.update(rel.encode() + b"\0")
        h.update(oct(stat.S_IFMT(st.st_mode)).encode() + b"\0")
        if stat.S_ISLNK(st.st_mode):
            h.update(os.readlink(path).encode() + b"\0")
        elif stat.S_ISREG(st.st_mode):
            with open(path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    h.update(chunk)
            h.update(b"\0")
        elif stat.S_ISDIR(st.st_mode):
            h.update(b"<dir>\0")
        else:
            h.update(b"<other>\0")
print(h.hexdigest())
PY
}

ambient_before=$(fingerprint_tree "$ambient_codex_home/config.toml" "$ambient_codex_home/plugins")
source_before=$(fingerprint_tree "$plugin_source")

"$clroom" --output json info codex "plugin:$plugin_id" >"$tmp/info.json" 2>"$tmp/info.err" \
  || fail "PLUGIN_INFO"

if ! "$clroom" codex mcp list --json >"$tmp/clean-before.json" 2>"$tmp/clean-before.err"; then
  fail_from_stderr "CLEAN_BEFORE_MCP_LIST" "$tmp/clean-before.err"
fi
if ! "$clroom" codex --with="plugin:$plugin_id" mcp list --json \
  >"$tmp/selected.json" 2>"$tmp/selected.err"; then
  fail_from_stderr "SELECTED_MCP_LIST" "$tmp/selected.err"
fi
if ! "$clroom" codex mcp list --json >"$tmp/clean-after.json" 2>"$tmp/clean-after.err"; then
  fail_from_stderr "CLEAN_AFTER_MCP_LIST" "$tmp/clean-after.err"
fi

ambient_after=$(fingerprint_tree "$ambient_codex_home/config.toml" "$ambient_codex_home/plugins")
source_after=$(fingerprint_tree "$plugin_source")
[[ "$ambient_before" == "$ambient_after" ]] || fail "PERSISTENT_PROVIDER_STATE_CHANGED"
[[ "$source_before" == "$source_after" ]] || fail "PLUGIN_SOURCE_CHANGED"

python3 - "$plugin_id" "$expected_mcp" "$tmp/info.json" \
  "$tmp/clean-before.json" "$tmp/selected.json" "$tmp/clean-after.json" \
  "$plugin_source" "$ambient_codex_home" <<'PY' \
  || fail "AUTOMATED_CODEX_PLUGIN_E2E"
import json, os, sys
(
    plugin_id, expected_mcp, info_path, clean_before_path, selected_path, clean_after_path,
    plugin_source, ambient_codex_home,
) = sys.argv[1:]

info = json.load(open(info_path, encoding="utf-8"))
entries = info.get("native_entries") or []
if len(entries) != 1:
    raise SystemExit("info-entry-count")
entry = entries[0]
native = entry.get("native") or {}
if not (
    native.get("id") == plugin_id
    and entry.get("installation") == "installed"
    and entry.get("selection") == "selectable"
    and entry.get("qualification") == "qualified"
    and entry.get("activation_policy") == "atomic_bundle"
    and not (entry.get("conflicts") or [])
    and (entry.get("effective_components") or [])
):
    raise SystemExit("plugin-not-qualified")

def names(path):
    data = json.load(open(path, encoding="utf-8"))
    if not isinstance(data, list):
        raise SystemExit("mcp-list-not-array")
    result = set()
    for item in data:
        if isinstance(item, dict) and isinstance(item.get("name"), str):
            result.add(item["name"])
    return result

clean_before = names(clean_before_path)
selected = names(selected_path)
clean_after = names(clean_after_path)
if expected_mcp in clean_before:
    raise SystemExit("expected-mcp-present-before-selection")
if expected_mcp not in selected:
    raise SystemExit("expected-mcp-absent-in-selected")
if expected_mcp in clean_after:
    raise SystemExit("expected-mcp-present-after-clean")

selected_data = json.load(open(selected_path, encoding="utf-8"))
selected_entry = next(
    (item for item in selected_data if isinstance(item, dict) and item.get("name") == expected_mcp),
    None,
)
if selected_entry is None:
    raise SystemExit("selected-entry-missing")
transport = selected_entry.get("transport") or {}
source_root = os.path.realpath(plugin_source)
cache_root = os.path.realpath(os.path.join(ambient_codex_home, "plugins", "cache"))
relative = os.path.relpath(source_root, cache_root)
if relative.startswith(".." + os.sep) or relative == "..":
    raise SystemExit("plugin-source-outside-cache")
shadow_root = os.path.realpath(os.path.join(
    ambient_codex_home, ".clroom-clean-state-v2", "home", "plugins", "cache", relative
))
legacy_path = os.path.join(source_root, ".mcp.json")
if not os.path.isfile(legacy_path):
    raise SystemExit("legacy-mcp-config-missing")
legacy = json.load(open(legacy_path, encoding="utf-8"))
servers = legacy.get("mcpServers", legacy)
original = servers.get(expected_mcp) if isinstance(servers, dict) else None
if not isinstance(original, dict):
    raise SystemExit("expected-mcp-source-missing")
rebased = 0
for field in ("command", "cwd"):
    raw = original.get(field)
    if not isinstance(raw, str) or not os.path.isabs(raw):
        continue
    resolved = os.path.realpath(raw)
    try:
        in_root = os.path.commonpath([source_root, resolved]) == source_root
    except ValueError:
        in_root = False
    if not in_root:
        continue
    expected = os.path.join(shadow_root, os.path.relpath(resolved, source_root))
    actual = transport.get(field)
    if not isinstance(actual, str) or os.path.realpath(actual) != os.path.realpath(expected):
        raise SystemExit(f"selected-{field}-not-shadow-rebased")
    rebased += 1
if rebased == 0:
    raise SystemExit("selected-mcp-rebase-target-missing")
print("SELECTED_MCP_PLUGIN_PATH_REBASE=PASS")
print("AUTOMATED_CODEX_PLUGIN_E2E=PASS")
PY

runtime_confirmed=false
runtime_mcp_healthy=false
post_runtime_clean=false
provider_mcp_initialize=false
provider_mcp_tools_list=false
fixture_mcp_tool_call=false

if ! python3 "$root/scripts/release/codex-mcp-fixture.py" probe-provider \
  --candidate "$clroom" \
  --mode clroom \
  --project "$root" \
  --home "$fixture_home" \
  --provider "$codex_executable" \
  --plugin-id "$plugin_id" \
  --log "$fixture_log" \
  2>"$tmp/selected-runtime.err"; then
  fail_from_stderr "SELECTED_MCP_RUNTIME" "$tmp/selected-runtime.err"
fi
runtime_confirmed=true
runtime_mcp_healthy=true
provider_mcp_initialize=true
provider_mcp_tools_list=true

python3 "$root/scripts/release/codex-mcp-fixture.py" probe-server \
  --server "$fixture_plugin/server.py" \
  || fail "FIXTURE_MCP_TOOL_CALL"
fixture_mcp_tool_call=true

if ! "$clroom" codex mcp list --json \
  >"$tmp/post-runtime-clean.json" 2>"$tmp/post-runtime-clean.err"; then
  fail_from_stderr "POST_RUNTIME_CLEAN_MCP_LIST" "$tmp/post-runtime-clean.err"
fi
python3 - "$expected_mcp" "$tmp/post-runtime-clean.json" <<'PY' \
  || fail "POST_RUNTIME_CLEAN_EXPECTED_MCP"
import json, sys
expected_mcp, path = sys.argv[1:]
data = json.load(open(path, encoding="utf-8"))
if not isinstance(data, list):
    raise SystemExit("mcp-list-not-array")
if any(isinstance(item, dict) and item.get("name") == expected_mcp for item in data):
    raise SystemExit("expected-mcp-present-after-interactive")
PY
post_runtime_clean=true
[[ "$ambient_before" == "$(fingerprint_tree "$ambient_codex_home/config.toml" "$ambient_codex_home/plugins")" ]] \
  || fail "PERSISTENT_PROVIDER_STATE_CHANGED_INTERACTIVE"
[[ "$source_before" == "$(fingerprint_tree "$plugin_source")" ]] \
  || fail "PLUGIN_SOURCE_CHANGED_INTERACTIVE"

git_common_dir=$(git rev-parse --git-common-dir)
if [[ "$git_common_dir" != /* ]]; then git_common_dir="$root/$git_common_dir"; fi
evidence_dir=${CLROOM_RELEASE_EVIDENCE_DIR:-"$git_common_dir/clroom-release-evidence"}
mkdir -p "$evidence_dir"
if [[ "$phase" == "rehearse" ]]; then evidence_key=${reviewed_content_digest:0:12}; else evidence_key=${source_head:0:12}; fi
evidence="$evidence_dir/codex-${phase}-v${version}-${evidence_key}.json"
python3 - "$evidence" "$phase" "$version" "$source_head" "$source_tree" "$reviewed_content_digest" "$artifact_sha" \
  "$plugin_id" "$expected_mcp" "$runtime_confirmed" "$runtime_mcp_healthy" "$post_runtime_clean" "$codex_version_output" \
  "$codex_version" "$codex_provider_sha" "$source_before" "$provider_mcp_initialize" \
  "$provider_mcp_tools_list" "$fixture_mcp_tool_call" <<'PY'
import datetime, json, sys
(
    output, phase, version, source, source_tree, reviewed_content_digest, artifact_sha, plugin_id, expected_mcp,
    runtime_confirmed, runtime_mcp_healthy, post_runtime_clean, codex_version_output, codex_version,
    codex_provider_sha, plugin_source_sha, provider_mcp_initialize,
    provider_mcp_tools_list, fixture_mcp_tool_call,
) = sys.argv[1:]
record = {
    "schema_version": "clroom.codex-plugin-release-smoke.v4",
    "result": "PASS",
    "phase": phase,
    "release_version": version,
    "source_head": source,
    "source_tree": source_tree,
    "reviewed_content_digest": reviewed_content_digest,
    "evidence_binding": "content-addressed-runtime-v1",
    "artifact_sha256": artifact_sha,
    "platform": "macos-aarch64",
    "codex_version_output": codex_version_output,
    "codex_version": codex_version,
    "codex_provider_sha256": codex_provider_sha,
    "plugin_id": plugin_id,
    "expected_mcp": expected_mcp,
    "plugin_source_sha256": plugin_source_sha,
    "clean_before_expected_mcp": False,
    "selected_expected_mcp": True,
    "selected_mcp_plugin_paths_rebased": True,
    "clean_after_expected_mcp": False,
    "ambient_config_and_plugin_tree_unchanged": True,
    "plugin_source_unchanged": True,
    "real_provider_runtime_confirmed": runtime_confirmed == "true",
    "expected_mcp_runtime_healthy_confirmed": runtime_mcp_healthy == "true",
    "model_prompt_sent": False,
    "provider_mcp_initialize_observed": provider_mcp_initialize == "true",
    "provider_mcp_tools_list_observed": provider_mcp_tools_list == "true",
    "fixture_mcp_tool_call_passed": fixture_mcp_tool_call == "true",
    "provider_state_lifecycle_closed": True,
    "post_runtime_clean_confirmed": post_runtime_clean == "true",
    "observed_at_utc": datetime.datetime.now(
        datetime.timezone.utc
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
}
with open(output, "w", encoding="utf-8") as handle:
    json.dump(record, handle, sort_keys=True, indent=2)
    handle.write("\n")
PY

echo "CODEX_PLUGIN_RELEASE_SMOKE=PASS"
echo "PHASE=$phase"
echo "SOURCE_HEAD=$source_head"
echo "SOURCE_TREE=$source_tree"
echo "REVIEWED_CONTENT_DIGEST=$reviewed_content_digest"
echo "ARTIFACT_SHA256=$artifact_sha"
echo "PLUGIN_ID=$plugin_id"
echo "EXPECTED_MCP=$expected_mcp"
echo "SELECTED_MCP_PLUGIN_PATH_REBASE=YES"
echo "AMBIENT_CONFIG_AND_PLUGIN_TREE_UNCHANGED=YES"
echo "PROVIDER_STATE_LIFECYCLE_CLOSED=YES"
echo "REAL_PROVIDER_RUNTIME_CONFIRMED=$runtime_confirmed"
echo "EXPECTED_MCP_RUNTIME_HEALTHY_CONFIRMED=$runtime_mcp_healthy"
echo "MODEL_PROMPT_SENT=NO"
echo "PROVIDER_MCP_INITIALIZE_OBSERVED=$provider_mcp_initialize"
echo "PROVIDER_MCP_TOOLS_LIST_OBSERVED=$provider_mcp_tools_list"
echo "FIXTURE_MCP_TOOL_CALL_PASSED=$fixture_mcp_tool_call"
echo "POST_RUNTIME_CLEAN_CONFIRMED=$post_runtime_clean"
echo "EVIDENCE_FILE=${evidence#$root/}"
