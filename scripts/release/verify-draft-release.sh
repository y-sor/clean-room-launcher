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
short=${expected:0:12}

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
for required in {"CI", "Release"}:
    if required not in names:
        raise SystemExit(f"missing:{required}")
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

bash scripts/release/check-provider-pins.sh || fail "PROVIDER_PINS"
# shellcheck source=provider-pins.sh
source scripts/release/provider-pins.sh

claude_pretag="target/release-evidence/pretag-v${version}-${short}.json"
claude_draft="target/release-evidence/draft-v${version}-${short}.json"
codex_pretag="target/release-evidence/codex-pretag-v${version}-${short}.json"
codex_draft="target/release-evidence/codex-draft-v${version}-${short}.json"
for path in "$claude_pretag" "$claude_draft" "$codex_pretag" "$codex_draft"; do
  [[ -f "$path" ]] || fail "LOCAL_EVIDENCE_MISSING:$path"
done

artifact_sha=$(shasum -a 256 "$artifact" | awk '{print $1}')
python3 - \
  "$claude_pretag" "$claude_draft" "$codex_pretag" "$codex_draft" \
  "$version" "$expected" "$artifact_sha" "$CLAUDE_VERSION" "$CODEX_VERSION" <<'PY' \
  || fail "LOCAL_EVIDENCE_INVALID"
import json, re, sys
(
    claude_pretag_path, claude_draft_path, codex_pretag_path, codex_draft_path,
    version, expected, artifact_sha, claude_version, codex_version,
) = sys.argv[1:]

def load(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)

cp, cd, xp, xd = map(load, [
    claude_pretag_path, claude_draft_path, codex_pretag_path, codex_draft_path,
])

for record, phase in [(cp, "pretag"), (cd, "draft")]:
    if record.get("schema_version") != "clroom.plugin-release-smoke.v2":
        raise SystemExit("claude-schema")
    required = {
        "result": "PASS",
        "phase": phase,
        "release_version": version,
        "source_head": expected,
        "platform": "macos-aarch64",
        "claude_version": claude_version,
        "clean_target_plugin": False,
        "selected_target_plugin": True,
        "new_sibling_plugins": 0,
        "selected_plugin_errors": 0,
        "persistent_config_unchanged": True,
        "external_ancestor_agents_sandbox_probe_passed": True,
    }
    for key, value in required.items():
        if record.get(key) != value:
            raise SystemExit(f"claude-{phase}:{key}")
    if not record.get("plugin_id"):
        raise SystemExit(f"claude-{phase}:plugin-id")
    if not re.fullmatch(r"[0-9a-f]{64}", str(record.get("claude_provider_sha256", ""))):
        raise SystemExit(f"claude-{phase}:provider-sha")

if cp.get("interactive_selected_tui_confirmed") is not True:
    raise SystemExit("claude-pretag:interactive")
if cp.get("interactive_no_model_prompt_confirmed") is not True:
    raise SystemExit("claude-pretag:no-model")
if cp.get("external_ancestor_agents_absent_confirmed") is not True:
    raise SystemExit("claude-pretag:external-ancestor-agents")
if cp.get("project_agents_retained_confirmed") is not True:
    raise SystemExit("claude-pretag:project-agents-retention")
if cp.get("plugin_id") != cd.get("plugin_id"):
    raise SystemExit("claude-plugin-drift")
if cp.get("claude_provider_sha256") != cd.get("claude_provider_sha256"):
    raise SystemExit("claude-provider-bytes-drift")
if cd.get("artifact_sha256") != artifact_sha:
    raise SystemExit("claude-draft-artifact")

for record, phase in [(xp, "pretag"), (xd, "draft")]:
    if record.get("schema_version") != "clroom.codex-plugin-release-smoke.v2":
        raise SystemExit("codex-schema")
    required = {
        "result": "PASS",
        "phase": phase,
        "release_version": version,
        "source_head": expected,
        "platform": "macos-aarch64",
        "codex_version": codex_version,
        "clean_before_expected_mcp": False,
        "selected_expected_mcp": True,
        "selected_mcp_plugin_paths_rebased": True,
        "clean_after_expected_mcp": False,
        "ambient_config_and_plugin_tree_unchanged": True,
        "plugin_source_unchanged": True,
        "provider_state_lifecycle_closed": True,
    }
    for key, value in required.items():
        if record.get(key) != value:
            raise SystemExit(f"codex-{phase}:{key}")
    if not record.get("plugin_id") or not record.get("expected_mcp"):
        raise SystemExit(f"codex-{phase}:identity")
    for key in ("codex_provider_sha256", "plugin_source_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(record.get(key, ""))):
            raise SystemExit(f"codex-{phase}:{key}")

if xp.get("interactive_selected_tui_confirmed") is not True:
    raise SystemExit("codex-pretag:interactive")
if xp.get("interactive_expected_mcp_healthy_confirmed") is not True:
    raise SystemExit("codex-pretag:mcp-health")
if xp.get("interactive_no_model_prompt_confirmed") is not True:
    raise SystemExit("codex-pretag:no-model")
if xp.get("post_interactive_clean_confirmed") is not True:
    raise SystemExit("codex-pretag:post-interactive-clean")
for key in ("plugin_id", "expected_mcp", "codex_provider_sha256", "plugin_source_sha256"):
    if xp.get(key) != xd.get(key):
        raise SystemExit(f"codex-drift:{key}")
if xd.get("artifact_sha256") != artifact_sha:
    raise SystemExit("codex-draft-artifact")
if cd.get("artifact_sha256") != xd.get("artifact_sha256"):
    raise SystemExit("draft-artifact-disagreement")
PY

echo "DRAFT_RELEASE_VERIFY_PASS tag=$tag target=$expected artifact_sha256=$artifact_sha"
