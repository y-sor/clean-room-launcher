#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
provisioner="$root/scripts/release/provision-provider-canaries.sh"
qualifier="$root/scripts/release/qualify-real-provider.sh"
pins="$root/scripts/release/provider-pins.sh"
pin_checker="$root/scripts/release/check-provider-pins.sh"
codex_smoke="$root/scripts/release/local-codex-plugin-activation-smoke.sh"
codex_mcp_fixture="$root/scripts/release/codex-mcp-fixture.py"
claude_smoke="$root/scripts/release/local-plugin-activation-smoke.sh"
tag_helper="$root/scripts/release/push-release-tag.sh"
codex_rehearsal_resolver="$root/scripts/release/resolve-codex-rehearsal-evidence.sh"
codex_draft_resolver="$root/scripts/release/resolve-codex-draft-evidence.sh"
release_candidate="$root/.github/workflows/release-candidate.yml"
release="$root/.github/workflows/release.yml"

fail() {
  printf 'PROVIDER_CANARY_CONTRACT_BLOCKED:%s\n' "$1" >&2
  exit 1
}

for file in "$provisioner" "$qualifier" "$pins" "$pin_checker" "$codex_smoke" "$codex_mcp_fixture" "$claude_smoke" "$tag_helper" "$codex_rehearsal_resolver" "$codex_draft_resolver" "$release_candidate" "$release"; do
  [[ -f "$file" ]] || fail "FILE_MISSING"
done

for needle in \
  'CODEX_VERSION=0.156.0' \
  'CLAUDE_VERSION=2.1.280' \
  'CODEX_SHA512=' \
  'CODEX_PLATFORM_SHA512=' \
  'CLAUDE_SHA512=' \
  'CLAUDE_PLATFORM_SHA512='; do
  grep -Fq -- "$needle" "$pins" || fail "PIN_MISSING"
done

for needle in \
  "verify_latest '@openai/codex' \"\$CODEX_VERSION\"" \
  "verify_latest '@anthropic-ai/claude-code' \"\$CLAUDE_VERSION\"" \
  'verify_integrity "@openai/codex@$CODEX_VERSION"' \
  'verify_integrity "@openai/codex@$CODEX_VERSION-darwin-arm64"' \
  'verify_integrity "@anthropic-ai/claude-code@$CLAUDE_VERSION"' \
  'verify_integrity "@anthropic-ai/claude-code-darwin-arm64@$CLAUDE_VERSION"' \
  'PROVIDER_PIN_CHECK_PASS'; do
  grep -Fq -- "$needle" "$pin_checker" || fail "LATEST_OR_INTEGRITY_GATE_MISSING"
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
  grep -Fq -- "$needle" "$provisioner" || fail "PIN_OR_LAYOUT_MISSING"
done


for needle in \
  'bash "$root/scripts/release/check-provider-pins.sh"' \
  '--fixture-standalone-mcp' \
  'plugin_id=standalone-mcp@clroom-fixture' \
  'expected_mcp=clroom_fixture' \
  '"$clroom" codex mcp list --json' \
  '"$clroom" codex --with="plugin:$plugin_id" mcp list --json' \
  '"schema_version": "clroom.codex-plugin-release-smoke.v4"' \
  '"clean_before_expected_mcp": False' \
  '"selected_expected_mcp": True' \
  '"selected_mcp_plugin_paths_rebased": True' \
  'SELECTED_MCP_PLUGIN_PATH_REBASE=PASS' \
  '"clean_after_expected_mcp": False' \
  '"ambient_config_and_plugin_tree_unchanged": True' \
  '"provider_mcp_initialize_observed": provider_mcp_initialize == "true"' \
  '"provider_mcp_tools_list_observed": provider_mcp_tools_list == "true"' \
  '"fixture_mcp_tool_call_passed": fixture_mcp_tool_call == "true"' \
  '"provider_state_lifecycle_closed": True' \
  '"real_provider_runtime_confirmed": runtime_confirmed == "true"' \
  '"expected_mcp_runtime_healthy_confirmed": runtime_mcp_healthy == "true"' \
  '"model_prompt_sent": False' \
  '"post_runtime_clean_confirmed": post_runtime_clean == "true"' \
  '"source_tree": source_tree' \
  '"reviewed_content_digest": reviewed_content_digest' \
  '"evidence_binding": "content-addressed-runtime-v1"' \
  'HEAD_NOT_EXPECTED_CANDIDATE' \
  'clroom-release-evidence' \
  'codex-mcp-fixture.py" probe-provider' \
  'CODEX_MCP_FIXTURE_BLOCKED:' \
  'selected-runtime.err' \
  'fail_from_stderr "SELECTED_MCP_RUNTIME"' \
  'codex-mcp-fixture.py" probe-server'; do
  grep -Fq -- "$needle" "$codex_smoke" || fail "CODEX_PLUGIN_SMOKE_CONTRACT_MISSING"
