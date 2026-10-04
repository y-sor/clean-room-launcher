#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'PUBLIC_ROUTE_REHEARSAL_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

[[ "${1:-}" == "--self-test" || $# -eq 0 ]] || fail "USAGE:rehearse-public-route.sh_[--self-test]" 64

self_test() {
  python3 - <<'PY'
def classify(release, latest):
    if release.get("tagName") != latest.get("tagName"):
        return "LATEST_IDENTITY"
    if release.get("isDraft") or release.get("isPrerelease"):
        return "RELEASE_STATE"
    if release.get("isImmutable") is not True or not release.get("publishedAt"):
        return "RELEASE_IMMUTABILITY"
    names = {item.get("name") for item in release.get("assets", [])}
    if not {"install.sh", "SHA256SUMS"} <= names:
        return "ROUTE_ASSETS"
    return "PASS"

clean = {
    "tagName": "v0.4.4",
    "isDraft": False,
    "isPrerelease": False,
    "isImmutable": True,
    "publishedAt": "2026-09-23T00:00:00Z",
    "assets": [{"name": "install.sh"}, {"name": "SHA256SUMS"}],
}
if classify(clean, clean) != "PASS":
    raise SystemExit("clean")
bad = dict(clean)
bad["isImmutable"] = False
if classify(bad, clean) != "RELEASE_IMMUTABILITY":
    raise SystemExit("immutable")
bad_latest = dict(clean)
bad_latest["tagName"] = "v0.4.3"
if classify(clean, bad_latest) != "LATEST_IDENTITY":
    raise SystemExit("latest")
print("PUBLIC_ROUTE_REHEARSAL_SELF_TEST_PASS")
PY
}

if [[ "${1:-}" == "--self-test" ]]; then
  self_test
  exit 0
fi

[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || fail "MACOS_ARM64_REQUIRED"
for name in gh python3 curl cmp shasum; do
  command -v "$name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$name" 74
done
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED" 74

repository="y-sor/clean-room-launcher"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-public-route-rehearsal.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

gh release view --repo "$repository"   --json tagName,isDraft,isPrerelease,isImmutable,publishedAt,assets >"$tmp/latest.json"   || fail "LATEST_QUERY"
tag=$(python3 - "$tmp/latest.json" <<'PY'
import json, re, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
tag = data.get("tagName") or ""
if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
    raise SystemExit("stable-tag")
print(tag)
PY
) || fail "LATEST_STABLE_TAG"

gh release view "$tag" --repo "$repository"   --json databaseId,tagName,isDraft,isPrerelease,isImmutable,publishedAt,assets >"$tmp/release.json"   || fail "RELEASE_QUERY"

python3 - "$tmp/release.json" "$tmp/latest.json" <<'PY' || exit 1
import json, sys
release = json.load(open(sys.argv[1], encoding="utf-8"))
latest = json.load(open(sys.argv[2], encoding="utf-8"))
if release.get("tagName") != latest.get("tagName"):
    raise SystemExit("PUBLIC_ROUTE_REHEARSAL_BLOCKED:LATEST_IDENTITY")
if release.get("isDraft") or release.get("isPrerelease"):
    raise SystemExit("PUBLIC_ROUTE_REHEARSAL_BLOCKED:RELEASE_STATE")
if release.get("isImmutable") is not True or not release.get("publishedAt"):
    raise SystemExit("PUBLIC_ROUTE_REHEARSAL_BLOCKED:RELEASE_IMMUTABILITY")
if not isinstance(release.get("databaseId"), int):
    raise SystemExit("PUBLIC_ROUTE_REHEARSAL_BLOCKED:RELEASE_DATABASE_ID")
names = {item.get("name") for item in release.get("assets", [])}
if not {"install.sh", "SHA256SUMS"} <= names:
    raise SystemExit("PUBLIC_ROUTE_REHEARSAL_BLOCKED:ROUTE_ASSETS")
PY

mkdir -p "$tmp/release-assets"
gh release download "$tag" --repo "$repository"   --pattern install.sh --pattern SHA256SUMS --dir "$tmp/release-assets"   || fail "RELEASE_DOWNLOAD"

latest_base="https://github.com/$repository/releases/latest/download"
curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error   "$latest_base/install.sh" -o "$tmp/latest-install.sh" || fail "LATEST_INSTALLER_DOWNLOAD"
curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error   "$latest_base/SHA256SUMS" -o "$tmp/latest-SHA256SUMS" || fail "LATEST_CHECKSUM_DOWNLOAD"
cmp -s "$tmp/latest-install.sh" "$tmp/release-assets/install.sh" || fail "LATEST_INSTALLER_ROUTE_DRIFT"
cmp -s "$tmp/latest-SHA256SUMS" "$tmp/release-assets/SHA256SUMS" || fail "LATEST_CHECKSUM_ROUTE_DRIFT"

chmod 0755 "$tmp/latest-install.sh"
install_home="$tmp/home"
mkdir -p "$install_home"
HOME="$install_home" sh "$tmp/latest-install.sh" >"$tmp/install.out" || fail "ISOLATED_PUBLIC_INSTALL"
for name in clroom clroom-codex clroom-claude; do
  HOME="$install_home" "$install_home/.local/bin/$name" --clroom-installer-smoke >/dev/null 2>&1     || fail "INSTALLED_BINARY:$name"
done

printf 'PUBLIC_ROUTE_REHEARSAL_PASS baseline=%s\n' "$tag"
