#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: scripts/release/local-plugin-activation-smoke.sh rehearse --expected-head SHA --plugin-id ID" >&2
  echo "       scripts/release/local-plugin-activation-smoke.sh diagnose-screen --expected-head SHA --plugin-id ID" >&2
  echo "       scripts/release/local-plugin-activation-smoke.sh stage --expected-head SHA --artifact PATH --plugin-id ID" >&2
  exit 64
}

fail() {
  echo "PLUGIN_RELEASE_SMOKE_BLOCKED:$1" >&2
  exit "${2:-1}"
}

phase=${1:-}
[[ "$phase" == "rehearse" || "$phase" == "diagnose-screen" || "$phase" == "stage" ]] || usage
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
  [[ -n "$artifact_input" && -f "$artifact_input" ]] || fail "STAGE_ARTIFACT_REQUIRED"
else
  [[ -z "$artifact_input" ]] || usage
fi

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"

[[ "$(uname -s)" == "Darwin" ]] || fail "MACOS_REQUIRED"
[[ "$(uname -m)" == "arm64" ]] || fail "APPLE_SILICON_REQUIRED"
for name in git cargo python3 npm shasum tar; do
  command -v "$name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$name"
done
[[ -z "$(git status --porcelain)" ]] || fail "WORKTREE_NOT_CLEAN"

version=$(python3 - <<'PY'
import tomllib
with open("Cargo.toml", "rb") as handle:
    print(tomllib.load(handle)["package"]["version"])
PY
)
head=$(git rev-parse HEAD)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-plugin-release-smoke.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

# The exact PR machine rehearsal (and accepted-main stage for phase=stage)
# owns mutable provider-latest resolution. Human TTY evidence reuses the exact
# pinned tuple and independently verifies exact package/native bytes.
provider_root="$tmp/providers"
provider_env="$tmp/provider.env"
: >"$provider_env"
bash "$root/scripts/release/provision-provider-canaries.sh" --all-frozen "$provider_root" "$provider_env" \
  || fail "PROVIDER_CANARY"
# shellcheck disable=SC1090
source "$provider_env"
export PATH="$provider_root/bin:$PATH"
if [[ "$phase" == "stage" ]]; then
  echo "PROVIDER_REGISTRY_FREEZE_REUSED=YES"
else
  echo "PROVIDER_PR_TUPLE_FREEZE_REUSED=YES"
fi

# shellcheck source=provider-pins.sh
source "$root/scripts/release/provider-pins.sh"
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

if [[ "$phase" != "stage" ]]; then
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
synthetic_claude_version=$CLAUDE_VERSION
{
  printf '%s\n' '#!/bin/sh'
  printf '%s\n' 'if [ "$#" -eq 1 ] && [ "${1:-}" = "--version" ]; then'
  printf "  printf '%%s\\\\n' '%s'\n" "$synthetic_claude_version"
  printf '%s\n' '  exit 0' 'fi'
  cat <<'SH'
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
} >"$probe_bin/claude"
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

plugin_info_preflight=true
probe_text="/${plugin_id%%@*}"
after=$(fingerprint)
[[ "$before" == "$after" ]] || fail "PERSISTENT_CONFIG_CHANGED"

