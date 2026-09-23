#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: scripts/release/local-plugin-activation-smoke.sh rehearse --expected-head SHA --plugin-id ID" >&2
  echo "       scripts/release/local-plugin-activation-smoke.sh stage --expected-head SHA --artifact PATH --plugin-id ID" >&2
  exit 64
}

fail() {
  echo "PLUGIN_RELEASE_SMOKE_BLOCKED:$1" >&2
  exit "${2:-1}"
}

phase=${1:-}
[[ "$phase" == "rehearse" || "$phase" == "stage" ]] || usage
shift || true

artifact_input=
expected_head=
plugin_id=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --artifact) artifact_input=${2:-}; shift 2 ;;
    --expected-head) expected_head=${2:-}; shift 2 ;;
    --plugin-id) plugin_id=${2:-}; shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$plugin_id" ]] || fail "PLUGIN_ID_REQUIRED"
[[ "$expected_head" =~ ^[0-9a-f]{40}$|^[0-9a-f]{64}$ ]] || fail "EXPECTED_HEAD_REQUIRED"
if [[ "$phase" == "stage" ]]; then
  [[ -n "$artifact_input" ]] || fail "ARTIFACT_REQUIRED"
else
  [[ -z "$artifact_input" ]] || usage
fi

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"

[[ "$(uname -s)" == "Darwin" ]] || fail "MACOS_REQUIRED"
[[ "$(uname -m)" == "arm64" ]] || fail "APPLE_SILICON_REQUIRED"
for name in git cargo python3 claude npm shasum tar; do
  command -v "$name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$name"
done
[[ -z "$(git status --porcelain)" ]] || fail "WORKTREE_NOT_CLEAN"

# shellcheck source=provider-pins.sh
source "$root/scripts/release/provider-pins.sh"
bash "$root/scripts/release/check-provider-pins.sh" || fail "PROVIDER_PINS"
claude_executable=$(command -v claude)
claude_version_output=$(claude --version 2>&1 | head -1) || fail "CLAUDE_VERSION"
claude_version=$(python3 - "$claude_version_output" <<'PY'
import re, sys
match = re.search(r"([0-9]+\.[0-9]+\.[0-9]+)", sys.argv[1])
if match is None:
    raise SystemExit(1)
print(match.group(1))
PY
) || fail "CLAUDE_VERSION_PARSE"
[[ "$claude_version" == "$CLAUDE_VERSION" ]] || fail "CLAUDE_NOT_CURRENT_STABLE"
claude_provider_sha=$(shasum -a 256 "$claude_executable" | awk '{print $1}')
[[ "$claude_provider_sha" =~ ^[0-9a-f]{64}$ ]] || fail "CLAUDE_PROVIDER_SHA256"

version=$(python3 - <<'PY'
import tomllib
with open("Cargo.toml", "rb") as handle:
    print(tomllib.load(handle)["package"]["version"])
PY
)
head=$(git rev-parse HEAD)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-plugin-release-smoke.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

artifact=
source_head=
source_tree=
reviewed_content_digest=
assets="$tmp/assets"
mkdir -p "$assets"

if [[ "$phase" == "rehearse" ]]; then
  source_head="$head"
  [[ "$head" == "$expected_head" ]] || fail "HEAD_NOT_EXPECTED_CANDIDATE"
  source_tree=$(git rev-parse "HEAD^{tree}")
  python3 scripts/release/check-release-contract.py --report >/dev/null || fail "RELEASE_CONTRACT"
  reviewed_content_digest=$(python3 - "$version" <<'PY'
import json, sys
version = sys.argv[1]
with open(f"reports/release/v{version}-review.json", encoding="utf-8") as handle:
    print(json.load(handle)["reviewed_content_digest"])
PY
)
  [[ "$reviewed_content_digest" =~ ^[0-9a-f]{64}$ ]] || fail "REVIEW_CONTENT_DIGEST"

  cargo fetch --locked >/dev/null
  CLROOM_SOURCE_COMMIT="$source_head" CLROOM_TARGET='' \
    ./packaging/build-artifacts.sh "$assets" >"$tmp/build.log"
  artifact=$(sed -n 's/^ARTIFACT=//p' "$tmp/build.log" | tail -1)
  [[ -n "$artifact" && -f "$artifact" ]] || fail "ARTIFACT_MISSING"
