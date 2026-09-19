#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: $0 vX.Y.Z EXPECTED_TAG_SOURCE_SHA" >&2
  exit 2
}

fail() {
  printf 'RELEASE_PUBLISH_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

[[ $# -eq 2 ]] || usage
tag=$1
expected_source=$2
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "STABLE_TAG_REQUIRED"
[[ "$expected_source" =~ ^[0-9a-f]{40}$ ]] || fail "EXPECTED_SOURCE_SHA"

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"

for command_name in git gh python3 shasum codex claude; do
  command -v "$command_name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$command_name"
done
gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED"

python3 scripts/release/check-repository-release-policy.py --mode strict >/dev/null || fail "REPOSITORY_TAG_POLICY"
immutable_enabled=$(gh api "repos/y-sor/clean-room-launcher/immutable-releases" --jq .enabled 2>/dev/null) \
  || fail "IMMUTABLE_RELEASE_POLICY_UNVERIFIED"
[[ "$immutable_enabled" == true ]] || fail "IMMUTABLE_RELEASE_POLICY_DISABLED"

remote_source=$(gh api "repos/y-sor/clean-room-launcher/commits/$tag" --jq .sha)
[[ "$remote_source" == "$expected_source" ]] || {
  printf 'REMOTE_TAG_SOURCE=%s EXPECTED=%s\n' "$remote_source" "$expected_source" >&2
  fail "TAG_SOURCE_MISMATCH"
}

release_json=$(gh release view "$tag" --json isDraft,isImmutable,isPrerelease,tagName,name,assets)
is_draft=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())' <<<"$release_json")
is_immutable=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isImmutable"]).lower())' <<<"$release_json")
is_prerelease=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isPrerelease"]).lower())' <<<"$release_json")
tag_name=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["tagName"])' <<<"$release_json")
title=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])' <<<"$release_json")
asset_count=$(python3 -c 'import json,sys; print(len(json.load(sys.stdin)["assets"]))' <<<"$release_json")
[[ "$is_draft" == true ]] || fail "RELEASE_NOT_DRAFT"
[[ "$is_immutable" == false ]] || fail "DRAFT_ALREADY_IMMUTABLE"
[[ "$is_prerelease" == false ]] || fail "UNEXPECTED_PRERELEASE"
[[ "$tag_name" == "$tag" ]] || fail "DRAFT_TAG_MISMATCH"
[[ "$title" == "$tag — Clean Room Launcher" ]] || fail "DRAFT_TITLE_MISMATCH"
[[ "$asset_count" -eq 6 ]] || fail "DRAFT_ASSET_COUNT"