if [[ "$phase" == "diagnose-screen" ]]; then
  [[ -t 0 && -t 1 ]] || fail "INTERACTIVE_TTY_REQUIRED"

  terminal_preflight_output=$(
    python3 "$root/scripts/release/terminal-state-diagnostic.py" --expected-head "$head"
  ) || {
    printf '%s\n' "$terminal_preflight_output"
    fail "PHYSICAL_TERMINAL_PREFLIGHT"
  }
  printf '%s\n' "$terminal_preflight_output"
  grep -Fqx "TERMINAL_STATE_DIAGNOSTIC=PASS" <<<"$terminal_preflight_output" \
    || fail "PHYSICAL_TERMINAL_PREFLIGHT_MARKER"

  diagnostic_evidence="$tmp/screen-control.json"
  echo
  echo "=== MACHINE SCREEN-CONTROL DIAGNOSTIC ==="
  echo "No human observation or keypress is required."
  echo "The supervisor stops after the first unsupported screen control and records only a normalized control identity plus SHA-256 fingerprint."
  echo
  (
    cd "$root"
    python3 "$root/scripts/release/claude-tty-supervisor.py" \
      --diagnose-unsupported \
      --diagnostic-evidence "$diagnostic_evidence" \
      -- "$clroom" claude
  ) || fail "SCREEN_CONTROL_DIAGNOSTIC"

  [[ "$before" == "$(fingerprint)" ]] || fail "PERSISTENT_CONFIG_CHANGED_SCREEN_DIAGNOSTIC"

  python3 - "$diagnostic_evidence" <<'PY' || fail "SCREEN_CONTROL_DIAGNOSTIC_EVIDENCE"
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    record = json.load(handle)

identity = record.get("unsupported_control_identity")
fingerprint = record.get("unsupported_control_sha256")
mutations = record.get("unsupported_mutations")

checks = (
    record.get("schema_version") == "clroom.claude-screen-control-diagnostic.v1",
    record.get("result") == "CAPTURED",
    isinstance(identity, str)
    and re.fullmatch(r"[A-Za-z0-9_|=?;,:.+_-]{1,256}", identity) is not None,
    isinstance(fingerprint, str)
    and re.fullmatch(r"[0-9a-f]{64}", fingerprint) is not None,
    isinstance(mutations, int) and mutations >= 1,
    record.get("screen_model_trusted") is False,
    record.get("physical_terminal_state_restored") is True,
    record.get("task_process_session_closed") is True,
    record.get("human_bytes_forwarded") == 0,
    record.get("submit_bytes_forwarded") == 0,
    record.get("raw_terminal_transcript_recorded") is False,
)
if not all(checks):
    raise SystemExit(1)

print(f"SCREEN_CONTROL_IDENTITY={identity}")
print(f"SCREEN_CONTROL_SHA256={fingerprint}")
print(f"SCREEN_CONTROL_UNSUPPORTED_MUTATIONS={mutations}")
print("SCREEN_CONTROL_RAW_TRANSCRIPT_RECORDED=NO")
print("SCREEN_CONTROL_DIAGNOSTIC=PASS")
PY

  [[ "$(claude --version 2>&1 | head -1)" == "$claude_version_output" ]] \
    || fail "CLAUDE_PROVIDER_VERSION_CHANGED"
  [[ "$(shasum -a 256 "$(command -v claude)" | awk '{print $1}')" == "$claude_provider_sha" ]] \
    || fail "CLAUDE_PROVIDER_BYTES_CHANGED"

  echo "PLUGIN_RELEASE_SCREEN_DIAGNOSTIC=CAPTURED"
  exit 0
fi