done

for needle in \
  '"schema_version":"clroom.plugin-release-smoke.v3"' \
  '"external_ancestor_agents_absent_confirmed": external_ancestor_agents_absent=="true"' \
  '"project_agents_retained_confirmed": project_agents_retained=="true"' \
  '"external_ancestor_agents_sandbox_probe_passed": agents_boundary_probe=="true"' \
  '"source_tree":source_tree' \
  '"reviewed_content_digest":reviewed_content_digest' \
  '"evidence_binding":"content-addressed-runtime-v1"' \
  'HEAD_NOT_EXPECTED_CANDIDATE' \
  'clroom-release-evidence' \
  'PROJECT_AGENTS_NOT_CONFIRMED' \
  'real-tui-workspace' \
  'chmod 0700 "$probe_tmp"' \
  'AGENTS_BOUNDARY_TMPDIR_NOT_PRIVATE' \
  'AGENTS_BOUNDARY_PROVIDER_EXECUTED=PASS' \
  'AGENTS_BOUNDARY_PROVIDER_NOT_EXECUTED' \
  'AGENTS_BOUNDARY_SANDBOX_PROBE=PASS' \
  'EXTERNAL_ANCESTOR_AGENTS_NOT_CONFIRMED'; do
  grep -Fq -- "$needle" "$claude_smoke" || fail "CLAUDE_INSTRUCTION_BOUNDARY_SMOKE_MISSING"
done

for needle in \
  'def seed_synthetic_project_trust(' \
  'init_argv.extend(["mcp", "list", "--json"])' \
  '".clroom-state-v2"' \
  'trust_level = "trusted"' \
  'if not initialized:' \
  'stderr=subprocess.PIPE' \
  'existing CLROOM-owned shadow trust seed failed' \
  'missing shadow marker did not require bootstrap' \
  'def same_executable_identity(' \
  'left_stat.st_dev == right_stat.st_dev' \
  'left_stat.st_ino == right_stat.st_ino' \
  'def process_argv(' \
  'KERN_PROCARGS2' \
  'def process_uses_provider(' \
  'same_executable_identity(path, provider)' \
  'same_executable_identity(argument, provider)' \
  'provider file identity rejected an equivalent path' \
  'provider file identity accepted unrelated executable' \
  'provider argv identity missed an interpreter-backed launcher' \
  'provider argv identity accepted unrelated executable' \
  'CODEX_MCP_PROVIDER_PROBE_PASS provider_process_observer=' \
  'Codex did not reach MCP initialize + tools/list' \
  'home_path = pathlib.Path(home)' \
  '"HOME": str(home_path)' \
  '"CODEX_HOME": str(home_path / ".codex")' \
  'CLROOM Codex shadow ownership marker missing' \
  'CLROOM Codex shadow ownership marker invalid'; do
  grep -Fq -- "$needle" "$codex_mcp_fixture" || fail "CODEX_SYNTHETIC_TRUST_CONTRACT_MISSING"
done

if grep -Fq -- 'raise RuntimeError("real Codex provider was not observed")' "$codex_mcp_fixture"; then
  fail "CODEX_PROCESS_OBSERVER_MUST_NOT_BE_ACCEPTANCE_GATE"
fi

for needle in \
  'scope="real-provider-repeat-interactive-mcp-discovery-no-model"' \
  'launch_path="clroom codex --with=plugin:standalone-mcp@clroom-fixture --no-alt-screen (PTY) x2 same HOME"' \
  'lifecycle_runs=2' \
  'for lifecycle_run in 1 2; do' \
  'codex-mcp-fixture.py" probe-provider' \
  'codex-mcp-fixture.py" probe-server' \
  'interactive-provider-repeat-mcp-qualified' \
  '"schema_version":"clroom.real-provider-qualification.v2"' \
  '"repeat_provider_executed":repeat_observed == "true"'; do
  grep -Fq -- "$needle" "$qualifier" || fail "CODEX_REPEAT_LIFECYCLE_CONTRACT_MISSING"
done

