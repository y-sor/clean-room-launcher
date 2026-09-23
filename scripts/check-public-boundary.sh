#!/bin/sh
set -eu

[ "$#" -eq 2 ] && [ "$1" = "--root" ] || {
  echo "usage: check-public-boundary.sh --root PATH" >&2
  exit 64
}

root=$(cd "$2" && pwd -P)
legacy_owner=$(printf '%s%s' 'ewgenij87sn' 'work')
legacy_repo="$legacy_owner/clean-room-launcher"
legacy_pages="$legacy_owner.github.io"

if find "$root" \( -name .git -o -name target -o -name .clroom-dev -o -path "$root/reports/gates" -o -path "$root/scripts/gates" \) -prune -o -type l -print | grep -q .; then
  echo "SYMLINK_ESCAPE" >&2
  exit 10
fi

inventory=$(mktemp "${TMPDIR:-/tmp}/clroom-public-inventory.XXXXXX")
cleanup() {
  case "$inventory" in
    "${TMPDIR:-/tmp}"/clroom-public-inventory.*) rm -f -- "$inventory" ;;
    *) echo "REFUSED_UNSAFE_TEMP_CLEANUP" >&2; exit 70 ;;
  esac
}
trap cleanup EXIT HUP INT TERM

find "$root" \( -name .git -o -name target -o -name .clroom-dev -o -path "$root/reports/gates" -o -path "$root/scripts/gates" \) -prune -o -type f -print |
  LC_ALL=C sort > "$inventory"

while IFS= read -r file; do
  relative=${file#"$root"/}
  case "$relative" in
    AGENTS.md|README.md|CONTRIBUTING.md|Cargo.toml|Cargo.lock|rust-toolchain.toml|LICENSE|SECURITY.md|GOVERNANCE.md|CHANGELOG.md|deny.toml|install.sh|.gitignore|.github/CODEOWNERS|.github/FUNDING.yml|.github/dependabot.yml|.github/scorecard.yml|.github/workflows/ci.yml|.github/workflows/release.yml|.github/workflows/release-candidate.yml|.github/workflows/indexnow.yml|.github/workflows/scorecard.yml|.github/workflows/codeql.yml|.github/workflows/dependency-review.yml|.github/workflows/fuzz.yml|schemas/canonical-json-profile.md) ;;
    src/*|docs/*|packaging/*|qualification/*|schemas/contracts/*|schemas/release/*|fixtures/contracts/*|fixtures/core/*|fixtures/catalog/*|fixtures/cli/*|fixtures/adapters/*|adapters/declarations/*|tests/contracts/*|tests/core/*|tests/catalog/*|tests/cli.rs|tests/cli/*|tests/fixtures/*|tests/public_identity.rs|tests/readme_plaque.rs|tests/discovery_surface.rs|tests/release_system.rs|tests/adapters.rs|tests/adapters/*|tests/packaging/*|tests/release/*|scripts/check-public-boundary.sh|scripts/indexnow_changed_urls.py|scripts/probe/*|scripts/release/*|scripts/release-build/*|reports/contracts/*|reports/release/*|site/*|fuzz/*) ;;
    *) echo "UNALLOWLISTED_PUBLIC_PATH:$relative" >&2; exit 11 ;;
  esac

  case "$relative" in
    tests/fixtures/public-boundary/*|tests/release/audit_fixtures/*) continue ;;
  esac

  if LC_ALL=C grep -E -q 'role:[[:space:]]*(conductor|teacher|student|verifier)' "$file"; then
    echo "PRIVATE_PRAXIS_ROLE" >&2
    exit 12
  fi
  if LC_ALL=C grep -E -q '(/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/)' "$file"; then
    echo "ABSOLUTE_HOME_PATH" >&2
    exit 13
  fi
  case "$relative" in
    packaging/supply-chain/schemas/*|tests/release/dossier.rs) ;;
    *)
      if LC_ALL=C grep -E -q '(ghp_[A-Za-z0-9]{30,}|sk-[A-Za-z0-9_-]{20,}|AKIA[0-9A-Z]{16})' "$file"; then
        echo "CREDENTIAL_TOKEN" >&2
        exit 14
      fi
      ;;
  esac
  if LC_ALL=C grep -E -q '"role"[[:space:]]*:[[:space:]]*"(user|assistant)"[[:space:]]*,[[:space:]]*"content"' "$file"; then
    echo "TRANSCRIPT_FRAGMENT" >&2
    exit 15
  fi
  case "$relative" in
    # The release readiness gate contains a split legacy-name detector by design;
    # no product/control artifact is grandfathered by this exception.
    scripts/release/readiness.sh) ;;
    *)
      if LC_ALL=C grep -E -i -q 'task[[:space:]-]*seal' "$file"; then
        echo "LEGACY_PRODUCT_IDENTITY" >&2
        exit 16
      fi
      ;;
  esac
  if LC_ALL=C grep -F -i -q "$legacy_repo" "$file" || LC_ALL=C grep -F -i -q "$legacy_pages" "$file"; then
    echo "LEGACY_REPOSITORY_NAMESPACE:$relative" >&2
    exit 17
  fi
done < "$inventory"

cleanup
trap - EXIT HUP INT TERM
echo "PUBLIC_BOUNDARY_PASS"