version=${tag#v}
short_head=${expected_source:0:12}
evidence="target/release-evidence/draft-v${version}-${short_head}.json"
[[ -f "$evidence" ]] || fail "DRAFT_SMOKE_EVIDENCE_MISSING"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-publish-guard.XXXXXX")
cleanup() { rm -rf -- "$tmp"; }
trap cleanup EXIT HUP INT TERM
artifact="clean-room-launcher-v${version}-aarch64-apple-darwin.tar.gz"

gh release download "$tag" --dir "$tmp" >/dev/null || fail "DRAFT_ASSET_DOWNLOAD"
[[ "$(find "$tmp" -maxdepth 1 -type f | wc -l | tr -d ' ')" == 6 ]] \
  || fail "DRAFT_ASSET_COUNT_DOWNLOADED"
for name in \
  "$artifact" \
  SHA256SUMS \
  sbom.cdx.json \
  install.sh \
  "$artifact.provenance.sigstore.json" \
  "$artifact.sbom.sigstore.json"; do
  [[ -s "$tmp/$name" ]] || fail "DRAFT_ASSET_MISSING:$name"
done
(
  cd "$tmp"
  shasum -a 256 -c SHA256SUMS
) >/dev/null || fail "DRAFT_CHECKSUMS_ACTION_TIME"

gh attestation verify "$tmp/$artifact" \
  -R y-sor/clean-room-launcher \
  --bundle "$tmp/$artifact.provenance.sigstore.json" \
  --signer-workflow y-sor/clean-room-launcher/.github/workflows/release.yml \
  --source-digest "$expected_source" \
  --source-ref "refs/tags/$tag" \
  --deny-self-hosted-runners >/dev/null || fail "DRAFT_PROVENANCE_ACTION_TIME"
gh attestation verify "$tmp/$artifact" \
  -R y-sor/clean-room-launcher \
  --bundle "$tmp/$artifact.sbom.sigstore.json" \
  --signer-workflow y-sor/clean-room-launcher/.github/workflows/release.yml \
  --source-digest "$expected_source" \
  --source-ref "refs/tags/$tag" \
  --deny-self-hosted-runners >/dev/null || fail "DRAFT_SBOM_ATTESTATION_ACTION_TIME"

current_sha=$(shasum -a 256 "$tmp/$artifact" | awk '{print $1}')

read -r codex_pin claude_plugin_pin < <(
  python3 - <<'PY'
import json
from pathlib import Path
data = json.loads(Path("release/qualification.json").read_text(encoding="utf-8"))
print(
    data["providers"]["codex"]["clean_exact"],
    data["providers"]["claude"]["plugin_activation_exact"],
)
PY
)
version_from_output() {
  "$1" --version 2>&1 | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1
}

# Action-time refresh: keep the mutable-state window immediately before publish short.
python3 scripts/release/check-repository-release-policy.py --mode strict >/dev/null \
  || fail "REPOSITORY_TAG_POLICY_ACTION_TIME"
immutable_enabled=$(gh api "repos/y-sor/clean-room-launcher/immutable-releases" --jq .enabled 2>/dev/null) \
  || fail "IMMUTABLE_RELEASE_POLICY_UNVERIFIED_ACTION_TIME"
[[ "$immutable_enabled" == true ]] || fail "IMMUTABLE_RELEASE_POLICY_DISABLED_ACTION_TIME"
remote_source=$(gh api "repos/y-sor/clean-room-launcher/commits/$tag" --jq .sha)
[[ "$remote_source" == "$expected_source" ]] || fail "TAG_SOURCE_MISMATCH_ACTION_TIME"

codex_executable=$(command -v codex)
claude_executable=$(command -v claude)
codex_version=$(version_from_output "$codex_executable")
claude_version=$(version_from_output "$claude_executable")
[[ "$codex_version" == "$codex_pin" ]] || fail "CODEX_PROVIDER_DRIFT_ACTION_TIME"
[[ "$claude_version" == "$claude_plugin_pin" ]] || fail "CLAUDE_PLUGIN_PROVIDER_DRIFT_ACTION_TIME"
codex_provider_sha=$(shasum -a 256 "$codex_executable" | awk '{print $1}')
claude_provider_sha=$(shasum -a 256 "$claude_executable" | awk '{print $1}')

gh api "repos/y-sor/clean-room-launcher/releases/tags/$tag" > "$tmp/action-release.json" \
  || fail "DRAFT_ACTION_STATE"

python3 - \
  "$evidence" "$version" "$expected_source" "$tag" "$tmp" \
  "$tmp/action-release.json" "$codex_version" "$claude_version" \
  "$codex_provider_sha" "$claude_provider_sha" <<'PY' \
  || fail "DRAFT_SMOKE_EVIDENCE_INVALID"
import hashlib
import json
import pathlib
import sys

(
    evidence_path,
    version,
    source,
    tag,
    assets_dir,
    release_path,
    codex_version,
    claude_version,
    codex_sha,
    claude_sha,
) = sys.argv[1:]

record = json.loads(pathlib.Path(evidence_path).read_text(encoding="utf-8"))
if record.get("schema_version") != "clroom.local-release-smoke.v1":
    raise SystemExit("schema")
if record.get("result") != "PASS" or record.get("phase") != "draft":
    raise SystemExit("result-phase")
if record.get("release_version") != version or record.get("source_head") != source:
    raise SystemExit("identity")
if record.get("release_tag") != tag:
    raise SystemExit("tag")

provider_versions = record.get("provider_versions") or {}
provider_sha = record.get("provider_sha256") or {}
if provider_versions != {"codex": codex_version, "claude": claude_version}:
    raise SystemExit("provider-version-drift")
if provider_sha != {"codex": codex_sha, "claude": claude_sha}:
    raise SystemExit("provider-bytes-drift")

draft_state = record.get("draft_release_state")
if not isinstance(draft_state, dict):
    raise SystemExit("draft-state")
expected_assets = draft_state.get("assets_sha256")
expected_body_sha = draft_state.get("release_body_sha256")
if not isinstance(expected_assets, dict) or len(expected_assets) != 6:
    raise SystemExit("draft-assets")
if not isinstance(expected_body_sha, str) or len(expected_body_sha) != 64:
    raise SystemExit("draft-body")

assets_dir = pathlib.Path(assets_dir)
downloaded = {
    path.name: hashlib.sha256(path.read_bytes()).hexdigest()
    for path in assets_dir.iterdir()
    if path.is_file() and path.name != "action-release.json"
}
if downloaded != expected_assets:
    raise SystemExit("asset-drift")
artifact = f"clean-room-launcher-v{version}-aarch64-apple-darwin.tar.gz"
if record.get("artifact_sha256") != downloaded.get(artifact):
    raise SystemExit("archive-drift")

release = json.loads(pathlib.Path(release_path).read_text(encoding="utf-8"))
if release.get("draft") is not True or release.get("immutable") is not False:
    raise SystemExit("release-state")
if release.get("prerelease") is not False:
    raise SystemExit("prerelease")
if release.get("tag_name") != tag or release.get("name") != f"{tag} — Clean Room Launcher":
    raise SystemExit("release-identity")
body = release.get("body")
if not isinstance(body, str):
    raise SystemExit("release-body")
if hashlib.sha256(body.encode("utf-8")).hexdigest() != expected_body_sha:
    raise SystemExit("release-body-drift")

api_assets = release.get("assets")
if not isinstance(api_assets, list) or len(api_assets) != 6:
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

auto = record.get("automated") or {}
human = record.get("human") or {}
for key in (
    "clean_init_only",
    "selected_init_only",
    "plugin_inventory_qualified",
    "persistent_config_unchanged",
):
    if auto.get(key) is not True:
        raise SystemExit("automated:" + key)
for key in (
    "codex_tui_confirmed",
    "claude_clean_tui_confirmed",
    "claude_clean_selected_skill_absent_confirmed",
    "claude_selected_plugin_tui_confirmed",
    "claude_selected_skill_visible_confirmed",
):
    if human.get(key) is not True:
        raise SystemExit("human:" + key)
if auto.get("model_prompt_sent") is not False or human.get("model_prompt_sent") is not False:
    raise SystemExit("model-prompt")
PY

# Publication is intentionally the last state-changing command after every guard above.
# If the transport fails after GitHub commits publication, reconcile before any retry:
# immutable publication is not safely replayable by assumption.
set +e
gh release edit "$tag" --draft=false --latest --verify-tag >/dev/null
publish_rc=$?
set -e

set +e
after=$(gh release view "$tag" --json isDraft,isImmutable,isPrerelease,tagName,name 2>/dev/null)
readback_rc=$?
set -e
[[ "$readback_rc" -eq 0 && -n "$after" ]] || fail "PUBLISH_OUTCOME_UNKNOWN"

after_draft=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isDraft"]).lower())' <<<"$after")
after_immutable=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isImmutable"]).lower())' <<<"$after")
after_prerelease=$(python3 -c 'import json,sys; print(str(json.load(sys.stdin)["isPrerelease"]).lower())' <<<"$after")
after_tag=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["tagName"])' <<<"$after")
after_title=$(python3 -c 'import json,sys; print(json.load(sys.stdin)["name"])' <<<"$after")

