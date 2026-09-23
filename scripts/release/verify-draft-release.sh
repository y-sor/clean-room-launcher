#!/usr/bin/env bash
set -euo pipefail

fail() {
  echo "DRAFT_RELEASE_VERIFY_BLOCKED:$1" >&2
  exit "${2:-1}"
}

[[ $# -eq 2 ]] || fail "USAGE:verify-draft-release.sh_vX.Y.Z_EXPECTED_SHA" 64
tag=$1
expected=$2
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "STABLE_TAG_REQUIRED"
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || fail "EXPECTED_SHA_INVALID"

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"
repository="y-sor/clean-room-launcher"
version=${tag#v}

for name in git gh python3 shasum cmp; do
  command -v "$name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$name"
done
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED"
[[ "$(git rev-parse HEAD)" == "$expected" ]] || fail "LOCAL_HEAD_MISMATCH"
[[ -z "$(git status --porcelain)" ]] || fail "WORKTREE_NOT_CLEAN"

manifest_version=$(python3 - <<'PY'
import tomllib
with open("Cargo.toml", "rb") as handle:
    print(tomllib.load(handle)["package"]["version"])
PY
)
[[ "$manifest_version" == "$version" ]] || fail "VERSION_MISMATCH"

# Repository policy is a mutable publish-time invariant and is read with the
# Owner-authenticated gh session, never with the restricted Actions token.
immutable_enabled=$(gh api "repos/$repository/immutable-releases" --jq .enabled 2>/dev/null) \
  || fail "IMMUTABLE_RELEASE_POLICY_UNVERIFIED"
[[ "$immutable_enabled" == true ]] || fail "IMMUTABLE_RELEASE_POLICY_DISABLED"

git fetch --quiet --force origin "refs/tags/$tag:refs/tags/$tag" || fail "TAG_FETCH"
[[ "$(git cat-file -t "refs/tags/$tag")" == tag ]] || fail "ANNOTATED_TAG_REQUIRED"
[[ "$(git rev-parse "refs/tags/$tag^{}")" == "$expected" ]] || fail "TAG_TARGET_MISMATCH"
[[ "$(git for-each-ref --format='%(contents:subject)' "refs/tags/$tag")" == "$tag — Clean Room Launcher" ]] \
  || fail "TAG_TITLE_MISMATCH"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-draft-release-verify.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

stage="$tmp/stage"
bash scripts/release/resolve-release-stage.sh "$version" "$expected" "$stage" \
  || fail "RELEASE_STAGE_RESOLUTION"
python3 scripts/release/verify-release-stage.py \
  --stage-dir "$stage" \
  --expected-head "$expected" \
  --expected-version "$version" \
  || fail "RELEASE_STAGE_VERIFY"

gh release view "$tag" \
  --json tagName,name,isDraft,isPrerelease,assets \
  >"$tmp/release.json" || fail "RELEASE_QUERY"

python3 - "$tmp/release.json" "$tag" "$version" <<'PY' || fail "RELEASE_IDENTITY_OR_ASSETS"
import json, sys
path, tag, version = sys.argv[1:]
data = json.load(open(path, encoding="utf-8"))
if data.get("tagName") != tag:
    raise SystemExit("tag")
if data.get("name") != f"{tag} — Clean Room Launcher":
    raise SystemExit("name")
if data.get("isDraft") is not True or data.get("isPrerelease") is not False:
    raise SystemExit("state")
artifact = f"clean-room-launcher-v{version}-aarch64-apple-darwin.tar.gz"
expected = {
    artifact,
    f"{artifact}.provenance.sigstore.json",
    f"{artifact}.sbom.sigstore.json",
    "install.sh",
    "sbom.cdx.json",
    "SHA256SUMS",
}
actual = {item.get("name") for item in data.get("assets", [])}
if actual != expected:
    raise SystemExit(f"assets:{sorted(actual)}")
PY

# Every exact-tag push workflow must be successful. The canonical harness
# permits only the promotion-only Release workflow to trigger on v*.
gh api -X GET "repos/$repository/actions/runs" \
  -f head_sha="$expected" -f per_page=100 \
  >"$tmp/runs.json" || fail "ACTIONS_QUERY"

python3 - "$tmp/runs.json" "$tag" "$expected" <<'PY' || fail "EXACT_TAG_ACTIONS"
import json, sys
path, tag, expected = sys.argv[1:]
data = json.load(open(path, encoding="utf-8"))
runs = [
    run for run in data.get("workflow_runs", [])
    if run.get("event") == "push"
    and run.get("head_branch") == tag
    and run.get("head_sha") == expected
]
if not runs:
    raise SystemExit("no-tag-push-runs")
names = {run.get("name") for run in runs}
if "Release" not in names:
    raise SystemExit("missing:Release")
bad = [
    (run.get("name"), run.get("id"), run.get("status"), run.get("conclusion"))
    for run in runs
    if run.get("status") != "completed" or run.get("conclusion") != "success"
]
if bad:
    raise SystemExit("non-success:" + repr(bad))
print("EXACT_TAG_ACTIONS_PASS names=" + ",".join(sorted(name for name in names if name)))
PY

assets="$tmp/assets"
mkdir -p "$assets"
gh release download "$tag" --dir "$assets" || fail "RELEASE_DOWNLOAD"
artifact="$assets/clean-room-launcher-v${version}-aarch64-apple-darwin.tar.gz"
provenance="$artifact.provenance.sigstore.json"
sbom_bundle="$artifact.sbom.sigstore.json"
for path in "$artifact" "$provenance" "$sbom_bundle" "$assets/SHA256SUMS" "$assets/sbom.cdx.json" "$assets/install.sh"; do
  [[ -s "$path" ]] || fail "DRAFT_ASSET_MISSING:$(basename "$path")"
done
[[ "$(find "$assets" -maxdepth 1 -type f | wc -l | tr -d ' ')" == 6 ]] || fail "DRAFT_ASSET_COUNT"

stage_assets="$stage/release-assets"
for name in "clean-room-launcher-v${version}-aarch64-apple-darwin.tar.gz" SHA256SUMS sbom.cdx.json install.sh; do
  cmp "$stage_assets/$name" "$assets/$name" || fail "STAGED_BYTE_DRIFT:$name"
done
(
  cd "$assets"
  shasum -a 256 -c SHA256SUMS
) >/dev/null || fail "DRAFT_CHECKSUMS"

for subject in "$artifact" "$assets/sbom.cdx.json" "$assets/install.sh"; do
  gh attestation verify "$subject" \
    -R "$repository" \
    --bundle "$provenance" \
    --signer-workflow "$repository/.github/workflows/release.yml" \
    --source-digest "$expected" \
    --source-ref "refs/tags/$tag" \
    --deny-self-hosted-runners >/dev/null || fail "DRAFT_PROVENANCE:$(basename "$subject")"
done
gh attestation verify "$artifact" \
  -R "$repository" \
  --bundle "$sbom_bundle" \
  --predicate-type https://cyclonedx.org/bom \
  --signer-workflow "$repository/.github/workflows/release.yml" \
  --source-digest "$expected" \
  --source-ref "refs/tags/$tag" \
  --deny-self-hosted-runners >/dev/null || fail "DRAFT_SBOM_ATTESTATION"

python3 scripts/release/check-post-tag-surface.py || fail "POST_TAG_SURFACE"

artifact_sha=$(shasum -a 256 "$artifact" | awk '{print $1}')
stage_sha=$(python3 - "$stage/stage-manifest.json" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["artifact_sha256"])
PY
)
[[ "$artifact_sha" == "$stage_sha" ]] || fail "STAGE_ARTIFACT_DIGEST"

echo "DRAFT_RELEASE_VERIFY_PASS tag=$tag target=$expected artifact_sha256=$artifact_sha"
