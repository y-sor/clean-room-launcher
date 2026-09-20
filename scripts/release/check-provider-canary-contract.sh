#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
provisioner="$root/scripts/release/provision-provider-canaries.sh"
qualifier="$root/scripts/release/qualify-real-provider.sh"
pins="$root/scripts/release/provider-pins.sh"
pin_checker="$root/scripts/release/check-provider-pins.sh"
codex_smoke="$root/scripts/release/local-codex-plugin-activation-smoke.sh"
claude_smoke="$root/scripts/release/local-plugin-activation-smoke.sh"
tag_helper="$root/scripts/release/push-release-tag.sh"
release_candidate="$root/.github/workflows/release-candidate.yml"
release="$root/.github/workflows/release.yml"

fail() {
  printf 'PROVIDER_CANARY_CONTRACT_BLOCKED:%s\n' "$1" >&2
  exit 1
}

for file in "$provisioner" "$qualifier" "$pins" "$pin_checker" "$codex_smoke" "$claude_smoke" "$tag_helper" "$release_candidate" "$release"; do
  [[ -f "$file" ]] || fail "FILE_MISSING"
done

for needle in \
  'CODEX_VERSION=0.155.1' \
  'CLAUDE_VERSION=2.1.278' \
  'CODEX_SHA512=' \
  'CODEX_PLATFORM_SHA512=' \
  'CLAUDE_SHA512=' \
  'CLAUDE_PLATFORM_SHA512='; do
  grep -Fq "$needle" "$pins" || fail "PIN_MISSING"
done

for needle in \
  "verify_latest '@openai/codex' \"\$CODEX_VERSION\"" \
  "verify_latest '@anthropic-ai/claude-code' \"\$CLAUDE_VERSION\"" \
  'verify_integrity "@openai/codex@$CODEX_VERSION"' \
  'verify_integrity "@openai/codex@$CODEX_VERSION-darwin-arm64"' \
  'verify_integrity "@anthropic-ai/claude-code@$CLAUDE_VERSION"' \
  'verify_integrity "@anthropic-ai/claude-code-darwin-arm64@$CLAUDE_VERSION"' \
  'PROVIDER_PIN_CHECK_PASS'; do
  grep -Fq "$needle" "$pin_checker" || fail "LATEST_OR_INTEGRITY_GATE_MISSING"
done

for needle in \
  'source "$root/scripts/release/provider-pins.sh"' \
  'bash "$root/scripts/release/check-provider-pins.sh"' \
  'aarch64-apple-darwin/bin/codex' \
  'claude_platform_root="$provider_root/claude-platform/package"' \
  'claude_native="$claude_platform_root/claude"' \
  'claude_canary="$provider_root/bin/claude"' \
  'cmp -s "$claude_native" "$claude_canary"' \
  'CLROOM_PROVIDER_CODEX=%s\n' \
  'CLROOM_PROVIDER_CLAUDE=%s\n' \
  'CLROOM_PROVIDER_CODEX_VERSION=%s\n' \
  'CLROOM_PROVIDER_CLAUDE_VERSION=%s\n'; do
  grep -Fq "$needle" "$provisioner" || fail "PIN_OR_LAYOUT_MISSING"
done


for needle in \
  'bash "$root/scripts/release/check-provider-pins.sh"' \
  '[[ "$codex_version" == "$CODEX_VERSION" ]]' \
  '"$clroom" codex mcp list --json' \
  '"$clroom" codex --with="plugin:$plugin_id" mcp list --json' \
  '"schema_version": "clroom.codex-plugin-release-smoke.v2"' \
  '"clean_before_expected_mcp": False' \
  '"selected_expected_mcp": True' \
  '"clean_after_expected_mcp": False' \
  '"ambient_config_and_plugin_tree_unchanged": True' \
  '"provider_state_lifecycle_closed": True' \
  '"post_interactive_clean_confirmed": post_interactive_clean == "true"'; do
  grep -Fq "$needle" "$codex_smoke" || fail "CODEX_PLUGIN_SMOKE_CONTRACT_MISSING"
done