if [[ "$after_draft" == false ]]; then
  [[ "$after_immutable" == true ]] || fail "PUBLISHED_RELEASE_NOT_IMMUTABLE"
  [[ "$after_prerelease" == false ]] || fail "PUBLISHED_RELEASE_UNEXPECTED_PRERELEASE"
  [[ "$after_tag" == "$tag" ]] || fail "PUBLISHED_TAG_MISMATCH"
  [[ "$after_title" == "$tag — Clean Room Launcher" ]] || fail "PUBLISHED_TITLE_MISMATCH"
  if [[ "$publish_rc" -ne 0 ]]; then
    printf 'RELEASE_PUBLISH_RECONCILED tag=%s source=%s artifact_sha256=%s immutable=true\n' \
      "$tag" "$expected_source" "$current_sha"
  else
    printf 'RELEASE_PUBLISH_PASS tag=%s source=%s artifact_sha256=%s immutable=true\n' \
      "$tag" "$expected_source" "$current_sha"
  fi
  exit 0
fi

# The authoritative state is still the exact pre-action Draft. A future explicit
# publish attempt may retry after a fresh maintainer action-time authorization; this invocation
# does not retry automatically.
[[ "$after_draft" == true && "$after_immutable" == false && "$after_prerelease" == false ]] \
  || fail "PUBLISH_OUTCOME_UNKNOWN"
[[ "$after_tag" == "$tag" && "$after_title" == "$tag — Clean Room Launcher" ]] \
  || fail "PUBLISH_OUTCOME_UNKNOWN"
if [[ "$publish_rc" -ne 0 ]]; then
  fail "PUBLISH_NOT_DELIVERED"
fi
fail "PUBLISH_OUTCOME_UNKNOWN"