interactive=false
clean_tui=false
clean_tui_supervised=false
selected_tui_supervised=false
physical_terminal_preflight=false
interactive_terminal_state_restored=false
clean_target_plugin_absent=false
selected_target_plugin_visible=false
no_new_sibling_plugins=false
selected_plugin_errors_absent=false
no_model_prompt=false
external_ancestor_agents_absent=$agents_boundary_probe
project_agents_retained=$agents_boundary_probe
if [[ "$phase" == "rehearse" || "$phase" == "stage" ]]; then
  [[ -t 0 && -t 1 ]] || fail "INTERACTIVE_TTY_REQUIRED"

  terminal_preflight_output=$(
    python3 "$root/scripts/release/terminal-state-diagnostic.py" --expected-head "$head"
  ) || {
    printf '%s\n' "$terminal_preflight_output"
    fail "PHYSICAL_TERMINAL_PREFLIGHT"
  }
  printf '%s\n' "$terminal_preflight_output"
  grep -Fqx "TERMINAL_STATE_DIAGNOSTIC=PASS" <<<"$terminal_preflight_output" \
    || fail "PHYSICAL_TERMINAL_PREFLIGHT_MARKER"
  physical_terminal_preflight=true

  echo
  echo "=== INTERACTIVE CLEAN TUI ==="
  echo "Do not send a model prompt."
  echo "This TUI runs from the exact candidate checkout."
  echo "The AGENTS boundary is already machine-proved; human work is autocomplete observation only."
  echo "Confirm the target plugin skill is absent from autocomplete."
  echo "Do not type into Claude."
  echo "The supervisor waits for the normal composer, injects the exact non-submitting probe automatically, keeps the TUI open for a bounded observation window, then owns teardown."
  echo "If Claude shows trust/onboarding/security confirmation instead of the normal composer, do not interact; the harness fails closed."
  echo "Human work is observation only; no keypresses are required."
  echo
  (
    cd "$root"
    python3 "$root/scripts/release/claude-tty-supervisor.py" --probe-text "$probe_text" -- "$clroom" claude
  ) || fail "CLEAN_TUI_SUPERVISOR"
  clean_tui_supervised=true
  [[ "$before" == "$(fingerprint)" ]] || fail "PERSISTENT_CONFIG_CHANGED_CLEAN_INTERACTIVE"
  printf 'Clean TUI opened normally [y/N]: '
  read -r clean_answer
  [[ "$clean_answer" == "y" || "$clean_answer" == "Y" ]] || fail "CLEAN_TUI_NOT_CONFIRMED"
  printf 'Target plugin skill was absent in clean autocomplete [y/N]: '
  read -r clean_target_answer
  [[ "$clean_target_answer" == "y" || "$clean_target_answer" == "Y" ]] \
    || fail "CLEAN_TARGET_PLUGIN_PRESENT"
  clean_tui=true
  clean_target_plugin_absent=true

  echo
  echo "=== INTERACTIVE SELECTED-PLUGIN TUI ==="
  echo "Do not send a model prompt."
  echo "This TUI runs from the same exact candidate checkout."
  echo "The AGENTS boundary is already machine-proved; human work is autocomplete observation only."
  echo "Confirm the selected plugin skill is visible in autocomplete."
  echo "Confirm no additional sibling plugin became newly visible."
  echo "Confirm no plugin load errors are shown."
  echo "Do not type into Claude."
  echo "The supervisor waits for the normal composer, injects the exact non-submitting probe automatically, keeps the TUI open for a bounded observation window, then owns teardown."
  echo "If Claude shows trust/onboarding/security confirmation instead of the normal composer, do not interact; the harness fails closed."
  echo "Human work is observation only; no keypresses are required."
  echo
  (
    cd "$root"
    python3 "$root/scripts/release/claude-tty-supervisor.py" --probe-text "$probe_text" -- "$clroom" claude --with="plugin:$plugin_id"
  ) || fail "SELECTED_TUI_SUPERVISOR"
  selected_tui_supervised=true
  interactive_terminal_state_restored=true
  [[ "$before" == "$(fingerprint)" ]] || fail "PERSISTENT_CONFIG_CHANGED_SELECTED_INTERACTIVE"
  printf 'Selected TUI opened normally and selected plugin skill was visible [y/N]: '
  read -r selected_answer
  [[ "$selected_answer" == "y" || "$selected_answer" == "Y" ]] || fail "SELECTED_TUI_NOT_CONFIRMED"
  printf 'No additional sibling plugin became newly visible [y/N]: '
  read -r sibling_answer
  [[ "$sibling_answer" == "y" || "$sibling_answer" == "Y" ]] || fail "NEW_SIBLING_PLUGIN_NOT_CONFIRMED"
  printf 'No plugin load errors were shown [y/N]: '
  read -r plugin_errors_answer
  [[ "$plugin_errors_answer" == "y" || "$plugin_errors_answer" == "Y" ]] || fail "PLUGIN_ERRORS_NOT_CONFIRMED"
  printf 'No inference/model response appeared in either TUI [y/N]: '
  read -r no_prompt_answer
  [[ "$no_prompt_answer" == "y" || "$no_prompt_answer" == "Y" ]] \
    || fail "NO_MODEL_PROMPT_NOT_CONFIRMED"

  interactive=true
  selected_target_plugin_visible=true
  no_new_sibling_plugins=true
  selected_plugin_errors_absent=true
  no_model_prompt=true
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
python3 - "$evidence" "$phase" "$version" "$source_head" "$source_tree" "$reviewed_content_digest" "$artifact_sha" \
  "$plugin_id" "$plugin_info_preflight" "$clean_tui" "$clean_tui_supervised" "$selected_tui_supervised" \
  "$clean_target_plugin_absent" "$interactive" "$selected_target_plugin_visible" "$no_new_sibling_plugins" \
  "$selected_plugin_errors_absent" "$no_model_prompt" "$external_ancestor_agents_absent" \
  "$project_agents_retained" "$agents_boundary_probe" "$physical_terminal_preflight" \
  "$interactive_terminal_state_restored" "$claude_version_output" "$claude_version" "$claude_provider_sha" <<'PY'