for needle in \
  '"schema_version":"clroom.plugin-release-smoke.v2"' \
  '"external_ancestor_agents_absent_confirmed": external_ancestor_agents_absent=="true"' \
  'EXTERNAL_ANCESTOR_AGENTS_NOT_CONFIRMED'; do
  grep -Fq "$needle" "$claude_smoke" || fail "CLAUDE_INSTRUCTION_BOUNDARY_SMOKE_MISSING"
done

for needle in \
  'scope="real-provider-repeat-interactive-startup-no-model"' \
  'launch_path="clroom codex --no-alt-screen (PTY) x2 same HOME"' \
  'lifecycle_runs=2' \
  'for lifecycle_run in 1 2; do' \
  '"schema_version":"clroom.real-provider-qualification.v2"' \
  '"repeat_provider_executed":repeat_observed == "true"'; do
  grep -Fq "$needle" "$qualifier" || fail "CODEX_REPEAT_LIFECYCLE_CONTRACT_MISSING"
done

for needle in \
  '"schema_version": "clroom.plugin-release-smoke.v2"' \
  '"external_ancestor_agents_absent_confirmed": True' \
  'PRETAG_CLAUDE_EVIDENCE_PASS'; do
  grep -Fq "$needle" "$tag_helper" || fail "CLAUDE_TAG_GATE_MISSING"
done

for needle in \
  'codex-pretag-v${version}-${expected:0:12}.json' \
  '"schema_version": "clroom.codex-plugin-release-smoke.v2"' \
  '"ambient_config_and_plugin_tree_unchanged": True' \
  '"provider_state_lifecycle_closed": True' \
  '"post_interactive_clean_confirmed": True' \
  'PRETAG_CODEX_EVIDENCE_PASS' \
  'TAG_GATE_BLOCKED:CODEX_PROVIDER_DRIFT_ACTION_TIME' \
  'TAG_GATE_BLOCKED:CODEX_PROVIDER_BYTES_DRIFT_ACTION_TIME'; do
  grep -Fq "$needle" "$tag_helper" || fail "CODEX_TAG_GATE_MISSING"
done

for workflow in "$release_candidate" "$release"; do
  grep -Fq './scripts/release/provision-provider-canaries.sh "$RUNNER_TEMP/clroom-providers" "$GITHUB_ENV"' "$workflow" \
    || fail "WORKFLOW_PROVISIONER_MISSING"
  if grep -Eq 'npm[[:space:]]+install[[:space:]]' "$workflow"; then
    fail "WORKFLOW_NPM_INSTALL_FORBIDDEN"
  fi
done

if grep -Eq 'npm[[:space:]]+install[[:space:]]' "$provisioner"; then
  fail "PROVISIONER_NPM_INSTALL_FORBIDDEN"
fi

bash -n "$provisioner" || fail "PROVISIONER_SYNTAX"
bash -n "$pin_checker" || fail "PIN_CHECKER_SYNTAX"
bash -n "$pins" || fail "PINS_SYNTAX"
bash -n "$codex_smoke" || fail "CODEX_SMOKE_SYNTAX"
bash -n "$claude_smoke" || fail "CLAUDE_SMOKE_SYNTAX"
bash -n "$tag_helper" || fail "TAG_HELPER_SYNTAX"
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

  cat > "$fake_provider" <<'SH'
#!/usr/bin/env bash
if [[ ${1:-} == --version ]]; then
  printf 'codex-cli 0.155.1\n'
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
    --expected-provider-version 0.155.1 \
    --candidate "$early_exit_candidate" \
    --source-head 0000000000000000000000000000000000000000 \
    --version 0.4.2 \
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
if record.get("schema_version") != "clroom.real-provider-qualification.v2":
    raise SystemExit("early-exit evidence schema must be lifecycle-aware")
if record.get("qualification") != "FAIL":
    raise SystemExit("early-exit candidate must fail qualification")
if record.get("real_provider_executed") is not False:
    raise SystemExit("early-exit candidate must not claim provider execution")
if record.get("repeat_provider_executed") is not False:
    raise SystemExit("early-exit candidate must not claim repeat provider execution")
if record.get("lifecycle_runs") != 2:
    raise SystemExit("Codex qualification must retain the two-run lifecycle contract")
PY
fi

printf 'PROVIDER_CANARY_CONTRACT_PASS\n'
