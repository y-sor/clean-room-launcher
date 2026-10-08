#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'PUBLIC_INSTALL_ROUTE_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

[[ $# -eq 2 ]] || fail "USAGE:verify-public-release.sh_vX.Y.Z_EXPECTED_SHA" 64
tag=$1
expected=$2
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "STABLE_TAG_REQUIRED"
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || fail "EXPECTED_SHA_INVALID"
[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || fail "MACOS_ARM64_REQUIRED"

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"
repository="y-sor/clean-room-launcher"
version=${tag#v}
for name in git gh python3 shasum curl cmp; do
  command -v "$name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$name" 74
done
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED" 74
[[ "$(git rev-parse HEAD)" == "$expected" ]] || fail "LOCAL_HEAD_MISMATCH"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-public-release.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM
bash scripts/release/resolve-pretag-stage.sh "$version" "$expected" "$tmp/stage" || fail "PRETAG_STAGE"
source scripts/release/provider-pins.sh
python3 scripts/release/verify-pretag-stage.py \
  --dir "$tmp/stage" --version "$version" --source-head "$expected" \
  --codex-version "$CODEX_VERSION" --claude-version "$CLAUDE_VERSION" || fail "PRETAG_STAGE_BINDING"

release_state_ready=false
for attempt in 1 2 3 4 5; do
  if gh release view "$tag" --json tagName,name,isDraft,isPrerelease,isImmutable,publishedAt,body,assets >"$tmp/release.json" 2>/dev/null \
    && gh release view --json tagName,isDraft,isPrerelease,isImmutable,publishedAt >"$tmp/latest.json" 2>/dev/null \
    && python3 - "$tmp/release.json" "$tmp/latest.json" "$tmp/stage/publish-preview.json" <<'PY'
import json, sys
release = json.load(open(sys.argv[1], encoding="utf-8"))
latest = json.load(open(sys.argv[2], encoding="utf-8"))
preview = json.load(open(sys.argv[3], encoding="utf-8"))
if release.get("tagName") != preview["tag_name"] or release.get("name") != preview["release_title"]:
    raise SystemExit(1)
if release.get("isDraft") or release.get("isPrerelease") is not preview["prerelease"] or release.get("isImmutable") is not True or not release.get("publishedAt"):
    raise SystemExit(1)
if (release.get("body") or "").rstrip() != preview["body"].rstrip():
    raise SystemExit(1)
if {item.get("name") for item in release.get("assets", [])} != set(preview["expected_assets"]):
    raise SystemExit(1)
if latest.get("tagName") != preview["tag_name"] or latest.get("isDraft") or latest.get("isImmutable") is not True or not latest.get("publishedAt"):
    raise SystemExit(1)
PY
  then
    release_state_ready=true
    break
  fi
  [[ "$attempt" -lt 5 ]] && sleep 1
done
[[ "$release_state_ready" == true ]] || fail "PUBLIC_RELEASE_STATE_PROPAGATION"

assets_ready=false
for attempt in 1 2 3 4 5; do
  rm -rf -- "$tmp/assets"
  mkdir -p "$tmp/assets"
  if gh release download "$tag" --dir "$tmp/assets" >/dev/null 2>&1; then
    assets_ready=true
    break
  fi
  [[ "$attempt" -lt 5 ]] && sleep 1
done
[[ "$assets_ready" == true ]] || fail "ASSET_DOWNLOAD_PROPAGATION"
python3 - "$tmp/stage/pretag-manifest.json" "$tmp/assets" <<'PY' || fail "PUBLIC_ASSET_BYTES"
import hashlib, json, pathlib, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
root = pathlib.Path(sys.argv[2])
for name in (manifest["artifact_name"], "SHA256SUMS", "sbom.cdx.json", "install.sh"):
    path = root / name
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != manifest["files"][name]:
        raise SystemExit("drift:" + name)
PY

artifact="clean-room-launcher-v${version}-aarch64-apple-darwin.tar.gz"
for subject in "$artifact" sbom.cdx.json install.sh; do
  gh attestation verify "$tmp/assets/$subject" \
    -R "$repository" \
    --bundle "$tmp/assets/$artifact.provenance.sigstore.json" \
    --signer-workflow "$repository/.github/workflows/release.yml" \
    --source-digest "$expected" --source-ref "refs/tags/$tag" --deny-self-hosted-runners >/dev/null \
    || fail "PUBLIC_PROVENANCE:$subject"
done
gh attestation verify "$tmp/assets/$artifact" \
  -R "$repository" \
  --bundle "$tmp/assets/$artifact.sbom.sigstore.json" \
  --predicate-type https://cyclonedx.org/bom \
  --signer-workflow "$repository/.github/workflows/release.yml" \
  --source-digest "$expected" --source-ref "refs/tags/$tag" --deny-self-hosted-runners >/dev/null \
  || fail "PUBLIC_SBOM_ATTESTATION"

latest_base="https://github.com/$repository/releases/latest/download"
curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
  --retry 5 --retry-all-errors --retry-delay 1 \
  "$latest_base/install.sh" -o "$tmp/latest-install.sh" || fail "LATEST_INSTALLER_DOWNLOAD"
curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error \
  --retry 5 --retry-all-errors --retry-delay 1 \
  "$latest_base/SHA256SUMS" -o "$tmp/latest-SHA256SUMS" || fail "LATEST_CHECKSUM_DOWNLOAD"
cmp -s "$tmp/latest-install.sh" "$tmp/stage/install.sh" || fail "LATEST_INSTALLER_DRIFT"
cmp -s "$tmp/latest-SHA256SUMS" "$tmp/stage/SHA256SUMS" || fail "LATEST_CHECKSUM_DRIFT"
chmod 0755 "$tmp/latest-install.sh"

install_home="$tmp"/home
mkdir -p "$install_home"
HOME="$install_home" sh "$tmp/latest-install.sh" >"$tmp/install.out" || fail "ISOLATED_PUBLIC_INSTALL"
for name in clroom clroom-codex clroom-claude; do
  HOME="$install_home" "$install_home"/.local/bin/"$name" --clroom-installer-smoke >/dev/null 2>&1 \
    || fail "INSTALLED_BINARY:$name"
done

echo "PUBLIC_INSTALL_ROUTE_VERIFY_PASS tag=$tag target=$expected"
