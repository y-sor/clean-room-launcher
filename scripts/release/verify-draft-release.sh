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

for name in git gh python3 shasum; do
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

immutable_enabled=$(gh api "repos/$repository/immutable-releases" --jq .enabled 2>/dev/null)   || fail "IMMUTABLE_RELEASE_POLICY_UNVERIFIED"
[[ "$immutable_enabled" == true ]] || fail "IMMUTABLE_RELEASE_POLICY_DISABLED"

git fetch --quiet --force origin "refs/tags/$tag:refs/tags/$tag" || fail "TAG_FETCH"
[[ "$(git cat-file -t "refs/tags/$tag")" == tag ]] || fail "ANNOTATED_TAG_REQUIRED"
[[ "$(git rev-parse "refs/tags/$tag^{}")" == "$expected" ]] || fail "TAG_TARGET_MISMATCH"
[[ "$(git for-each-ref --format='%(contents:subject)' "refs/tags/$tag")" == "$tag — Clean Room Launcher" ]]   || fail "TAG_TITLE_MISMATCH"

current_tree=$(git rev-parse "HEAD^{tree}")
review_path="reports/release/v${version}-review.json"
[[ -f "$review_path" ]] || fail "REVIEW_FILE_MISSING"
reviewed_content_digest=$(python3 - "$review_path" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["reviewed_content_digest"])
PY
)
[[ "$reviewed_content_digest" =~ ^[0-9a-f]{64}$ ]] || fail "REVIEW_CONTENT_DIGEST"

# shellcheck source=provider-pins.sh
source scripts/release/provider-pins.sh

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-draft-release-verify.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

bash scripts/release/resolve-pretag-stage.sh "$version" "$expected" "$tmp/stage"   || fail "PRETAG_STAGE"
python3 scripts/release/verify-pretag-stage.py   --dir "$tmp/stage"   --version "$version"   --source-head "$expected"   --source-tree "$current_tree"   --reviewed-content-digest "$reviewed_content_digest"   --codex-version "$CODEX_VERSION"   --claude-version "$CLAUDE_VERSION"   || fail "PRETAG_STAGE_BINDING"

artifact="clean-room-launcher-v${version}-aarch64-apple-darwin.tar.gz"
artifact_sha=$(python3 - "$tmp/stage/pretag-manifest.json" "$artifact" <<'PY'
import json, sys
record = json.load(open(sys.argv[1], encoding="utf-8"))
print(record["files"][sys.argv[2]])
PY
)
[[ "$artifact_sha" =~ ^[0-9a-f]{64}$ ]] || fail "STAGED_ARTIFACT_DIGEST"

