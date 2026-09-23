#!/usr/bin/env bash
set -euo pipefail
release_workflow=${1:-.github/workflows/release.yml}
candidate_workflow=${2:-.github/workflows/release-candidate.yml}
fail(){ printf 'RELEASE_ATTESTATION_CONTRACT_BLOCKED:%s\n' "$1" >&2; exit 1; }
[[ -f "$release_workflow" ]] || fail RELEASE_WORKFLOW_MISSING
[[ -f "$candidate_workflow" ]] || fail CANDIDATE_WORKFLOW_MISSING
pin='uses: actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6 # v4.2.2'
grep -Fq -- "$pin" "$candidate_workflow" || fail PRETAG_ATTEST_ACTION_PIN
grep -Fq -- "$pin" "$release_workflow" || fail TAG_ATTEST_ACTION_PIN
grep -Fq -- 'subject-checksums: ${{ env.CLROOM_STAGE_DIR }}/SHA256SUMS' "$candidate_workflow" || fail PRETAG_PROVENANCE_SUBJECTS
grep -Fq -- 'subject-checksums: release-stage/SHA256SUMS' "$release_workflow" || fail TAG_PROVENANCE_SUBJECTS
grep -Fq -- '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release-candidate.yml"' "$candidate_workflow" || fail PRETAG_SIGNER
grep -Fq -- '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release.yml"' "$release_workflow" || fail TAG_SIGNER
grep -Fq -- 'gh release upload "$tag" public-assets/* --clobber' "$release_workflow" || fail PROMOTION_UPLOAD
grep -Fq -- 'DRAFT_PROMOTION_RECONCILE_PASS' "$release_workflow" || fail PROMOTION_RECONCILIATION
for forbidden in   'cargo test'   'packaging/build-artifacts.sh'   'provision-provider-canaries.sh'   'local-codex-plugin-activation-smoke.sh'   'local-plugin-activation-smoke.sh'   'check-provider-pins.sh'   'immutable-releases'   'npm view'
do
  if grep -Fq -- "$forbidden" "$release_workflow"; then
    fail "POST_TAG_BLOCKER:$forbidden"
  fi
done
for required in   'Build exact future shipping bundle once'   'Qualify exact staged archive with real providers'   'Rehearse Codex runtime on exact staged shipping bytes'   'Rehearse attestation mechanism before tag'   'Upload exact pre-tag release stage'
do
  grep -Fq -- "$required" "$candidate_workflow" || fail "PRETAG_STAGE_MISSING:$required"
done
printf 'RELEASE_ATTESTATION_CONTRACT_PASS release=%s candidate=%s\n' "$release_workflow" "$candidate_workflow"
