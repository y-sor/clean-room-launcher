#!/usr/bin/env bash
set -euo pipefail
root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"

full=false
if [[ ${1:-} == "--full" ]]; then full=true; shift; fi
[[ $# -eq 0 ]] || { echo "usage: scripts/release/local-release-audit.sh [--full]" >&2; exit 2; }

git fetch --quiet --tags origin
python3 scripts/release/check-release-contract.py --report

echo
echo "=== RELEASE VERSION / DEPENDENCY DELTA ==="
baseline=$(python3 - <<'PY'
import json, urllib.request
req=urllib.request.Request("https://api.github.com/repos/y-sor/clean-room-launcher/releases/latest",headers={"User-Agent":"clroom-local-release-audit"})
with urllib.request.urlopen(req,timeout=20) as r: print(json.load(r)["tag_name"])
PY
)
git diff "$baseline..HEAD" -- Cargo.toml Cargo.lock

if ! $full; then
  echo
  echo "SUMMARY_PASS. Re-run with --full for local tests + artifact verification."
  exit 0
fi

echo
echo "=== FULL LOCAL RELEASE CHECK ==="
git diff --check
./scripts/check-public-boundary.sh --root "$root"
sh install.sh --self-test
cargo test --locked --all-targets

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-local-release-audit.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM
CLROOM_SOURCE_COMMIT=$(git rev-parse HEAD) CLROOM_TARGET='' ./packaging/build-artifacts.sh "$tmp"
artifact=$(find "$tmp" -maxdepth 1 -type f -name 'clean-room-launcher-*.tar.gz' -print -quit)
test -n "$artifact"
python3 packaging/verify-artifact.py "$artifact"
shasum -a 256 "$artifact"
echo "LOCAL_RELEASE_AUDIT_PASS head=$(git rev-parse HEAD) artifact=$artifact"
