#!/usr/bin/env bash
set -euo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
provisioner="$root/scripts/release/provision-provider-canaries.sh"
qualifier="$root/scripts/release/qualify-real-provider.sh"
pins="$root/scripts/release/provider-pins.sh"
pin_checker="$root/scripts/release/check-provider-pins.sh"
codex_smoke="$root/scripts/release/local-codex-plugin-activation-smoke.sh"
claude_smoke="$root/scripts/release/local-plugin-activation-smoke.sh"
codex_mcp_fixture="$root/scripts/release/codex-mcp-fixture.py"
tag_helper="$root/scripts/release/push-release-tag.sh"
codex_rehearsal_resolver="$root/scripts/release/resolve-codex-rehearsal-evidence.sh"
pretag_resolver="$root/scripts/release/resolve-pretag-stage.sh"
stage_release="$root/scripts/release/stage-release.sh"
stage_verifier="$root/scripts/release/verify-pretag-stage.py"
claude_stage_verifier="$root/scripts/release/verify-claude-stage-evidence.py"
post_tag_contract="$root/scripts/release/check-post-tag-contract.sh"
release_candidate="$root/.github/workflows/release-candidate.yml"
release="$root/.github/workflows/release.yml"
ci="$root/.github/workflows/ci.yml"

fail() {
  printf 'PROVIDER_CANARY_CONTRACT_BLOCKED:%s\n' "$1" >&2
  exit 1
}

for file in   "$provisioner" "$qualifier" "$pins" "$pin_checker"   "$codex_smoke" "$claude_smoke" "$codex_mcp_fixture"   "$tag_helper" "$codex_rehearsal_resolver" "$pretag_resolver"   "$stage_release" "$stage_verifier" "$claude_stage_verifier"   "$post_tag_contract" "$release_candidate" "$release" "$ci"
do
  [[ -f "$file" ]] || fail "FILE_MISSING:$(basename "$file")"
done

for needle in   'CODEX_VERSION='   'CLAUDE_VERSION='   'CODEX_SHA512='   'CODEX_PLATFORM_SHA512='   'CLAUDE_SHA512='   'CLAUDE_PLATFORM_SHA512='
do
  grep -Fq -- "$needle" "$pins" || fail "PIN_MISSING:$needle"
