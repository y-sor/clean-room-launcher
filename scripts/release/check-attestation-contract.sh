#!/usr/bin/env bash
set -euo pipefail

workflow=${1:-.github/workflows/release.yml}

fail() {
  printf 'RELEASE_ATTESTATION_CONTRACT_BLOCKED:%s\n' "$1" >&2
  exit 1
}

[[ -f "$workflow" ]] || fail "WORKFLOW_MISSING"

grep -Fq -- 'uses: actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6 # v4.2.2' "$workflow" || fail "ATTEST_ACTION_PIN"
grep -Fq -- 'subject-checksums: release-artifacts/SHA256SUMS' "$workflow" || fail "PROVENANCE_SUBJECTS"
grep -Fq -- 'PROVENANCE_BUNDLE: ${{ steps.provenance.outputs.bundle-path }}' "$workflow" || fail "PROVENANCE_BUNDLE_OUTPUT"
grep -Fq -- 'SBOM_BUNDLE: ${{ steps.sbom_attestation.outputs.bundle-path }}' "$workflow" || fail "SBOM_BUNDLE_OUTPUT"
grep -Fq -- '--bundle "$provenance"' "$workflow" || fail "PROVENANCE_BUNDLE_VERIFY"
grep -Fq -- '--bundle "$sbom"' "$workflow" || fail "SBOM_BUNDLE_VERIFY"
grep -Fq -- '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release.yml"' "$workflow" || fail "SIGNER_WORKFLOW_BINDING"
grep -Fq -- '--source-digest "$GITHUB_SHA"' "$workflow" || fail "SOURCE_DIGEST_BINDING"
grep -Fq -- '--source-ref "$GITHUB_REF"' "$workflow" || fail "SOURCE_REF_BINDING"
grep -Fq -- '.provenance.sigstore.json' "$workflow" || fail "PROVENANCE_SIDECAR"
grep -Fq -- '.sbom.sigstore.json' "$workflow" || fail "SBOM_SIDECAR"
grep -Fq -- 'gh release upload "$tag" release-artifacts/* --clobber' "$workflow" || fail "RELEASE_UPLOAD_CONTRACT"
[[ $(grep -Fc -- 'name: release-attestations' "$workflow") -eq 2 ]] || fail "ARTIFACT_HANDOFF"

printf 'RELEASE_ATTESTATION_CONTRACT_PASS workflow=%s\n' "$workflow"
