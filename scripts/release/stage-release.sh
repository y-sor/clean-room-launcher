#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'PRETAG_STAGE_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

[[ $# -eq 2 ]] || fail "USAGE:stage-release.sh_EXPECTED_HEAD_OUTPUT_DIR" 64
expected=$1
output=$2
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || fail "EXPECTED_SHA"

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"

[[ "$(uname -s)" == Darwin && "$(uname -m)" == arm64 ]] || fail "MACOS_ARM64_REQUIRED"
for name in git cargo rustc rustup python3 shasum tar; do
  command -v "$name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$name"
done
[[ -z "$(git status --porcelain)" ]] || fail "WORKTREE_NOT_CLEAN"
head=$(git rev-parse HEAD)
[[ "$head" == "$expected" ]] || fail "HEAD_NOT_EXPECTED"
source_tree=$(git rev-parse "HEAD^{tree}")

version=$(python3 - <<'PY'
import tomllib
with open("Cargo.toml", "rb") as handle:
    print(tomllib.load(handle)["package"]["version"])
PY
)
review_path="reports/release/v${version}-review.json"
[[ -f "$review_path" ]] || fail "REVIEW_FILE_MISSING"
reviewed_content_digest=$(python3 - "$review_path" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as handle:
    print(json.load(handle)["reviewed_content_digest"])
PY
)
[[ "$reviewed_content_digest" =~ ^[0-9a-f]{64}$ ]] || fail "REVIEW_DIGEST"

python3 scripts/release/check-release-contract.py --report >/dev/null || fail "RELEASE_CONTRACT"

# Freeze registry freshness/integrity before the irreversible tag. This decision is
# intentionally not repeated after tag creation.
# shellcheck source=provider-pins.sh
source scripts/release/provider-pins.sh
bash scripts/release/check-provider-pins.sh || fail "PROVIDER_REGISTRY_FREEZE"

for name in   CLROOM_PROVIDER_CODEX CLROOM_PROVIDER_CODEX_VERSION   CLROOM_PROVIDER_CLAUDE CLROOM_PROVIDER_CLAUDE_VERSION
do
  [[ -n "${!name:-}" ]] || fail "PROVIDER_ENV_MISSING:$name"
done
[[ "$CLROOM_PROVIDER_CODEX_VERSION" == "$CODEX_VERSION" ]] || fail "CODEX_PROVIDER_VERSION_ENV"
[[ "$CLROOM_PROVIDER_CLAUDE_VERSION" == "$CLAUDE_VERSION" ]] || fail "CLAUDE_PROVIDER_VERSION_ENV"

rm -rf -- "$output"
mkdir -p "$output"
tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-pretag-stage.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

rustup target add aarch64-apple-darwin >/dev/null
cargo fetch --locked >/dev/null
cargo metadata   --locked   --offline   --filter-platform aarch64-apple-darwin   --format-version 1   >"$tmp/cargo-metadata.json"

CLROOM_TARGET=aarch64-apple-darwin CLROOM_SOURCE_COMMIT="$head"   ./packaging/build-artifacts.sh "$output" >"$tmp/build.log"

artifact_name="clean-room-launcher-v${version}-aarch64-apple-darwin.tar.gz"
artifact="$output/$artifact_name"
[[ -f "$artifact" ]] || fail "ARTIFACT_MISSING"
python3 packaging/verify-artifact.py "$artifact" >/dev/null || fail "ARTIFACT_METADATA"

python3 - "$artifact" "$head" "$version" <<'PY' || fail "ARTIFACT_IDENTITY"
import sys, tarfile
path, head, version = sys.argv[1:]
with tarfile.open(path, "r:gz") as archive:
    versions = [
        member for member in archive.getmembers()
        if member.isfile() and member.name.endswith("/VERSION")
    ]
    if len(versions) != 1:
        raise SystemExit("VERSION-count")
    body = archive.extractfile(versions[0]).read().decode("utf-8")
required = {
    f"version={version}",
    f"source_commit={head}",
    "qualification=CANDIDATE",
    "signing=unsigned",
}
lines = set(body.splitlines())
missing = sorted(required - lines)
if missing:
    raise SystemExit("VERSION-missing:" + ",".join(missing))
PY

python3 packaging/generate-release-sbom.py   --artifact "$artifact"   --metadata "$tmp/cargo-metadata.json"   --output "$output/sbom.cdx.json"
install -m 0755 install.sh "$output/install.sh"
(
  cd "$output"
  shasum -a 256 "$artifact_name" sbom.cdx.json install.sh > SHA256SUMS
  shasum -a 256 -c SHA256SUMS
) >/dev/null

extract_dir="$tmp/release-archive"
mkdir -p "$extract_dir"
tar -xzf "$artifact" -C "$extract_dir"
archive_root=$(find "$extract_dir" -mindepth 1 -maxdepth 1 -type d -print -quit)
[[ -n "$archive_root" ]] || fail "ARCHIVE_ROOT_MISSING"
codex_candidate="$archive_root/bin/clroom-codex"
claude_candidate="$archive_root/bin/clroom-claude"
[[ -x "$codex_candidate" && -x "$claude_candidate" ]] || fail "ARCHIVE_PROVIDER_ENTRYPOINTS"

scripts/release/qualify-real-provider.sh   --provider codex   --executable "$CLROOM_PROVIDER_CODEX"   --expected-provider-version "$CLROOM_PROVIDER_CODEX_VERSION"   --candidate "$codex_candidate"   --source-head "$head"   --version "$version"   --output "$output/codex-qualification.json"   || fail "GENERIC_CODEX_QUALIFICATION"

scripts/release/qualify-real-provider.sh   --provider claude   --executable "$CLROOM_PROVIDER_CLAUDE"   --expected-provider-version "$CLROOM_PROVIDER_CLAUDE_VERSION"   --candidate "$claude_candidate"   --source-head "$head"   --version "$version"   --output "$output/claude-qualification.json"   || fail "GENERIC_CLAUDE_QUALIFICATION"

python3 scripts/release/verify-qualification.py   "$artifact" "$output/codex-qualification.json"   "$head" "$version" codex "$CODEX_VERSION"   || fail "GENERIC_CODEX_EVIDENCE"
python3 scripts/release/verify-qualification.py   "$artifact" "$output/claude-qualification.json"   "$head" "$version" claude "$CLAUDE_VERSION"   || fail "GENERIC_CLAUDE_EVIDENCE"

provider_bin="$tmp/provider-bin"
evidence_dir="$tmp/evidence"
mkdir -p "$provider_bin" "$evidence_dir"
ln -s "$CLROOM_PROVIDER_CODEX" "$provider_bin/codex"
PATH="$provider_bin:$PATH" CLROOM_RELEASE_EVIDENCE_DIR="$evidence_dir"   bash scripts/release/local-codex-plugin-activation-smoke.sh stage     --expected-head "$head"     --artifact "$artifact"     --fixture-standalone-mcp     || fail "CODEX_EXACT_ARCHIVE_RUNTIME"

codex_evidence="$evidence_dir/codex-stage-v${version}-${head:0:12}.json"
[[ -s "$codex_evidence" ]] || fail "CODEX_STAGE_EVIDENCE_MISSING"
install -m 0644 "$codex_evidence" "$output/codex-stage.json"

python3 scripts/release/render-release-notes.py   --version "$version"   --artifact "$artifact_name"   --output "$output/release-notes.md"   || fail "RELEASE_NOTES"

python3 -   "$output" "$version" "$head" "$source_tree" "$reviewed_content_digest"   "$artifact_name" "$CODEX_VERSION" "$CODEX_SHA512" "$CODEX_PLATFORM_SHA512"   "$CLAUDE_VERSION" "$CLAUDE_SHA512" "$CLAUDE_PLATFORM_SHA512" <<'PY'
import hashlib, json, pathlib, sys
(
    raw_root, version, source_head, source_tree, review_digest, artifact_name,
    codex_version, codex_sha512, codex_platform_sha512,
    claude_version, claude_sha512, claude_platform_sha512,
) = sys.argv[1:]
root = pathlib.Path(raw_root)

def sha(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

names = [
    artifact_name,
    "SHA256SUMS",
    "sbom.cdx.json",
    "install.sh",
    "release-notes.md",
    "codex-qualification.json",
    "claude-qualification.json",
    "codex-stage.json",
]
files = {name: sha(root / name) for name in names}
record = {
    "schema_version": "clroom.pretag-stage.v1",
    "release_version": version,
    "source_head": source_head,
    "source_tree": source_tree,
    "reviewed_content_digest": review_digest,
    "artifact_name": artifact_name,
    "provider_registry_freshness": "PASS",
    "generic_provider_qualification": "PASS",
    "codex_exact_archive_runtime": "PASS",
    "providers": {
        "codex": {
            "version": codex_version,
            "package_integrity_sha512": codex_sha512,
            "platform_integrity_sha512": codex_platform_sha512,
        },
        "claude": {
            "version": claude_version,
            "package_integrity_sha512": claude_sha512,
            "platform_integrity_sha512": claude_platform_sha512,
        },
    },
    "blocker_closure": sorted({
        "release_contract",
        "release_readiness",
        "exact_shipping_archive",
        "generic_provider_qualification",
        "codex_exact_archive_runtime",
        "installer_contract",
        "release_notes_render",
        "provider_registry_freeze",
    }),
    "post_tag_only": sorted({
        "tag_bound_attestation",
        "draft_promotion",
        "draft_reconciliation",
    }),
    "files": files,
}
(root / "pretag-manifest.json").write_text(
    json.dumps(record, sort_keys=True, indent=2) + "\n",
    encoding="utf-8",
)
PY

python3 scripts/release/verify-pretag-stage.py   --dir "$output"   --version "$version"   --source-head "$head"   --source-tree "$source_tree"   --reviewed-content-digest "$reviewed_content_digest"   --codex-version "$CODEX_VERSION"   --claude-version "$CLAUDE_VERSION"   || fail "FINAL_VERIFY"

artifact_sha=$(shasum -a 256 "$artifact" | awk '{print $1}')
printf 'PRETAG_STAGE_PASS version=%s source=%s tree=%s artifact_sha256=%s\n'   "$version" "$head" "$source_tree" "$artifact_sha"
