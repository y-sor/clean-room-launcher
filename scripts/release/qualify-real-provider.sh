#!/usr/bin/env bash
set -euo pipefail
usage() { echo "usage: $0 --provider NAME --executable PATH --candidate PATH --source-head SHA --version VERSION --output PATH" >&2; exit 2; }
provider= executable= candidate= source_head= release_version= output=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --provider) provider=${2:-}; shift 2;;
    --executable) executable=${2:-}; shift 2;;
    --candidate) candidate=${2:-}; shift 2;;
    --source-head) source_head=${2:-}; shift 2;;
    --version) release_version=${2:-}; shift 2;;
    --output) output=${2:-}; shift 2;;
    *) usage;;
  esac
done
[[ $provider == codex || $provider == claude ]] || usage
[[ -x $executable && -x $candidate ]] || { echo "qualification executable missing" >&2; exit 2; }
[[ $source_head =~ ^[0-9a-f]{40,64}$ && $release_version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ && -n $output ]] || usage
executable="$(cd "$(dirname "$executable")" && pwd -P)/$(basename "$executable")"
candidate="$(cd "$(dirname "$candidate")" && pwd -P)/$(basename "$candidate")"
provider_version=$($executable --version 2>/dev/null | sed -nE 's/.*([0-9]+\.[0-9]+\.[0-9]+).*/\1/p' | head -1)
root_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
expected_provider_version=$(python3 - "$root_dir/release/qualification.json" "$provider" <<'PY'
import json
import sys
path, provider = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
print(data["providers"][provider]["clean_exact"])
PY
)
candidate_digest=$(shasum -a 256 "$candidate" | awk '{print $1}')
provider_digest=$(shasum -a 256 "$executable" | awk '{print $1}')
target=$(rustc -vV | sed -n 's/^host: //p')
root=$(mktemp -d "${TMPDIR:-/tmp}/clroom-provider-qualification.XXXXXX")
trap 'rm -rf "$root"' EXIT
user_home="$root/user-home"
mkdir -p "$user_home/.codex" "$user_home/.claude" "$root/project"
printf '%s\n' 'not valid provider configuration' > "$user_home/.codex/config.toml"
printf '%s\n' '{"synthetic_global_context":"must-not-apply"}' > "$user_home/.claude/settings.json"
printf '%s\n' '{}' > "$user_home/.codex/auth.json"
mkdir -p "$(dirname "$output")"
scope="real-provider-startup-no-model"
launch_path="clroom provider --help"
set +e
if [[ $provider == codex ]]; then
  scope="real-provider-interactive-startup-no-model"
  launch_path="clroom codex --no-alt-screen (PTY)"
  observation="$root/provider-observed"
  python3 - "$candidate" "$root/project" "$user_home" "$(dirname "$executable")" "$executable" "$observation" <<'PY'
import ctypes, os, pty, signal, subprocess, sys, time
candidate, project, home, provider_dir, provider, observation_file = sys.argv[1:]
provider = os.path.realpath(provider)
def process_path(pid):
    if sys.platform != "darwin":
        return None
    library = ctypes.CDLL("/usr/lib/libproc.dylib")
    buffer = ctypes.create_string_buffer(4096)
    library.proc_pidpath.restype = ctypes.c_int
    if library.proc_pidpath(int(pid), buffer, len(buffer)) <= 0:
        return None
    return os.path.realpath(os.fsdecode(buffer.value))
def provider_in_tree(root_pid):
    try:
        rows = subprocess.check_output(["/bin/ps", "-axo", "pid=,ppid=,pgid="], text=True)
    except (OSError, subprocess.SubprocessError):
        return False
    processes = {}
    for row in rows.splitlines():
        fields = row.split()
        if len(fields) != 3:
            continue
        try:
            processes[int(fields[0])] = (int(fields[1]), int(fields[2]))
        except ValueError:
            continue
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for child, (parent, _group) in processes.items():
            if parent in descendants and child not in descendants:
                descendants.add(child)
                changed = True
    group = processes.get(root_pid, (None, root_pid))[1]
    if group is not None:
        descendants.update(
            pid for pid, (_parent, process_group) in processes.items()
            if process_group == group
        )
    for pid in descendants:
        if process_path(pid) == provider:
            return True
    return False
pid, fd = pty.fork()
if pid == 0:
    env = {"PATH": provider_dir + ":/usr/bin:/bin", "HOME": home, "TMPDIR": os.environ.get("TMPDIR", "/tmp"), "TERM": "dumb", "CODEX_HOME": home + "/.codex"}
    os.chdir(project)
    os.execve(candidate, [candidate, "--no-alt-screen"], env)
provider_observed = False
def finish():
    with open(observation_file, "w", encoding="ascii") as handle:
        handle.write("YES\n" if provider_observed else "NO\n")
    raise SystemExit(0 if provider_observed else 1)
deadline = time.monotonic() + 5.0
reaped = False
while time.monotonic() < deadline:
    try:
        waited, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        reaped = True
        break
    if waited:
        reaped = True
        break
    provider_observed = provider_observed or provider_in_tree(pid)
    time.sleep(0.05)
if reaped:
    finish()
try:
    os.killpg(pid, signal.SIGINT)
except (ProcessLookupError, PermissionError):
    pass
for _ in range(40):
    try:
        waited, _ = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        finish()
    if waited:
        finish()
    provider_observed = provider_observed or provider_in_tree(pid)
    time.sleep(0.05)
try:
    os.killpg(pid, signal.SIGKILL)
except (ProcessLookupError, PermissionError):
    pass
try:
    os.waitpid(pid, 0)
except ChildProcessError:
    pass
finish()
PY
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
fi
status=$?
set -e
pass=false
observed=false
[[ -f ${observation:-} ]] && [[ $(sed -n '1p' "$observation") == YES ]] && observed=true
[[ $provider == claude && $status -eq 0 ]] && observed=true
[[ $status -eq 0 && $provider_version == "$expected_provider_version" && $observed == true ]] && pass=true
exit_class=nonzero
[[ $status -eq 0 ]] && exit_class=success
[[ $provider == codex && $observed == true && $status -eq 0 ]] && exit_class=interactive-provider-observed
python3 - "$output" "$provider" "$provider_version" "$provider_digest" "$candidate_digest" "$source_head" "$release_version" "$target" "$status" "$pass" "$scope" "$launch_path" "$observed" "$exit_class" <<'PY'
import json, sys
out, provider, provider_version, provider_digest, candidate_digest, source_head, release_version, target, status, passed, scope, launch_path, observed, exit_class = sys.argv[1:]
record = {"schema_version":"clroom.real-provider-qualification.v1", "qualification":"PASS" if passed == "true" else "FAIL", "scope":scope, "real_provider_executed":observed == "true", "fake_provider":False, "provider":provider, "provider_version":provider_version, "provider_digest":provider_digest, "clroom_source_head":source_head, "release_version":release_version, "target":target, "candidate_digest":candidate_digest, "launch_path":launch_path, "synthetic_ambient_config_present":True, "synthetic_ambient_config_applied":False if observed == "true" else None, "exit_class":exit_class}
with open(out, "w", encoding="utf-8") as handle:
    json.dump(record, handle, sort_keys=True, separators=(",", ":")); handle.write("\n")
if record["qualification"] != "PASS": raise SystemExit(1)
PY
printf 'REAL_PROVIDER_QUALIFICATION_%s provider=%s version=%s scope=%s\n' "$([[ $pass == true ]] && echo PASS || echo FAIL)" "$provider" "$provider_version" "$scope"
