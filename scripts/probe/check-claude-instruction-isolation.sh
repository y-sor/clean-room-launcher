#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'CLAUDE_INSTRUCTION_ISOLATION_BLOCKED:%s\n' "$1" >&2
  exit 1
}

[[ $# -eq 1 ]] || fail "USAGE"
candidate=$1
[[ -x "$candidate" ]] || fail "CANDIDATE_MISSING"
candidate="$(cd "$(dirname "$candidate")" && pwd -P)/$(basename "$candidate")"

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
source "$root/scripts/release/provider-pins.sh"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-claude-instruction-probe.XXXXXX")
cleanup() { rm -rf -- "$tmp"; }
trap cleanup EXIT HUP INT TERM

home="$tmp/home"
workspace="$home/workspace"
repo="$workspace/repo"
project="$repo/subdir"
fake_bin="$tmp/bin"
mkdir -p "$home/.claude/skills" "$workspace/.claude" "$repo/.claude" "$repo/.git" "$project" "$fake_bin"

printf 'ambient-home\n' >"$home/AGENTS.md"
printf 'ambient-workspace\n' >"$workspace/AGENTS.md"
printf 'ambient-workspace-claude\n' >"$workspace/.claude/AGENTS.md"
printf 'repo\n' >"$repo/AGENTS.md"
printf 'repo-claude\n' >"$repo/.claude/AGENTS.md"
printf 'project\n' >"$project/AGENTS.md"
printf '{"hasCompletedOnboarding":true}\n' >"$home/.claude.json"

cat >"$fake_bin/claude" <<SH
#!/bin/sh
if [ "${1:-}" = "--version" ]; then
  printf '%s\n' "$CLAUDE_VERSION"
  exit 0
fi
[ ! -r "$HOME/AGENTS.md" ] || exit 81
[ ! -r "$HOME/workspace/AGENTS.md" ] || exit 82
[ ! -r "$HOME/workspace/.claude/AGENTS.md" ] || exit 83
[ -r "$PWD/../AGENTS.md" ] || exit 84
[ -r "$PWD/../.claude/AGENTS.md" ] || exit 85
[ -r "$PWD/AGENTS.md" ] || exit 86
exit 0
SH
chmod 0755 "$fake_bin/claude"

set +e
(
  cd "$project"
  HOME="$home" PATH="$fake_bin:/usr/bin:/bin" TMPDIR="$tmp" TERM=dumb "$candidate" --version
) >"$tmp/stdout.log" 2>"$tmp/stderr.log"
status=$?
set -e

[[ $status -eq 0 ]] || fail "BOUNDARY"
printf 'CLAUDE_INSTRUCTION_ISOLATION_PASS\n'