else
  source_head="$head"
  [[ "$head" == "$expected_head" ]] || fail "HEAD_NOT_EXPECTED_ACCEPTED_MAIN"
  source_tree=$(git rev-parse "HEAD^{tree}")
  python3 scripts/release/check-release-contract.py --report >/dev/null || fail "RELEASE_CONTRACT"
  reviewed_content_digest=$(python3 - "$version" <<'PY'
import json, sys
version = sys.argv[1]
with open(f"reports/release/v{version}-review.json", encoding="utf-8") as handle:
    print(json.load(handle)["reviewed_content_digest"])
PY
)
  [[ "$reviewed_content_digest" =~ ^[0-9a-f]{64}$ ]] || fail "REVIEW_CONTENT_DIGEST"
  artifact=$(python3 - "$artifact_input" <<'PY'
import pathlib, sys
path = pathlib.Path(sys.argv[1]).expanduser().resolve()
if not path.is_file():
    raise SystemExit(1)
print(path)
PY
) || fail "STAGED_ARTIFACT_MISSING"
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

agents_boundary_probe=false
probe_root="$tmp/agents-boundary-probe"
probe_home="$probe_root/home"
probe_workspace="$probe_home/workspace"
probe_repository="$probe_workspace/repo"
probe_project="$probe_repository/nested"
probe_bin="$probe_root/bin"
probe_tmp="$probe_root/tmp"
probe_marker="$probe_tmp/provider-executed"
mkdir -p \
  "$probe_home/.claude/skills" \
  "$probe_workspace/.claude" \
  "$probe_repository/.claude" \
  "$probe_project/.claude" \
  "$probe_bin" \
  "$probe_tmp"
chmod 0700 "$probe_tmp"
[[ "$(stat -f '%Lp' "$probe_tmp")" == 700 ]] || fail "AGENTS_BOUNDARY_TMPDIR_NOT_PRIVATE"
printf '%s\n' 'ambient home instructions' >"$probe_home/AGENTS.md"
printf '%s\n' 'ambient workspace instructions' >"$probe_workspace/AGENTS.md"
printf '%s\n' 'ambient hidden workspace instructions' >"$probe_workspace/.claude/AGENTS.md"
printf '%s\n' 'gitdir: synthetic-worktree' >"$probe_repository/.git"
printf '%s\n' 'repository instructions' >"$probe_repository/AGENTS.md"
printf '%s\n' 'repository hidden instructions' >"$probe_repository/.claude/AGENTS.md"
printf '%s\n' 'nested instructions' >"$probe_project/AGENTS.md"
printf '%s\n' 'nested hidden instructions' >"$probe_project/.claude/AGENTS.md"
cat >"$probe_bin/claude" <<'SH'
#!/bin/sh
if [ "$#" -eq 1 ] && [ "${1:-}" = "--version" ]; then
  printf '2.1.280\n'
  exit 0
fi
for path in "$HOME/AGENTS.md" "$HOME/workspace/AGENTS.md" "$HOME/workspace/.claude/AGENTS.md"; do
  /bin/cat "$path" >/dev/null 2>&1 && exit 100
done
/bin/cat "$HOME/workspace/repo/AGENTS.md" >/dev/null 2>&1 || exit 101
/bin/cat "$HOME/workspace/repo/.claude/AGENTS.md" >/dev/null 2>&1 || exit 102
/bin/cat "$PWD/AGENTS.md" >/dev/null 2>&1 || exit 103
/bin/cat "$PWD/.claude/AGENTS.md" >/dev/null 2>&1 || exit 104
printf '%s\n' executed >"$TMPDIR/provider-executed" || exit 105
exit 0
SH
chmod 0700 "$probe_bin/claude"
if ! (
  cd "$probe_project"
  HOME="$probe_home" \
  PATH="$probe_bin:/usr/bin:/bin" \
  TMPDIR="$probe_tmp" \
  TERM="${TERM:-dumb}" \
    "$clroom" claude \
      >"$probe_root/stdout.log" 2>"$probe_root/stderr.log"
); then
  fail "AGENTS_BOUNDARY_SANDBOX_PROBE"
fi
[[ "$(cat "$probe_marker" 2>/dev/null || true)" == executed ]] \
  || fail "AGENTS_BOUNDARY_PROVIDER_NOT_EXECUTED"
agents_boundary_probe=true
echo "AGENTS_BOUNDARY_PROVIDER_EXECUTED=PASS"
echo "AGENTS_BOUNDARY_SANDBOX_PROBE=PASS"