git_common_dir=$(git rev-parse --git-common-dir)
if [[ "$git_common_dir" != /* ]]; then git_common_dir="$root/$git_common_dir"; fi
evidence_dir=${CLROOM_RELEASE_EVIDENCE_DIR:-"$git_common_dir/clroom-release-evidence"}
claude_stage="$evidence_dir/stage-v${version}-${expected:0:12}.json"
[[ -f "$claude_stage" ]] || fail "CLAUDE_STAGE_EVIDENCE_MISSING:$claude_stage"
python3 scripts/release/verify-claude-stage-evidence.py   --evidence "$claude_stage"   --version "$version"   --source-head "$expected"   --source-tree "$current_tree"   --reviewed-content-digest "$reviewed_content_digest"   --artifact-sha256 "$artifact_sha"   --claude-version "$CLAUDE_VERSION"   || fail "CLAUDE_STAGE_EVIDENCE"

gh api -X GET "repos/$repository/actions/runs"   -f head_sha="$expected" -f per_page=100   >"$tmp/runs.json" || fail "ACTIONS_QUERY"
python3 - "$tmp/runs.json" "$tag" "$expected" <<'PY' || fail "EXACT_TAG_PROMOTION_ACTION"
import json, sys
path, tag, expected = sys.argv[1:]
data = json.load(open(path, encoding="utf-8"))
runs = [
    run for run in data.get("workflow_runs", [])
    if run.get("name") == "Release"
    and run.get("event") == "push"
    and run.get("head_branch") == tag
    and run.get("head_sha") == expected
    and run.get("path") == ".github/workflows/release.yml"
]
if not runs:
    raise SystemExit("missing-release-promotion-run")
bad = [
    (run.get("id"), run.get("status"), run.get("conclusion"))
    for run in runs
    if run.get("status") != "completed" or run.get("conclusion") != "success"
]
if bad:
    raise SystemExit("non-success:" + repr(bad))
print("EXACT_TAG_PROMOTION_PASS")
PY

gh release view "$tag"   --json tagName,name,isDraft,isPrerelease,body,assets   >"$tmp/release.json" || fail "RELEASE_QUERY"
python3 - "$tmp/release.json" "$tag" "$version" "$tmp/stage/release-notes.md" <<'PY'   || fail "RELEASE_IDENTITY_NOTES_OR_ASSETS"
import json, pathlib, sys
path, tag, version, notes_path = sys.argv[1:]
data = json.load(open(path, encoding="utf-8"))
if data.get("tagName") != tag:
    raise SystemExit("tag")
if data.get("name") != f"{tag} — Clean Room Launcher":
    raise SystemExit("name")
if data.get("isDraft") is not True or data.get("isPrerelease") is not False:
    raise SystemExit("state")
if (data.get("body") or "").rstrip() != pathlib.Path(notes_path).read_text(encoding="utf-8").rstrip():
    raise SystemExit("notes")
expected = {
    f"clean-room-launcher-v{version}-aarch64-apple-darwin.tar.gz",
    f"clean-room-launcher-v{version}-aarch64-apple-darwin.tar.gz.provenance.sigstore.json",
    f"clean-room-launcher-v{version}-aarch64-apple-darwin.tar.gz.sbom.sigstore.json",
    "install.sh",
    "sbom.cdx.json",
    "SHA256SUMS",
}
actual = {item.get("name") for item in data.get("assets", [])}
if actual != expected:
    raise SystemExit(f"assets:{sorted(actual)}")
PY

mkdir -p "$tmp/assets"
gh release download "$tag" --dir "$tmp/assets" || fail "RELEASE_DOWNLOAD"

python3 - "$tmp/stage/pretag-manifest.json" "$tmp/assets" <<'PY'   || fail "DRAFT_BYTE_RECONCILIATION"
import hashlib, json, pathlib, sys
record = json.load(open(sys.argv[1], encoding="utf-8"))
root = pathlib.Path(sys.argv[2])
for name in (record["artifact_name"], "SHA256SUMS", "sbom.cdx.json", "install.sh"):
    path = root / name
    if not path.is_file():
        raise SystemExit("missing:" + name)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != record["files"][name]:
        raise SystemExit("drift:" + name)
PY

provenance="$tmp/assets/$artifact.provenance.sigstore.json"
sbom_bundle="$tmp/assets/$artifact.sbom.sigstore.json"
for path in "$provenance" "$sbom_bundle"; do
  [[ -s "$path" ]] || fail "DRAFT_ATTESTATION_BUNDLE_MISSING:$(basename "$path")"
done
for subject in "$artifact" sbom.cdx.json install.sh; do
  gh attestation verify "$tmp/assets/$subject"     -R "$repository"     --bundle "$provenance"     --signer-workflow "$repository/.github/workflows/release.yml"     --source-digest "$expected"     --source-ref "refs/tags/$tag"     --deny-self-hosted-runners >/dev/null     || fail "DRAFT_PROVENANCE:$subject"
done
gh attestation verify "$tmp/assets/$artifact"   -R "$repository"   --bundle "$sbom_bundle"   --predicate-type https://cyclonedx.org/bom   --signer-workflow "$repository/.github/workflows/release.yml"   --source-digest "$expected"   --source-ref "refs/tags/$tag"   --deny-self-hosted-runners >/dev/null   || fail "DRAFT_SBOM_ATTESTATION"

echo "DRAFT_RELEASE_VERIFY_PASS tag=$tag target=$expected artifact_sha256=$artifact_sha"