done
# shellcheck source=provider-pins.sh
source "$pins"
[[ "$CODEX_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "CODEX_VERSION"
[[ "$CLAUDE_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "CLAUDE_VERSION"

for needle in   "verify_latest '@openai/codex' \"\$CODEX_VERSION\""   "verify_latest '@anthropic-ai/claude-code' \"\$CLAUDE_VERSION\""   'verify_integrity "@openai/codex@$CODEX_VERSION"'   'verify_integrity "@openai/codex@$CODEX_VERSION-darwin-arm64"'   'verify_integrity "@anthropic-ai/claude-code@$CLAUDE_VERSION"'   'verify_integrity "@anthropic-ai/claude-code-darwin-arm64@$CLAUDE_VERSION"'   'PROVIDER_PIN_CHECK_PASS'
do
  grep -Fq -- "$needle" "$pin_checker" || fail "LATEST_OR_INTEGRITY_GATE_MISSING"
done

for needle in   'source "$root/scripts/release/provider-pins.sh"'   'bash "$root/scripts/release/check-provider-pins.sh"'   'aarch64-apple-darwin/bin/codex'   'claude_native="$claude_platform_root/claude"'   'cmp -s "$claude_native" "$claude_canary"'   'CLROOM_PROVIDER_CODEX=%s\n'   'CLROOM_PROVIDER_CLAUDE=%s\n'   'CLROOM_PROVIDER_CODEX_VERSION=%s\n'   'CLROOM_PROVIDER_CLAUDE_VERSION=%s\n'
do
  grep -Fq -- "$needle" "$provisioner" || fail "PIN_OR_LAYOUT_MISSING"
done

for needle in   '"$phase" == "rehearse" || "$phase" == "stage"'   '--artifact) artifact_input='   'STAGE_ARTIFACT_REQUIRED'   'HEAD_NOT_EXPECTED_CANDIDATE'   'review_path="reports/release/v${version}-review.json"'   '"evidence_binding": "content-addressed-runtime-v1"'
do
  grep -Fq -- "$needle" "$codex_smoke" || fail "CODEX_STAGE_SMOKE_MISSING:$needle"
done
for needle in   '"$phase" == "rehearse" || "$phase" == "stage"'   '--artifact) artifact_input='   'STAGE_ARTIFACT_REQUIRED'   'HEAD_NOT_EXPECTED_CANDIDATE'   'review_path="reports/release/v${version}-review.json"'   '"schema_version":"clroom.plugin-release-smoke.v3"'   'interactive_selected_tui_confirmed'
do
  grep -Fq -- "$needle" "$claude_smoke" || fail "CLAUDE_STAGE_SMOKE_MISSING:$needle"
done
for needle in   'PROVIDER_REGISTRY_FREEZE_REUSED=YES'   'if [[ "$phase" == "rehearse" ]]; then'
do
  grep -Fq -- "$needle" "$claude_smoke" || fail "CLAUDE_STAGE_FREEZE_CONTRACT:$needle"
done
grep -Fq -- '"plugin_id": "frontend-design@claude-plugins-official"' "$claude_stage_verifier"   || fail "CLAUDE_STAGE_PLUGIN_IDENTITY"

for smoke in "$codex_smoke" "$claude_smoke"; do
  for forbidden in     'IMMUTABLE_RELEASE_POLICY'     'gh release '     'gh attestation '     '"$phase" == "draft"'
  do
    if grep -Fq -- "$forbidden" "$smoke"; then
      fail "POST_TAG_SMOKE_RESIDUE:$forbidden"
    fi
  done
done

for needle in   '--fixture-standalone-mcp'   'plugin_id=standalone-mcp@clroom-fixture'   'expected_mcp=clroom_fixture'   'codex-mcp-fixture.py" probe-provider'   'codex-mcp-fixture.py" probe-server'   '"provider_mcp_initialize_observed": provider_mcp_initialize == "true"'   '"provider_mcp_tools_list_observed": provider_mcp_tools_list == "true"'   '"fixture_mcp_tool_call_passed": fixture_mcp_tool_call == "true"'   '"provider_state_lifecycle_closed": True'   '"post_runtime_clean_confirmed": post_runtime_clean == "true"'   'fail_from_stderr "SELECTED_MCP_RUNTIME"'
do
  grep -Fq -- "$needle" "$codex_smoke" || fail "CODEX_RUNTIME_CONTRACT_MISSING:$needle"
done

for needle in   'PROJECT_AGENTS_NOT_CONFIRMED'   'EXTERNAL_ANCESTOR_AGENTS_NOT_CONFIRMED'   'AGENTS_BOUNDARY_SANDBOX_PROBE=PASS'   'interactive_no_model_prompt_confirmed'   'project_agents_retained_confirmed'   'external_ancestor_agents_absent_confirmed'
do
  grep -Fq -- "$needle" "$claude_smoke" || fail "CLAUDE_TUI_BOUNDARY_MISSING:$needle"
done

for needle in   'Rehearse Codex runtime on exact PR candidate'   'GITHUB_TOKEN: ${{ github.token }}'   'local-codex-plugin-activation-smoke.sh rehearse'   '--fixture-standalone-mcp'   'Upload Codex pre-merge rehearsal evidence'
do
  grep -Fq -- "$needle" "$release_candidate" || fail "CODEX_PREMERGE_WORKFLOW_MISSING:$needle"
done
for needle in   'Release candidate readiness'   '.github/workflows/release-candidate.yml'   'event": "pull_request"'   'conclusion": "success"'   'candidate_tree'   'SUCCESSFUL_PR_RUN_WITH_MATCHING_TREE_NOT_FOUND'
do
  grep -Fq -- "$needle" "$codex_rehearsal_resolver" || fail "CODEX_REHEARSAL_RESOLVER_CONTRACT:$needle"
done

for needle in   'pretag-stage:'   'Rehearse/stage exact release bytes'   'source_sha="${{ github.event.pull_request.head.sha || github.sha }}"'   'bash scripts/release/stage-release.sh "$source_sha" "$RUNNER_TEMP/pretag-stage"'   'pretag-stage-v${{ needs.release-readiness.outputs.version }}-${{ github.event.pull_request.head.sha || github.sha }}'   'pretag-attestation-rehearsal:'   'Rehearse attestation mechanism before tag'   'PRETAG_ATTESTATION_REHEARSAL_PASS'
do
  grep -Fq -- "$needle" "$release_candidate" || fail "PRETAG_WORKFLOW_MISSING:$needle"
done
for needle in   'bash scripts/release/check-provider-pins.sh'   'packaging/build-artifacts.sh'   'qualify-real-provider.sh'   'local-codex-plugin-activation-smoke.sh stage'   '--artifact "$artifact"'   'render-release-notes.py'   'pretag-manifest.json'   'PRETAG_STAGE_PASS'
do
  grep -Fq -- "$needle" "$stage_release" || fail "PRETAG_STAGE_CONTRACT_MISSING:$needle"
done
for needle in   '"event": "push"'   '"head_branch": "main"'   '"head_sha": expected'   'SUCCESSFUL_MAIN_STAGE_RUN_NOT_FOUND'   'PRETAG_STAGE_RESOLVED'
do
  grep -Fq -- "$needle" "$pretag_resolver" || fail "PRETAG_RESOLVER_CONTRACT:$needle"
done

for needle in   'resolve-pretag-stage.sh'   'verify-pretag-stage.py'   'verify-claude-stage-evidence.py'   'IMMUTABLE_RELEASE_POLICY_PASS'   'ensure_release_absent ACTION_TIME'   'ensure_remote_tag_absent ACTION_TIME'   'verify_required_main_workflows ACTION_TIME'   'verify_tag_ruleset'   'PRETAG_STAGE_BINDING'   'PRETAG_STAGE_BINDING_ACTION_TIME'   'CLAUDE_STAGE_EVIDENCE'
do
  grep -Fq -- "$needle" "$tag_helper" || fail "TAG_PRETAG_CLOSURE_MISSING:$needle"
done
for forbidden in   'check-provider-pins.sh'   'resolve-codex-rehearsal-evidence.sh'   'CODEX_PROVIDER_DRIFT_ACTION_TIME'   'CLAUDE_PROVIDER_DRIFT_ACTION_TIME'   'local-codex-plugin-activation-smoke.sh'   'local-plugin-activation-smoke.sh'
do
  if grep -Fq -- "$forbidden" "$tag_helper"; then
    fail "TAG_REOPENS_BLOCKER:$forbidden"
  fi
done

bash "$post_tag_contract" "$release" "$ci" || fail "POST_TAG_PROMOTION_ONLY"
for needle in   'resolve-pretag-stage.sh'   'release-stage-v${{ steps.release.outputs.version }}-${{ github.sha }}'   'Bind accepted staged bytes to exact tag'   'Promote exact staged bytes to guarded Draft'   'DRAFT_PROMOTION_RECONCILE_PASS'
do
  grep -Fq -- "$needle" "$release" || fail "PROMOTION_WORKFLOW_MISSING:$needle"
done
if grep -Fq './scripts/release/provision-provider-canaries.sh' "$release"; then
  fail "POST_TAG_PROVIDER_PROVISIONING"
fi
grep -Fq './scripts/release/provision-provider-canaries.sh "$RUNNER_TEMP/clroom-providers" "$GITHUB_ENV"' "$release_candidate"   || fail "PRETAG_PROVIDER_PROVISIONER_MISSING"

for workflow in "$release_candidate" "$release"; do
  if grep -Eq 'npm[[:space:]]+install[[:space:]]' "$workflow"; then
    fail "WORKFLOW_NPM_INSTALL_FORBIDDEN"
  fi
done
if grep -Eq 'npm[[:space:]]+install[[:space:]]' "$provisioner"; then
  fail "PROVISIONER_NPM_INSTALL_FORBIDDEN"
fi

for script in   "$provisioner" "$pin_checker" "$pins" "$codex_smoke" "$claude_smoke"   "$tag_helper" "$codex_rehearsal_resolver" "$pretag_resolver"   "$stage_release" "$post_tag_contract" "$qualifier"
do
  bash -n "$script" || fail "SHELL_SYNTAX:$(basename "$script")"
done
python3 -m py_compile "$stage_verifier" "$claude_stage_verifier" || fail "PYTHON_SYNTAX"
python3 "$codex_mcp_fixture" --self-test || fail "CODEX_MCP_FIXTURE_SELF_TEST"

if [[ "$(uname -s)" == "Darwin" ]]; then
  tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-provider-contract.XXXXXX")
  cleanup() { rm -rf -- "$tmp"; }
  trap cleanup EXIT HUP INT TERM
  fake_provider="$tmp/codex"
  early_exit_candidate="$tmp/candidate"
  record="$tmp/record.json"
  stderr_log="$tmp/stderr.log"
  cat > "$fake_provider" <<SH
#!/usr/bin/env bash
if [[ ${1:-} == --version ]]; then
  printf 'codex-cli %s\n' '$CODEX_VERSION'
fi
exit 0
SH
  cat > "$early_exit_candidate" <<'SH'
#!/usr/bin/env bash
exit 0
SH
  chmod 0755 "$fake_provider" "$early_exit_candidate"
  manifest_version=$(python3 - <<'PY'
import tomllib
with open("Cargo.toml", "rb") as handle:
    print(tomllib.load(handle)["package"]["version"])
PY
)
  set +e
  "$qualifier"     --provider codex     --executable "$fake_provider"     --expected-provider-version "$CODEX_VERSION"     --candidate "$early_exit_candidate"     --source-head 0000000000000000000000000000000000000000     --version "$manifest_version"     --output "$record"     >"$tmp/stdout.log" 2>"$stderr_log"
  status=$?
  set -e
  [[ $status -eq 1 ]] || fail "EARLY_EXIT_STATUS"
  ! grep -Fq 'Traceback' "$stderr_log" || fail "EARLY_EXIT_TRACEBACK"
  [[ -f "$record" ]] || fail "EARLY_EXIT_RECORD_MISSING"
  python3 - "$record" <<'PY' || fail "EARLY_EXIT_RECORD_INVALID"
import json, sys
record = json.load(open(sys.argv[1], encoding="utf-8"))
if record.get("schema_version") != "clroom.real-provider-qualification.v2":
    raise SystemExit("schema")
if record.get("qualification") != "FAIL":
    raise SystemExit("qualification")
if record.get("real_provider_executed") is not False:
    raise SystemExit("provider-executed")
if record.get("repeat_provider_executed") is not False:
    raise SystemExit("repeat-provider-executed")
if record.get("lifecycle_runs") != 2:
    raise SystemExit("lifecycle")
PY
fi

printf 'PROVIDER_CANARY_CONTRACT_PASS\n'
