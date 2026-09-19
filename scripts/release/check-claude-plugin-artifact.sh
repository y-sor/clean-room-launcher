#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'CLAUDE_PLUGIN_ARTIFACT_BLOCKED:%s\n' "$1" >&2
  exit 1
}

[[ $# -eq 1 ]] || fail "USAGE"
artifact=$1
[[ "$(uname -s)" == Darwin ]] || fail "HOST_DARWIN_REQUIRED"
[[ "$(uname -m)" == arm64 ]] || fail "HOST_ARM64_REQUIRED"
[[ -f "$artifact" ]] || fail "ARTIFACT_MISSING"
command -v python3 >/dev/null 2>&1 || fail "PYTHON_REQUIRED"

root=$(mktemp -d "${TMPDIR:-/tmp}/clroom-plugin-artifact.XXXXXX")
cleanup() {
  rm -rf -- "$root"
}
trap cleanup EXIT HUP INT TERM

candidate="$root/clroom"
python3 - "$artifact" "$candidate" <<'PY'
import pathlib
import sys
import tarfile

archive, output = sys.argv[1:]
with tarfile.open(archive, "r:gz") as handle:
    members = [
        member for member in handle.getmembers()
        if member.isfile() and member.name.endswith("/bin/clroom")
    ]
    if len(members) != 1:
        raise SystemExit("expected exactly one bin/clroom")
    source = handle.extractfile(members[0])
    if source is None:
        raise SystemExit("cannot read bin/clroom")
    pathlib.Path(output).write_bytes(source.read())
PY
chmod 0755 "$candidate"

home="$root/home"
plugin="$home/.claude/plugins/cache/example/release-fixture/1.0.0"
mkdir -p "$plugin/.claude-plugin" "$plugin/skills/release-fixture" "$home/.claude/plugins" "$root/bin" "$root/project"
printf '%s\n' '{"name":"release-fixture","version":"1.0.0"}' > "$plugin/.claude-plugin/plugin.json"
printf '%s\n' '# Release fixture' > "$plugin/skills/release-fixture/SKILL.md"
python3 - "$home/.claude/plugins/installed_plugins.json" "$plugin" <<'PY'
import json
import pathlib
import sys
out, plugin = sys.argv[1:]
pathlib.Path(out).write_text(
    json.dumps({"plugins":{"release-fixture@example":[{"installPath":plugin}]}}) + "\n",
    encoding="utf-8",
)
PY

command -v clang >/dev/null 2>&1 || fail "CLANG_REQUIRED"
cat > "$root/fake-claude.c" <<'C'
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc >= 2 && strcmp(argv[1], "--version") == 0) {
        puts("2.1.273 (Claude Code)");
        return 0;
    }

    const char *plugin_root = NULL;
    for (int i = 1; i < argc; i++) {
        printf("CLROOM_FAKE_ARG=%s\n", argv[i]);
        if (i + 1 < argc && strcmp(argv[i], "--plugin-dir") == 0) {
            plugin_root = argv[i + 1];
        }
    }
    if (plugin_root == NULL) {
        puts("CLROOM_FAKE_WRITE=MISSING_PLUGIN_DIR");
        return 19;
    }

    char probe[4096];
    int written = snprintf(
        probe, sizeof(probe), "%s/CLROOM_RELEASE_WRITE_PROBE", plugin_root
    );
    if (written < 0 || (size_t)written >= sizeof(probe)) {
        return 21;
    }

    int fd = open(probe, O_WRONLY | O_CREAT | O_EXCL, 0600);
    if (fd >= 0) {
        close(fd);
        unlink(probe);
        puts("CLROOM_FAKE_WRITE=WRITABLE");
        return 20;
    }

    if (errno == EACCES || errno == EPERM) {
        puts("CLROOM_FAKE_WRITE=READ_ONLY");
        return 0;
    }

    printf("CLROOM_FAKE_WRITE=ERROR:%d\n", errno);
    return 22;
}
C
clang -O2 -Wall -Wextra -Werror "$root/fake-claude.c" -o "$root/bin/claude" \
  || fail "NATIVE_PROVIDER_BUILD"
chmod 0755 "$root/bin/claude"

set +e
HOME="$home" PATH="$root/bin:/usr/bin:/bin" \
  "$candidate" claude --with=plugin:release-fixture@example --help \
  >"$root/stdout.log" 2>"$root/stderr.log"
status=$?
set -e
if [[ $status -ne 0 ]]; then
  cat "$root/stderr.log" >&2
  cat "$root/stdout.log" >&2
  fail "SKILL_ONLY_LAUNCH_FAILED"
fi
grep -Fqx "CLROOM_FAKE_WRITE=READ_ONLY" "$root/stdout.log" \
  || fail "PLUGIN_ROOT_WRITE_POLICY"

canonical_plugin=$(cd "$plugin" && pwd -P)
python3 - "$root/stdout.log" "$canonical_plugin" <<'PY' || fail "ACTIVATION_ARGV"
import pathlib
import sys

lines = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
args = [
    line.removeprefix("CLROOM_FAKE_ARG=")
    for line in lines
    if line.startswith("CLROOM_FAKE_ARG=")
]
root = sys.argv[2]
pairs = [(args[i], args[i + 1]) for i in range(len(args) - 1)]
if pairs.count(("--plugin-dir", root)) != 1:
    raise SystemExit("expected exactly one exact --plugin-dir")
PY

# A hook-bearing bundle must be refused before the provider's actual launch.
printf '%s\n' '{"name":"release-fixture","version":"1.0.0","hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"echo nope"}]}]}}' > "$plugin/.claude-plugin/plugin.json"
set +e
HOME="$home" PATH="$root/bin:/usr/bin:/bin" \
  "$candidate" claude --with=plugin:release-fixture@example --help \
  >"$root/negative.stdout.log" 2>"$root/negative.stderr.log"
negative_status=$?
set -e
[[ $negative_status -ne 0 ]] || fail "HOOK_BUNDLE_UNEXPECTEDLY_ACCEPTED"
if grep -Fq "CLROOM_FAKE_ARG=" "$root/negative.stdout.log"; then
  fail "HOOK_BUNDLE_REACHED_PROVIDER"
fi

printf 'CLAUDE_PLUGIN_ARTIFACT_PASS provider=2.1.273 plugin=release-fixture@example\n'