for needle in \
  '"schema_version": "clroom.plugin-release-smoke.v3"' \
  '"external_ancestor_agents_absent_confirmed": True' \
  '"project_agents_retained_confirmed": True' \
  '"external_ancestor_agents_sandbox_probe_passed": True' \
  '"source_tree": current_tree' \
  '"reviewed_content_digest": reviewed_content_digest' \
  '"evidence_binding": "content-addressed-runtime-v1"' \
  'rehearse-v${version}-${evidence_key}.json' \
  'REHEARSAL_CLAUDE_EVIDENCE_PASS'; do
  grep -Fq -- "$needle" "$tag_helper" || fail "CLAUDE_TAG_GATE_MISSING"
done

for needle in \
  'codex-rehearse-v${version}-${evidence_key}.json' \
  '"schema_version": "clroom.codex-plugin-release-smoke.v4"' \
  '"ambient_config_and_plugin_tree_unchanged": True' \
  '"provider_mcp_initialize_observed": True' \
  '"provider_mcp_tools_list_observed": True' \
  '"fixture_mcp_tool_call_passed": True' \
  '"provider_state_lifecycle_closed": True' \
  '"real_provider_runtime_confirmed": True' \
  '"expected_mcp_runtime_healthy_confirmed": True' \
  '"model_prompt_sent": False' \
  '"post_runtime_clean_confirmed": True' \
  '"source_tree": current_tree' \
  '"reviewed_content_digest": reviewed_content_digest' \
  '"evidence_binding": "content-addressed-runtime-v1"' \
  'TAG_GATE_BLOCKED:CODEX_REHEARSAL_FIXTURE_IDENTITY' \
  'REHEARSAL_CODEX_EVIDENCE_PASS' \
  'resolve-codex-rehearsal-evidence.sh' \
  'TAG_GATE_BLOCKED:CODEX_REHEARSAL_ARTIFACT' \
  'check-provider-pins.sh'; do
  grep -Fq -- "$needle" "$tag_helper" || fail "CODEX_TAG_GATE_MISSING"
done

for needle in \
  'Rehearse Codex runtime on exact PR candidate' \
  'GITHUB_TOKEN: ${{ github.token }}' \
  'local-codex-plugin-activation-smoke.sh rehearse' \
  '--fixture-standalone-mcp' \
  'codex-rehearsal-v${CLROOM_RELEASE_VERSION}-${digest}' \
  'Upload Codex pre-merge rehearsal evidence'; do
  grep -Fq -- "$needle" "$release_candidate" || fail "CODEX_PREMERGE_WORKFLOW_MISSING"
done

for needle in \
  'verify-codex-draft:' \
  'Verify Codex plugin runtime against Draft assets' \
  'local-codex-plugin-activation-smoke.sh draft' \
  'codex-draft-${GITHUB_REF_NAME}-${GITHUB_SHA}' \
  'Upload Codex Draft evidence'; do
  grep -Fq -- "$needle" "$release" || fail "CODEX_DRAFT_WORKFLOW_MISSING"
done

for needle in \
  'Release candidate readiness' \
  '.github/workflows/release-candidate.yml' \
  'event": "pull_request"' \
  'conclusion": "success"' \
  'git/commits/$artifact_head' \
  'candidate_tree' \
  'SUCCESSFUL_PR_RUN_WITH_MATCHING_TREE_NOT_FOUND' \
  'CODEX_REHEARSAL_EVIDENCE_RESOLVED'; do
  grep -Fq -- "$needle" "$codex_rehearsal_resolver" || fail "CODEX_REHEARSAL_RESOLVER_CONTRACT"
done

for needle in \
  '"name": "Release"' \
  '.github/workflows/release.yml' \
  '"event": "push"' \
  'CODEX_DRAFT_EVIDENCE_RESOLVED'; do
  grep -Fq -- "$needle" "$codex_draft_resolver" || fail "CODEX_DRAFT_RESOLVER_CONTRACT"
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
bash -n "$codex_rehearsal_resolver" || fail "CODEX_REHEARSAL_RESOLVER_SYNTAX"
bash -n "$codex_draft_resolver" || fail "CODEX_DRAFT_RESOLVER_SYNTAX"
bash -n "$qualifier" || fail "QUALIFIER_SYNTAX"
python3 "$codex_mcp_fixture" --self-test || fail "CODEX_MCP_FIXTURE_SELF_TEST"

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
  printf 'codex-cli 0.156.0\n'
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
    --expected-provider-version 0.156.0 \
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
