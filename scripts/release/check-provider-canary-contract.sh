#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
provisioner="$root/scripts/release/provision-provider-canaries.sh"
qualifier="$root/scripts/release/qualify-real-provider.sh"
release_candidate="$root/.github/workflows/release-candidate.yml"
release="$root/.github/workflows/release.yml"
pins="$root/release/qualification.json"
version_sync="$root/scripts/release/check-provider-version-sync.py"

fail() {
  printf 'PROVIDER_CANARY_CONTRACT_BLOCKED:%s\n' "$1" >&2
  exit 1
}

for file in "$provisioner" "$qualifier" "$release_candidate" "$release" "$pins" "$version_sync"; do
  [[ -f "$file" ]] || fail "FILE_MISSING"
done

read -r codex_pin claude_pin < <(
  python3 - "$pins" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    data = json.load(handle)
print(
    data["providers"]["codex"]["clean_exact"],
    data["providers"]["claude"]["clean_exact"],
)
PY
) || fail "PIN_SOURCE_INVALID"

python3 "$version_sync" >/dev/null || fail "VERSION_SYNC"

for needle in \
  "@openai/codex@$codex_pin" \
  "@openai/codex@$codex_pin-darwin-arm64" \
  "@anthropic-ai/claude-code@$claude_pin" \
  "@anthropic-ai/claude-code-darwin-arm64@$claude_pin" \
  'FV/x1OHXYv/ifjf3mXj9ThTTAWcUZN6cGIRQRhRxkKNOPuImu1WW0c8ev1vUkE9XGH90dEnYG1tBjIkxRikg0w==' \
  'HP/vJCH/t2hB9Kg6hotN9UglClJ6/z584fal5lEP14C9gNAgAQS4/kTQC7l5V+BA3TqwDPwINSjul28cX8AYXg==' \
  'sOwHBM69H8Zka3/D3rc2VNNemPYNlgfYTdhsoqPoXZdK5KcKQlzoue4asJ2RVc+tGb/Pz1qxjVV9nVJQ87W7Ng==' \
  'l3CI1gPSCGkWNbAnX66SbDF4uFBecCCLu9FLN43JSbMMds5cb6tjOTBMSTr1ydZRZALW9AC/PYabtQOgXIbK5Q==' \
  'aarch64-apple-darwin/bin/codex' \
  'claude_platform_root="$provider_root/claude-platform/package"' \
  'claude_native="$claude_platform_root/claude"' \
  'claude_canary="$provider_root/bin/claude"' \
  'cmp -s "$claude_native" "$claude_canary"' \
  'CLROOM_PROVIDER_CODEX=%s\n' \
  '"$codex_native" >> "$env_file"' \
  'CLROOM_PROVIDER_CLAUDE=%s\n' \
  '"$claude_canary" >> "$env_file"'; do
  grep -Fq "$needle" "$provisioner" || fail "PIN_OR_LAYOUT_MISSING"
done

for workflow in "$release_candidate" "$release"; do
  grep -Fq './scripts/release/provision-provider-canaries.sh "$RUNNER_TEMP/clroom-providers" "$GITHUB_ENV"' "$workflow" \
    || fail "WORKFLOW_PROVISIONER_MISSING"
  if grep -Eq 'npm[[:space:]]+install[[:space:]]' "$workflow"; then
    fail "WORKFLOW_NPM_INSTALL_FORBIDDEN"
  fi
done

for needle in \
  '.qualification-extract' \
  'tar -xzf "$artifact"' \
  'candidate_dir="$archive_root/bin"' \
  'clroom-codex' \
  'clroom-claude'; do
  grep -Fq "$needle" "$root/scripts/release/readiness.sh" || fail "READINESS_ARTIFACT_BINDING_MISSING"
done

for needle in \
  'qualification_extract="$RUNNER_TEMP/clroom-release-archive"' \
  'tar -xzf "$artifact" -C "$qualification_extract"' \
  'candidate_dir="$archive_root/bin"' \
  '--candidate "$candidate_dir/clroom-codex"' \
  '--candidate "$candidate_dir/clroom-claude"'; do
  grep -Fq -- "$needle" "$release" || fail "TAG_WORKFLOW_ARTIFACT_BINDING_MISSING"
done

if grep -Fq 'target/aarch64-apple-darwin/release/clroom-codex' "$release" \
  || grep -Fq 'target/aarch64-apple-darwin/release/clroom-claude' "$release"; then
  fail "TAG_WORKFLOW_SIBLING_BUILD_QUALIFICATION_FORBIDDEN"
fi

if grep -Eq 'npm[[:space:]]+install[[:space:]]' "$provisioner"; then
  fail "PROVISIONER_NPM_INSTALL_FORBIDDEN"
fi

bash -n "$provisioner" || fail "PROVISIONER_SYNTAX"
bash -n "$qualifier" || fail "QUALIFIER_SYNTAX"

if [[ "$(uname -s)" == "Darwin" ]]; then
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-provider-contract.XXXXXX")
  cleanup() {
    rm -rf -- "$tmp"
  }
  trap cleanup EXIT HUP INT TERM

  fake_provider="$tmp/codex"
  early_exit_candidate="$tmp/candidate"
  record="$tmp/record.json"
  stderr_log="$tmp/stderr.log"

  cat > "$fake_provider" <<SH
#!/usr/bin/env bash
if [[ \${1:-} == --version ]]; then
  printf 'codex-cli %s\\n' '$codex_pin'
fi
exit 0
SH
  cat > "$early_exit_candidate" <<'SH'
#!/usr/bin/env bash
exit 0
SH
  chmod 0755 "$fake_provider" "$early_exit_candidate"

  set +e
  "$qualifier" \
    --provider codex \
    --executable "$fake_provider" \
    --candidate "$early_exit_candidate" \
    --source-head 0000000000000000000000000000000000000000 \
    --version 0.4.0 \
    --output "$record" \
    >"$tmp/stdout.log" 2>"$stderr_log"
  status=$?
  set -e

  [[ $status -eq 1 ]] || fail "EARLY_EXIT_STATUS"
  if grep -Fq 'Traceback' "$stderr_log"; then
    fail "EARLY_EXIT_TRACEBACK"
  fi
  [[ -f "$record" ]] || fail "EARLY_EXIT_RECORD_MISSING"
  python3 - "$record" <<'PY' || fail "EARLY_EXIT_RECORD_INVALID"
import json
import sys

with open(sys.argv[1], encoding="utf-8") as handle:
    record = json.load(handle)
if record.get("qualification") != "FAIL":
    raise SystemExit("early-exit candidate must fail qualification")
if record.get("real_provider_executed") is not False:
    raise SystemExit("early-exit candidate must not claim provider execution")
PY
fi

printf 'PROVIDER_CANARY_CONTRACT_PASS\n'
