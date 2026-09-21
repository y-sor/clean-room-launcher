#!/usr/bin/env bash
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
usage() { echo "usage: $0 --provider NAME --executable PATH --expected-provider-version VERSION --candidate PATH --source-head SHA --version VERSION --output PATH" >&2; exit 2; }
provider= executable= expected_provider_version= candidate= source_head= release_version= output=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider) provider=${2:-}; shift 2;;
    --executable) executable=${2:-}; shift 2;;
    --expected-provider-version) expected_provider_version=${2:-}; shift 2;;
    --candidate) candidate=${2:-}; shift 2;;
    --source-head) source_head=${2:-}; shift 2;;
    --version) release_version=${2:-}; shift 2;;
    --output) output=${2:-}; shift 2;;
    *) usage;;
  esac
done
[[ $provider == codex || $provider == claude ]] || usage
[[ -x $executable && -x $candidate ]] || { echo "qualification executable missing" >&2; exit 2; }
[[ $source_head =~ ^[0-9a-f]{40,64}$ && $release_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && $expected_provider_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && -n $output ]] || usage
executable="$(cd "$(dirname "$executable")" && pwd -P)/$(basename "$executable")"
candidate="$(cd "$(dirname "$candidate")" && pwd -P)/$(basename "$candidate")"
provider_version=$($executable --version 2>/dev/null | sed -nE 's/.*([0-9]+\.[0-9]+\.[0-9]+).*/\1/p' | head -1)
candidate_digest=$(shasum -a 256 "$candidate" | awk '{print $1}')
provider_digest=$(shasum -a 256 "$executable" | awk '{print $1}')
target=$(rustc -vV | sed -n 's/^host: //p')
root=$(mktemp -d "${TMPDIR:-/tmp}/clroom-provider-qualification.XXXXXX")
cleanup() {
  chmod -R u+w "$root" 2>/dev/null || true
  rm -rf "$root"
}
trap cleanup EXIT
user_home="$root/user-home"
mkdir -p "$user_home/.codex" "$user_home/.claude" "$root/project"
printf '%s\n' 'not valid provider configuration' > "$user_home/.codex/config.toml"
printf '%s\n' '{"synthetic_global_context":"must-not-apply"}' > "$user_home/.claude/settings.json"
printf '%s\n' '{"OPENAI_API_KEY":"clroom-provider-qualification","tokens":null,"last_refresh":null}' > "$user_home/.codex/auth.json"
mkdir -p "$(dirname "$output")"
scope="real-provider-startup-no-model"
launch_path="clroom provider --help"
set +e
status=0
observed=false
repeat_observed=false
lifecycle_runs=1
if [[ $provider == codex ]]; then
  scope="real-provider-repeat-interactive-mcp-discovery-no-model"
  launch_path="clroom codex --with=plugin:standalone-mcp@clroom-fixture --no-alt-screen (PTY) x2 same HOME"
  lifecycle_runs=2
  fixture_log="$root/codex-mcp.log"
  fixture_plugin=$(python3 "$repo_root/scripts/release/codex-mcp-fixture.py" install \
    --codex-home "$user_home/.codex" --log "$fixture_log")
  status=$?
  observed_count=0
  if [[ $status -eq 0 ]]; then
    for lifecycle_run in 1 2; do
      python3 "$repo_root/scripts/release/codex-mcp-fixture.py" probe-provider \
        --candidate "$candidate" \
        --mode dropin \
        --project "$root/project" \
        --home "$user_home" \
        --provider "$executable" \
        --plugin-id standalone-mcp@clroom-fixture \
        --log "$fixture_log"
      run_status=$?
      if [[ $run_status -ne 0 ]]; then
        status=$run_status
        break
      fi
      observed_count=$((observed_count + 1))
    done
  fi
  if [[ $status -eq 0 && $observed_count -eq 2 ]]; then
    python3 "$repo_root/scripts/release/codex-mcp-fixture.py" probe-server \
      --server "$fixture_plugin/server.py"
    status=$?
  fi
  if [[ $observed_count -eq 2 && $status -eq 0 ]]; then
    observed=true
    repeat_observed=true
  fi
else
  python3 - "$candidate" "$root/project" "$user_home" "$(dirname "$executable")" <<'PY'
import os, subprocess, sys
candidate, project, home, provider_dir = sys.argv[1:]
env = {"PATH": provider_dir + ":/usr/bin:/bin", "HOME": home, "TMPDIR": os.environ.get("TMPDIR", "/tmp"), "TERM": "dumb"}
try:
    result = subprocess.run([candidate, "--help"], cwd=project, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
    raise SystemExit(result.returncode)
except subprocess.TimeoutExpired:
    raise SystemExit(124)
except OSError:
    raise SystemExit(125)
PY
  status=$?
  [[ $status -eq 0 ]] && observed=true
fi
set -e
pass=false
if [[ $status -eq 0 && $provider_version == "$expected_provider_version" && $observed == true ]]; then
  if [[ $provider != codex || $repeat_observed == true ]]; then
    pass=true
  fi
fi
exit_class=nonzero
[[ $status -eq 0 ]] && exit_class=success
[[ $provider == codex && $repeat_observed == true && $status -eq 0 ]] && exit_class=interactive-provider-repeat-mcp-qualified
python3 - "$output" "$provider" "$provider_version" "$provider_digest" "$candidate_digest" "$source_head" "$release_version" "$target" "$status" "$pass" "$scope" "$launch_path" "$observed" "$repeat_observed" "$lifecycle_runs" "$exit_class" <<'PY'
import json, sys
(
    out, provider, provider_version, provider_digest, candidate_digest,
    source_head, release_version, target, status, passed, scope, launch_path,
    observed, repeat_observed, lifecycle_runs, exit_class,
) = sys.argv[1:]
record = {
    "schema_version":"clroom.real-provider-qualification.v2",
    "qualification":"PASS" if passed == "true" else "FAIL",
    "scope":scope,
    "real_provider_executed":observed == "true",
    "repeat_provider_executed":repeat_observed == "true",
    "lifecycle_runs":int(lifecycle_runs),
    "fake_provider":False,
    "provider":provider,
    "provider_version":provider_version,
    "provider_digest":provider_digest,
    "clroom_source_head":source_head,
    "release_version":release_version,
    "target":target,
    "candidate_digest":candidate_digest,
    "launch_path":launch_path,
    "synthetic_ambient_config_present":True,
    "synthetic_ambient_config_applied":False if observed == "true" else None,
    "exit_class":exit_class,
}
with open(out, "w", encoding="utf-8") as handle:
    json.dump(record, handle, sort_keys=True, separators=(",", ":"))
    handle.write("\n")
if record["qualification"] != "PASS":
    raise SystemExit(1)
PY
printf 'REAL_PROVIDER_QUALIFICATION_%s provider=%s version=%s scope=%s\n' "$([[ $pass == true ]] && echo PASS || echo FAIL)" "$provider" "$provider_version" "$scope"
