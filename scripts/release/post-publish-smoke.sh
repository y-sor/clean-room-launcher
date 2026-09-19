#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 vX.Y.Z" >&2
  exit 2
}

fail() {
  printf 'POST_PUBLISH_SMOKE_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

[[ $# -eq 1 ]] || usage
tag=$1
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "STABLE_TAG_REQUIRED"
version=${tag#v}
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"

for command_name in curl shasum tar gh python3; do
  command -v "$command_name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$command_name"
done

repo_url="https://github.com/y-sor/clean-room-launcher"
base_url="$repo_url/releases/download/$tag"
artifact="clean-room-launcher-$tag-aarch64-apple-darwin.tar.gz"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-post-publish.XXXXXX")
cleanup() {
  rm -rf -- "$tmp"
}
trap cleanup EXIT HUP INT TERM

latest_url=$(curl --proto '=https' --tlsv1.2 -fsSL -o /dev/null -w '%{url_effective}' "$repo_url/releases/latest")
release_title=$(gh release view "$tag" --json name,isDraft,isPrerelease,tagName --jq '.name')
release_tag=$(gh release view "$tag" --json tagName --jq '.tagName')
release_draft=$(gh release view "$tag" --json isDraft --jq '.isDraft')
release_prerelease=$(gh release view "$tag" --json isPrerelease --jq '.isPrerelease')
source_head=$(gh api "repos/y-sor/clean-room-launcher/commits/$tag" --jq .sha)
[[ "$source_head" =~ ^[0-9a-f]{40}$ ]] || fail "PUBLIC_TAG_SOURCE_UNKNOWN"
short_head=${source_head:0:12}
evidence="target/release-evidence/draft-v${version}-${short_head}.json"
[[ -f "$evidence" ]] || fail "DRAFT_SMOKE_EVIDENCE_MISSING"
gh api "repos/y-sor/clean-room-launcher/releases/tags/$tag" > "$tmp/public-release.json" \
  || fail "PUBLIC_RELEASE_STATE"
[[ "$release_tag" == "$tag" ]] || fail "PUBLIC_RELEASE_TAG_MISMATCH"
[[ "$release_title" == "$tag — Clean Room Launcher" ]] || fail "PUBLIC_RELEASE_TITLE_MISMATCH"
[[ "$release_draft" == false ]] || fail "PUBLIC_RELEASE_STILL_DRAFT"
[[ "$release_prerelease" == false ]] || fail "PUBLIC_RELEASE_UNEXPECTED_PRERELEASE"
[[ "$latest_url" == "$repo_url/releases/tag/$tag" ]] || {
  printf 'LATEST_URL=%s\nEXPECTED=%s\n' "$latest_url" "$repo_url/releases/tag/$tag" >&2
  fail "LATEST_RELEASE_MISMATCH"
}

gh release verify "$tag" -R y-sor/clean-room-launcher >/dev/null \
  || fail "PUBLIC_RELEASE_ATTESTATION"

for name in   "$artifact"   SHA256SUMS   sbom.cdx.json   install.sh   "$artifact.provenance.sigstore.json"   "$artifact.sbom.sigstore.json"; do
  curl --proto '=https' --tlsv1.2 -fsSL --retry 3     "$base_url/$name" -o "$tmp/$name" || fail "DOWNLOAD_FAILED:$name"
done

(
  cd "$tmp"
  shasum -a 256 -c SHA256SUMS
) >/dev/null || fail "PUBLIC_CHECKSUMS"

python3 - "$evidence" "$tag" "$source_head" "$tmp/public-release.json" "$tmp" <<'PY' \
  || fail "PUBLIC_RELEASE_DRIFT_FROM_ACCEPTED_DRAFT"
import hashlib
import json
import pathlib
import sys

evidence_path, tag, source, release_path, assets_dir = sys.argv[1:]
record = json.loads(pathlib.Path(evidence_path).read_text(encoding="utf-8"))
if record.get("phase") != "draft" or record.get("result") != "PASS":
    raise SystemExit("evidence")
if record.get("release_tag") != tag or record.get("source_head") != source:
    raise SystemExit("identity")
state = record.get("draft_release_state") or {}
expected_body = state.get("release_body_sha256")
expected_assets = state.get("assets_sha256")
if not isinstance(expected_body, str) or not isinstance(expected_assets, dict):
    raise SystemExit("state")

release = json.loads(pathlib.Path(release_path).read_text(encoding="utf-8"))
if release.get("draft") is not False or release.get("immutable") is not True:
    raise SystemExit("release-state")
body = release.get("body")
if not isinstance(body, str):
    raise SystemExit("body")
if hashlib.sha256(body.encode("utf-8")).hexdigest() != expected_body:
    raise SystemExit("body-drift")

api_assets = release.get("assets")
if not isinstance(api_assets, list) or len(api_assets) != len(expected_assets):
    raise SystemExit("api-asset-count")
api_digests = {}
for item in api_assets:
    name = item.get("name")
    digest = item.get("digest")
    if not isinstance(name, str) or not isinstance(digest, str) or not digest.startswith("sha256:"):
        raise SystemExit("api-asset-digest")
    api_digests[name] = digest.removeprefix("sha256:")
if api_digests != expected_assets:
    raise SystemExit("api-asset-drift")

root = pathlib.Path(assets_dir)
actual = {}
for name in expected_assets:
    path = root / name
    if not path.is_file():
        raise SystemExit("missing-asset:" + name)
    actual[name] = hashlib.sha256(path.read_bytes()).hexdigest()
if actual != expected_assets:
    raise SystemExit("asset-drift")
PY

gh attestation verify "$tmp/$artifact"   -R y-sor/clean-room-launcher   --bundle "$tmp/$artifact.provenance.sigstore.json"   --signer-workflow y-sor/clean-room-launcher/.github/workflows/release.yml   --source-digest "$source_head"   --source-ref "refs/tags/$tag"   --deny-self-hosted-runners >/dev/null || fail "PUBLIC_PROVENANCE"
gh attestation verify "$tmp/$artifact"   -R y-sor/clean-room-launcher   --bundle "$tmp/$artifact.sbom.sigstore.json"   --signer-workflow y-sor/clean-room-launcher/.github/workflows/release.yml   --source-digest "$source_head"   --source-ref "refs/tags/$tag"   --deny-self-hosted-runners >/dev/null || fail "PUBLIC_SBOM_ATTESTATION"

extract="$tmp/extracted"
mkdir -p "$extract"
tar -xzf "$tmp/$artifact" -C "$extract"
archive_root=$(find "$extract" -mindepth 1 -maxdepth 1 -type d -print -quit)
[[ -n "$archive_root" ]] || fail "ARCHIVE_ROOT"
grep -Fqx "version=$version" "$archive_root/VERSION" || fail "ARCHIVE_VERSION"

latest_installer="$tmp/latest-install.sh"
curl --proto '=https' --tlsv1.2 -fsSL --retry 3 \
  "$repo_url/releases/latest/download/install.sh" -o "$latest_installer" \
  || fail "LATEST_INSTALLER_DOWNLOAD"
cmp -s "$latest_installer" "$tmp/install.sh" || fail "LATEST_INSTALLER_BYTES_MISMATCH"
chmod 0755 "$latest_installer"

install_home="$tmp/install-home"
mkdir -p "$install_home"
HOME="$install_home" PATH="$PATH" sh "$latest_installer" >/dev/null || fail "PUBLIC_INSTALLER"
installed="$install_home/.local/bin/clroom"
[[ -x "$installed" ]] || fail "INSTALLED_BINARY_MISSING"

reported=$("$installed" --version 2>&1 | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1)
[[ "$reported" == "$version" ]] || {
  printf 'INSTALLED_VERSION=%s EXPECTED=%s\n' "$reported" "$version" >&2
  fail "INSTALLED_VERSION_MISMATCH"
}

"$installed" --help >/dev/null || fail "INSTALLED_HELP"
HOME="$install_home" PATH="$PATH" "$installed" codex --version >/dev/null || fail "INSTALLED_CODEX_VERSION_PATH"
HOME="$install_home" PATH="$PATH" "$installed" claude --version >/dev/null || fail "INSTALLED_CLAUDE_VERSION_PATH"

public_sha=$(shasum -a 256 "$tmp/$artifact" | awk '{print $1}')
printf 'POST_PUBLISH_SMOKE=PASS tag=%s artifact_sha256=%s\n' "$tag" "$public_sha"