registry="$HOME/.claude/plugins/installed_plugins.json"
[[ -f "$registry" ]] || fail "PLUGIN_REGISTRY_MISSING"

fingerprint() {
python3 <<'PY'
import hashlib, os
paths=[
    "~/.claude/settings.json",
    "~/.claude/settings.local.json",
    "~/.claude/plugins/installed_plugins.json",
    "~/.claude/plugins/known_marketplaces.json",
]
h=hashlib.sha256()
for raw in paths:
    p=os.path.expanduser(raw)
    h.update(raw.encode()+b"\0")
    if os.path.isfile(p):
        with open(p,"rb") as f: h.update(f.read())
    else:
        h.update(b"<missing>")
    h.update(b"\0")
print(h.hexdigest())
PY
}

before=$(fingerprint)
"$clroom" --output json info claude "plugin:$plugin_id" >"$tmp/info.json" 2>"$tmp/info.err"   || fail "PLUGIN_INFO"

python3 - "$plugin_id" "$tmp/info.json" <<'PY' || fail "PLUGIN_INFO_PREFLIGHT"
import json, sys
plugin_id, info_path = sys.argv[1:]
info = json.load(open(info_path, encoding="utf-8"))
entries = info.get("native_entries") or []
if len(entries) != 1:
    print(f"PLUGIN_INFO_PREFLIGHT_BLOCKED entry_count={len(entries)}", file=sys.stderr)
    raise SystemExit(1)
entry = entries[0]
native = entry.get("native") or {}
kinds = sorted({
    item.get("kind")
    for item in (entry.get("effective_components") or [])
    if isinstance(item, dict)
})
qualified = (
    native.get("id") == plugin_id
    and entry.get("installation") == "installed"
    and entry.get("selection") == "selectable"
    and entry.get("qualification") == "qualified"
    and entry.get("activation_policy") == "atomic_bundle"
    and not (entry.get("conflicts") or [])
    and kinds == ["skill"]
)
if not qualified:
    details = {
        "native_id": native.get("id"),
        "installation": entry.get("installation"),
        "selection": entry.get("selection"),
        "qualification": entry.get("qualification"),
        "activation_policy": entry.get("activation_policy"),
        "conflicts": entry.get("conflicts") or [],
        "kinds": kinds,
    }
    print("PLUGIN_INFO_PREFLIGHT_BLOCKED " + json.dumps(details, sort_keys=True), file=sys.stderr)
    raise SystemExit(1)
print("PLUGIN_INFO_PREFLIGHT=PASS")
PY

set +e
"$clroom" claude -p --output-format stream-json --verbose "Reply exactly UNUSED."   >"$tmp/clean.jsonl" 2>"$tmp/clean.err"
clean_rc=$?
"$clroom" claude --with="plugin:$plugin_id" -p --output-format stream-json --verbose   "Reply exactly UNUSED." >"$tmp/selected.jsonl" 2>"$tmp/selected.err"
selected_rc=$?
set -e

after=$(fingerprint)
[[ "$before" == "$after" ]] || fail "PERSISTENT_CONFIG_CHANGED"

python3 - "$registry" "$plugin_id" "$tmp/info.json" "$tmp/clean.jsonl" "$tmp/selected.jsonl" <<'PY'   || fail "AUTOMATED_PLUGIN_E2E"
import json, os, sys
registry_path, plugin_id, info_path, clean_path, selected_path=sys.argv[1:]

registry=json.load(open(registry_path,encoding="utf-8"))
installed=registry.get("plugins",{})

def roots_for(pid):
    roots=[]
    for record in installed.get(pid,[]) if isinstance(installed.get(pid,[]),list) else []:
        if isinstance(record,dict):
            path=record.get("installPath")
            if isinstance(path,str) and os.path.isdir(path):
                roots.append(os.path.realpath(path))
    return sorted(set(roots))

if len(roots_for(plugin_id)) != 1:
    raise SystemExit("plugin-root-not-exact")

info=json.load(open(info_path,encoding="utf-8"))
entries=info.get("native_entries") or []
if len(entries) != 1:
    raise SystemExit("info-entry-count")
entry=entries[0]
native=entry.get("native") or {}
kinds=sorted({
    item.get("kind")
    for item in (entry.get("effective_components") or [])
    if isinstance(item,dict)
})
if not (
    native.get("id")==plugin_id
    and entry.get("installation")=="installed"
    and entry.get("selection")=="selectable"
    and entry.get("qualification")=="qualified"
    and entry.get("activation_policy")=="atomic_bundle"
    and not (entry.get("conflicts") or [])
    and kinds==["skill"]
):
    raise SystemExit("plugin-not-qualified-skill-only")

