#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 PREVIOUS_PUBLISHED_TAG [CANDIDATE_REF]" >&2
  exit 2
}

[[ $# -ge 1 && $# -le 2 ]] || usage
base=$1
candidate=${2:-HEAD}

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"

git rev-parse --verify "$base^{commit}" >/dev/null 2>&1 || {
  echo "RELEASE_DELTA_BLOCKED:BASE_TAG_NOT_FOUND:$base" >&2
  exit 1
}
git rev-parse --verify "$candidate^{commit}" >/dev/null 2>&1 || {
  echo "RELEASE_DELTA_BLOCKED:CANDIDATE_NOT_FOUND:$candidate" >&2
  exit 1
}

base_sha=$(git rev-parse "$base^{commit}")
candidate_sha=$(git rev-parse "$candidate^{commit}")

python3 scripts/release/check-release-review.py \
  --base-tag "$base" \
  --candidate "$candidate_sha"

git merge-base --is-ancestor "$base_sha" "$candidate_sha" || {
  echo "RELEASE_DELTA_BLOCKED:BASE_NOT_ANCESTOR" >&2
  exit 1
}

version=$(python3 - <<'PY'
import tomllib
with open("Cargo.toml", "rb") as handle:
    print(tomllib.load(handle)["package"]["version"])
PY
)

echo "========================================"
echo "CLROOM WHOLE-RELEASE DELTA"
echo "BASE_TAG=$base"
echo "BASE_SHA=$base_sha"
echo "CANDIDATE_REF=$candidate"
echo "CANDIDATE_SHA=$candidate_sha"
echo "PACKAGE_VERSION=$version"
echo "========================================"
echo

echo "=== 1. COMMITS SINCE $base ==="
git log --date=short --format='%h  %ad  %s' "$base_sha..$candidate_sha"
echo

echo "=== 2. EXACT CHANGED FILES ==="
git diff --name-status "$base_sha..$candidate_sha"
echo

echo "=== 3. RELEASE DELTA SUMMARY ==="
git diff --stat "$base_sha..$candidate_sha"
echo

echo "=== 4. DEPENDENCY / LOCKFILE DELTA ==="
if git diff --quiet "$base_sha..$candidate_sha" -- Cargo.toml Cargo.lock; then
  echo "NO_DEPENDENCY_MANIFEST_OR_LOCKFILE_CHANGE"
else
  git diff "$base_sha..$candidate_sha" -- Cargo.toml Cargo.lock
fi
echo

echo "=== 5. HIGH-RISK RELEASE SURFACES CHANGED ==="
high_risk=(
  src
  install.sh
  packaging
  scripts/release
  .github/workflows
  Cargo.toml
  Cargo.lock
  SECURITY.md
)
found=0
for path in "${high_risk[@]}"; do
  if ! git diff --quiet "$base_sha..$candidate_sha" -- "$path"; then
    echo "$path"
    found=1
  fi
done
[[ $found -eq 1 ]] || echo "NONE"
echo

echo "=== 6. PUBLIC TRUTH CHANGED ==="
public_paths=(README.md CHANGELOG.md SECURITY.md docs)
found=0
for path in "${public_paths[@]}"; do
  if ! git diff --quiet "$base_sha..$candidate_sha" -- "$path"; then
    echo "$path"
    found=1
  fi
done
[[ $found -eq 1 ]] || echo "NONE"
echo

echo "=== 7. PROVIDER QUALIFICATION TRUTH ==="
python3 scripts/release/check-provider-version-sync.py
echo

echo "=== 8. CURRENT RELEASE CHANGELOG SECTION ==="
python3 - "$version" <<'PY'
import sys
from pathlib import Path

version = sys.argv[1]
lines = Path("CHANGELOG.md").read_text(encoding="utf-8").splitlines()
start = None
for index, line in enumerate(lines):
    if line.startswith(f"## [{version}] - "):
        start = index
        break
if start is None:
    raise SystemExit("RELEASE_DELTA_BLOCKED:CHANGELOG_VERSION_SECTION_MISSING")
end = len(lines)
for index in range(start + 1, len(lines)):
    if lines[index].startswith("## ["):
        end = index
        break
print("\n".join(lines[start:end]))
PY
echo

echo "=== MANUAL REVIEW COMMANDS ==="
echo "git diff '$base_sha..$candidate_sha' -- src/"
echo "git diff '$base_sha..$candidate_sha' -- .github/workflows scripts/release packaging install.sh"
echo "git diff '$base_sha..$candidate_sha' -- Cargo.toml Cargo.lock"
echo "git diff '$base_sha..$candidate_sha' -- README.md CHANGELOG.md SECURITY.md docs/"
echo

echo "RELEASE_DELTA_REVIEW_READY base=$base candidate=$candidate_sha"
echo "NOTE=READY_MEANS_INVENTORIED_NOT_HUMAN_ACCEPTED"
