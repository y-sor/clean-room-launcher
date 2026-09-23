#!/usr/bin/env bash
set -euo pipefail

release_workflow=${1:-.github/workflows/release.yml}
candidate_workflow=${2:-.github/workflows/release-candidate.yml}

fail() {
  printf 'RELEASE_ATTESTATION_CONTRACT_BLOCKED:%s\n' "$1" >&2
  exit 1
}

[[ -f "$release_workflow" && -f "$candidate_workflow" ]] || fail "WORKFLOW_MISSING"
pin='uses: actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6 # v4.2.2'

grep -Fq -- "$pin" "$release_workflow" || fail "TAG_ATTEST_ACTION_PIN"
grep -Fq -- "$pin" "$candidate_workflow" || fail "PRETAG_ATTEST_ACTION_PIN"
grep -Fq -- 'subject-checksums: release-stage/SHA256SUMS' "$release_workflow" || fail "TAG_PROVENANCE_SUBJECTS"
grep -Fq -- 'subject-checksums: pretag-stage/SHA256SUMS' "$candidate_workflow" || fail "PRETAG_PROVENANCE_SUBJECTS"
grep -Fq -- 'sbom-path: release-stage/sbom.cdx.json' "$release_workflow" || fail "TAG_SBOM_SUBJECTS"
grep -Fq -- 'sbom-path: pretag-stage/sbom.cdx.json' "$candidate_workflow" || fail "PRETAG_SBOM_SUBJECTS"

for required in   '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release.yml"'   '--source-digest "$GITHUB_SHA"'   '--source-ref "$GITHUB_REF"'   '--deny-self-hosted-runners'   '.provenance.sigstore.json'   '.sbom.sigstore.json'   'release-attestations-v'   'gh release upload'
do
  grep -Fq -- "$required" "$release_workflow" || fail "TAG_ATTEST_CONTRACT:$required"
done

for required in   '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release-candidate.yml"'   '--source-digest "$GITHUB_SHA"'   '--source-ref "refs/heads/main"'   '--deny-self-hosted-runners'   'PRETAG_ATTESTATION_REHEARSAL_PASS'
do
  grep -Fq -- "$required" "$candidate_workflow" || fail "PRETAG_ATTEST_CONTRACT:$required"
done

printf 'RELEASE_ATTESTATION_CONTRACT_PASS release=%s candidate=%s\n'   "$release_workflow" "$candidate_workflow"