def read_init(path):
    init=None
    with open(path,encoding="utf-8") as handle:
        for raw in handle:
            try: obj=json.loads(raw)
            except Exception: continue
            if obj.get("type")=="system" and obj.get("subtype")=="init":
                init=obj
    return init

clean=read_init(clean_path)
selected=read_init(selected_path)
if clean is None or selected is None:
    raise SystemExit("missing-system-init")

def matches(plugin,pid):
    name=pid.rsplit("@",1)[0]
    roots=roots_for(pid)
    if isinstance(plugin,str):
        return plugin in (pid,name) or pid in plugin or (
            os.path.isabs(plugin) and os.path.realpath(plugin) in roots
        )
    if not isinstance(plugin,dict):
        return False
    for key in ("name","id","plugin_id","source"):
        value=plugin.get(key)
        if isinstance(value,str) and (value in (pid,name) or pid in value):
            return True
    path=plugin.get("path")
    return isinstance(path,str) and os.path.isabs(path) and os.path.realpath(path) in roots

clean_plugins=clean.get("plugins") or []
selected_plugins=selected.get("plugins") or []
if any(matches(p,plugin_id) for p in clean_plugins):
    raise SystemExit("target-present-in-clean")
if not any(matches(p,plugin_id) for p in selected_plugins):
    raise SystemExit("target-absent-in-selected")
if selected.get("plugin_errors"):
    raise SystemExit("selected-plugin-errors")

for pid in installed:
    if pid==plugin_id: continue
    clean_has=any(matches(p,pid) for p in clean_plugins)
    selected_has=any(matches(p,pid) for p in selected_plugins)
    if selected_has and not clean_has:
        raise SystemExit("new-sibling-plugin:"+pid)

print("AUTOMATED_PLUGIN_E2E=PASS")
PY

interactive=false
external_ancestor_agents_absent=false
project_agents_retained=false
if [[ "$phase" == "rehearse" ]]; then
  [[ -t 0 && -t 1 ]] || fail "INTERACTIVE_TTY_REQUIRED"

  tui_workspace="$tmp/real-tui-workspace"
  tui_repository="$tui_workspace/repo"
  tui_project="$tui_repository/nested"
  mkdir -p     "$tui_workspace/.claude"     "$tui_repository/.claude"     "$tui_project/.claude"
  printf '%s\n' 'external TUI probe instruction' >"$tui_workspace/AGENTS.md"
  printf '%s\n' 'external hidden TUI probe instruction' >"$tui_workspace/.claude/AGENTS.md"
  printf '%s\n' 'gitdir: synthetic-worktree' >"$tui_repository/.git"
  printf '%s\n' 'repository TUI probe instruction' >"$tui_repository/AGENTS.md"
  printf '%s\n' 'repository hidden TUI probe instruction' >"$tui_repository/.claude/AGENTS.md"
  printf '%s\n' 'nested TUI probe instruction' >"$tui_project/AGENTS.md"
  printf '%s\n' 'nested hidden TUI probe instruction' >"$tui_project/.claude/AGENTS.md"

  echo
  echo "=== INTERACTIVE SELECTED-PLUGIN TUI ==="
  echo "Do not send a model prompt."
  echo "This TUI runs in a task-owned synthetic nested Git project."
  echo "Confirm the selected plugin skill is visible in autocomplete."
  echo "For agents-md, confirm repo/nested project AGENTS.md is reported as loaded."
  echo "Reject the smoke if the parent workspace AGENTS.md or .claude/AGENTS.md is reported as loaded."
  echo "Exit normally with /exit."
  echo
  (
    cd "$tui_project"
    "$clroom" claude --with="plugin:$plugin_id"
  ) || fail "SELECTED_TUI_EXIT"
  printf 'TUI opened normally and selected plugin skill was visible [y/N]: '
  read -r answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || fail "SELECTED_TUI_NOT_CONFIRMED"
  printf 'Repo/nested project AGENTS.md was reported as loaded [y/N]: '
  read -r project_agents_answer
  [[ "$project_agents_answer" == "y" || "$project_agents_answer" == "Y" ]]     || fail "PROJECT_AGENTS_NOT_CONFIRMED"
  printf 'No AGENTS.md above the synthetic Git project was reported as loaded [y/N]: '
  read -r agents_answer
  [[ "$agents_answer" == "y" || "$agents_answer" == "Y" ]]     || fail "EXTERNAL_ANCESTOR_AGENTS_NOT_CONFIRMED"
  interactive=true
  project_agents_retained=true
  external_ancestor_agents_absent=true
  [[ "$before" == "$(fingerprint)" ]] || fail "PERSISTENT_CONFIG_CHANGED_INTERACTIVE"