import datetime, json, sys
(
    output, phase, version, source, source_tree, reviewed_content_digest, artifact_sha,
    plugin_id, plugin_info_preflight, clean_tui, clean_tui_supervised, selected_tui_supervised,
    clean_target_plugin_absent, interactive, selected_target_plugin_visible,
    no_new_sibling_plugins, selected_plugin_errors_absent,
    no_model_prompt, external_ancestor_agents_absent, project_agents_retained,
    agents_boundary_probe, physical_terminal_preflight, interactive_terminal_state_restored,
    claude_version_output, claude_version, claude_provider_sha,
) = sys.argv[1:]
record={
  "schema_version":"clroom.plugin-release-smoke.v5",
  "result":"PASS",
  "phase":phase,
  "release_version":version,
  "source_head":source,
  "source_tree":source_tree,
  "reviewed_content_digest":reviewed_content_digest,
  "evidence_binding":"content-addressed-runtime-v1",
  "artifact_sha256":artifact_sha,
  "platform":"macos-aarch64",
  "claude_version_output":claude_version_output,
  "claude_version":claude_version,
  "claude_provider_sha256":claude_provider_sha,
  "plugin_id":plugin_id,
  "plugin_info_preflight_passed":plugin_info_preflight=="true",
  "clean_tui_confirmed":clean_tui=="true",
  "clean_tui_supervised":clean_tui_supervised=="true",
  "selected_tui_supervised":selected_tui_supervised=="true",
  "interactive_human_bytes_forwarded":False,
  "interactive_submit_bytes_blocked_by_supervisor":True,
  "interactive_harness_owned_teardown":True,
  "physical_terminal_preflight_passed":physical_terminal_preflight=="true",
  "interactive_terminal_state_restored":interactive_terminal_state_restored=="true",
  "clean_target_plugin_absent_confirmed":clean_target_plugin_absent=="true",
  "selected_tui_confirmed":interactive=="true",
  "selected_target_plugin_visible_confirmed":selected_target_plugin_visible=="true",
  "no_new_sibling_plugins_confirmed":no_new_sibling_plugins=="true",
  "selected_plugin_errors_absent_confirmed":selected_plugin_errors_absent=="true",
  "persistent_config_unchanged":True,
  "automated_probe_prompt_supplied":False,
  "interactive_no_model_prompt_confirmed":no_model_prompt=="true",
  "external_ancestor_agents_absent_confirmed":external_ancestor_agents_absent=="true",
  "project_agents_retained_confirmed":project_agents_retained=="true",
  "external_ancestor_agents_sandbox_probe_passed":agents_boundary_probe=="true",
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
echo "MODEL_PROMPT_SENT=NO"
echo "PERSISTENT_CONFIG_UNCHANGED=YES"
echo "EVIDENCE_FILE=${evidence#$root/}"
