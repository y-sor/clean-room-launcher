#!/usr/bin/env bash
set -euo pipefail

release_workflow=${1:-.github/workflows/release.yml}
candidate_workflow=${2:-.github/workflows/release-candidate.yml}

fail() {
  printf 'RELEASE_ATTESTATION_CONTRACT_BLOCKED:%s\n' "$1" >&2
  exit 1
}

[[ -f "$release_workflow" ]] || fail "RELEASE_WORKFLOW_MISSING"
[[ -f "$candidate_workflow" ]] || fail "CANDIDATE_WORKFLOW_MISSING"

pin='uses: actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6 # v4.2.2'
grep -Fq -- "$pin" "$release_workflow" || fail "RELEASE_ATTEST_ACTION_PIN"
grep -Fq -- "$pin" "$candidate_workflow" || fail "CANDIDATE_ATTEST_ACTION_PIN"

for required in   'subject-checksums: release-artifacts/SHA256SUMS'   'PROVENANCE_BUNDLE: ${{ steps.provenance.outputs.bundle-path }}'   'SBOM_BUNDLE: ${{ steps.sbom_attestation.outputs.bundle-path }}'   '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release.yml"'   '--source-digest "$GITHUB_SHA"'   '--source-ref "$GITHUB_REF"'   '.provenance.sigstore.json'   '.sbom.sigstore.json'   'gh release upload "$tag" release-artifacts/* --clobber'   'Reconcile uploaded Draft bytes'
do
  grep -Fq -- "$required" "$release_workflow" || fail "RELEASE_CONTRACT:$required"
done

for required in   'name: Rehearse staged attestation mechanism'   'subject-checksums: release-stage/release-assets/SHA256SUMS'   '--signer-workflow "$GITHUB_REPOSITORY/.github/workflows/release-candidate.yml"'   '--source-digest "$GITHUB_SHA"'   '--source-ref "$GITHUB_REF"'
do
  grep -Fq -- "$required" "$candidate_workflow" || fail "CANDIDATE_REHEARSAL:$required"
done

python3 - "$release_workflow" <<'PY'
from pathlib import Path
import sys

source = Path(sys.argv[1]).read_text(encoding="utf-8")
for forbidden in (
    "cargo test",
    "cargo build",
    "cargo fetch",
    "provision-provider-canaries",
    "qualify-real-provider",
    "local-codex-plugin-activation-smoke",
    "local-plugin-activation-smoke",
    "check-provider-pins.sh",
    "/immutable-releases",
):
    if forbidden in source:
        raise SystemExit(
            "RELEASE_ATTESTATION_CONTRACT_BLOCKED:POST_TAG_BLOCKER:" + forbidden
        )
PY

printf 'RELEASE_ATTESTATION_CONTRACT_PASS release=%s candidate=%s\n' \
  "$release_workflow" "$candidate_workflow"