fi

[[ "$(claude --version 2>&1 | head -1)" == "$claude_version_output" ]] || fail "CLAUDE_PROVIDER_VERSION_CHANGED"
[[ "$(shasum -a 256 "$(command -v claude)" | awk '{print $1}')" == "$claude_provider_sha" ]] || fail "CLAUDE_PROVIDER_BYTES_CHANGED"

git_common_dir=$(git rev-parse --git-common-dir)
if [[ "$git_common_dir" != /* ]]; then git_common_dir="$root/$git_common_dir"; fi
evidence_dir=${CLROOM_RELEASE_EVIDENCE_DIR:-"$git_common_dir/clroom-release-evidence"}
mkdir -p "$evidence_dir"
if [[ "$phase" == "rehearse" ]]; then evidence_key=${reviewed_content_digest:0:12}; else evidence_key=${source_head:0:12}; fi
evidence="$evidence_dir/${phase}-v${version}-${evidence_key}.json"
binding="content-addressed-runtime-v1"
if [[ "$phase" == "stage" ]]; then binding="exact-release-artifact-v1"; fi
python3 - "$evidence" "$phase" "$version" "$source_head" "$source_tree" "$reviewed_content_digest" "$artifact_sha" \
  "$binding" "$plugin_id" "$clean_rc" "$selected_rc" "$interactive" "$external_ancestor_agents_absent" \
  "$project_agents_retained" "$agents_boundary_probe" "$claude_version_output" \
  "$claude_version" "$claude_provider_sha" <<'PY'
import datetime, json, sys
output,phase,version,source,source_tree,reviewed_content_digest,artifact_sha,binding,plugin_id,clean_rc,selected_rc,interactive,external_ancestor_agents_absent,project_agents_retained,agents_boundary_probe,claude_version_output,claude_version,claude_provider_sha=sys.argv[1:]
record={
  "schema_version":"clroom.plugin-release-smoke.v3",
  "result":"PASS",
  "phase":phase,
  "release_version":version,
  "source_head":source,
  "source_tree":source_tree,
  "reviewed_content_digest":reviewed_content_digest,
  "evidence_binding":binding,
  "artifact_sha256":artifact_sha,
  "platform":"macos-aarch64",
  "claude_version_output":claude_version_output,
  "claude_version":claude_version,
  "claude_provider_sha256":claude_provider_sha,
  "plugin_id":plugin_id,
  "clean_system_init":True,
  "selected_system_init":True,
  "clean_target_plugin":False,
  "selected_target_plugin":True,
  "new_sibling_plugins":0,
  "selected_plugin_errors":0,
  "persistent_config_unchanged":True,
  "interactive_selected_tui_confirmed": interactive=="true",
  "automated_probe_prompt_supplied":True,
  "interactive_no_model_prompt_confirmed": interactive=="true",
  "external_ancestor_agents_absent_confirmed": external_ancestor_agents_absent=="true",
  "project_agents_retained_confirmed": project_agents_retained=="true",
  "external_ancestor_agents_sandbox_probe_passed": agents_boundary_probe=="true",
  "clean_provider_rc":int(clean_rc),
  "selected_provider_rc":int(selected_rc),
  "observed_at_utc":datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),
}
with open(output,"w",encoding="utf-8") as f:
    json.dump(record,f,sort_keys=True,indent=2)
    f.write("\n")
PY

echo "PLUGIN_RELEASE_SMOKE=PASS"
echo "PHASE=$phase"
echo "SOURCE_HEAD=$source_head"
echo "SOURCE_TREE=$source_tree"
echo "REVIEWED_CONTENT_DIGEST=$reviewed_content_digest"
echo "ARTIFACT_SHA256=$artifact_sha"
echo "PLUGIN_ID=$plugin_id"
echo "CLEAN_PROVIDER_RC=$clean_rc"
echo "SELECTED_PROVIDER_RC=$selected_rc"
echo "PERSISTENT_CONFIG_UNCHANGED=YES"
echo "EVIDENCE_FILE=${evidence#$root/}"
