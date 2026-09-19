#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage:
  scripts/release/local-release-smoke.sh pretag --plugin-id ID
  scripts/release/local-release-smoke.sh draft --tag vX.Y.Z --plugin-id ID
EOF
  exit 2
}

fail() {
  printf 'LOCAL_RELEASE_SMOKE_BLOCKED:%s\n' "$1" >&2
  exit "${2:-1}"
}

phase=${1:-}
[[ "$phase" == pretag || "$phase" == draft ]] || usage
shift || true

tag=
plugin_id=
while [[ $# -gt 0 ]]; do
  case "$1" in
    --tag) tag=${2:-}; shift 2 ;;
    --plugin-id) plugin_id=${2:-}; shift 2 ;;
    *) usage ;;
  esac
done
[[ -n "$plugin_id" ]] || fail "PLUGIN_ID_REQUIRED"
if [[ "$phase" == draft ]]; then
  [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "STABLE_TAG_REQUIRED"
else
  [[ -z "$tag" ]] || usage
fi

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"

[[ "$(uname -s)" == Darwin ]] || fail "MACOS_REQUIRED"
[[ "$(uname -m)" == arm64 ]] || fail "APPLE_SILICON_REQUIRED"
for command_name in git python3 shasum tar codex claude cargo rustc; do
  command -v "$command_name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$command_name"
done

source_head=
if [[ "$phase" == draft ]]; then
  [[ -z "$(git status --porcelain)" ]] || fail "WORKTREE_NOT_CLEAN"
  git remote get-url origin >/dev/null 2>&1 || fail "ORIGIN_MISSING"
  git fetch --quiet origin "refs/tags/$tag:refs/tags/$tag" || fail "TAG_FETCH"
  source_head=$(git rev-list -n1 "$tag")
  local_head=$(git rev-parse HEAD)
  [[ "$local_head" == "$source_head" ]] || {
    printf 'LOCAL_HEAD=%s\nTAG_SOURCE=%s\n' "$local_head" "$source_head" >&2
    fail "CHECKOUT_NOT_TAG_SOURCE"
  }
fi

python3 scripts/release/check-provider-version-sync.py >/dev/null || fail "PROVIDER_VERSION_REPO_DRIFT"

read -r codex_pin claude_clean_pin claude_plugin_pin < <(
  python3 - <<'PY'
import json
from pathlib import Path
data = json.loads(Path("release/qualification.json").read_text(encoding="utf-8"))
print(
    data["providers"]["codex"]["clean_exact"],
    data["providers"]["claude"]["clean_exact"],
    data["providers"]["claude"]["plugin_activation_exact"],
)
PY
)

version_from_output() {
  "$1" --version 2>&1 | grep -Eo '[0-9]+\.[0-9]+\.[0-9]+' | head -1
}

codex_executable=$(command -v codex)
claude_executable=$(command -v claude)
codex_version=$(version_from_output "$codex_executable")
claude_version=$(version_from_output "$claude_executable")
[[ -n "$codex_version" ]] || fail "CODEX_VERSION_UNKNOWN"
[[ -n "$claude_version" ]] || fail "CLAUDE_VERSION_UNKNOWN"
codex_provider_sha=$(shasum -a 256 "$codex_executable" | awk '{print $1}')
claude_provider_sha=$(shasum -a 256 "$claude_executable" | awk '{print $1}')

if [[ "$codex_version" != "$codex_pin" ]]; then
  printf 'PROVIDER_REFRESH_REQUIRED provider=codex installed=%s release_pin=%s\n'     "$codex_version" "$codex_pin" >&2
  fail "CODEX_PROVIDER_DRIFT" 20
fi
if [[ "$claude_version" != "$claude_plugin_pin" ]]; then
  printf 'PROVIDER_REFRESH_REQUIRED provider=claude capability=plugin_activation installed=%s plugin_pin=%s baseline_clean_pin=%s\n' \
    "$claude_version" "$claude_plugin_pin" "$claude_clean_pin" >&2
  fail "CLAUDE_PLUGIN_PROVIDER_DRIFT" 21
fi

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-local-release-smoke.XXXXXX")
cleanup() {
  rm -rf -- "$tmp"
}
trap cleanup EXIT HUP INT TERM

artifact=
source_head=${source_head:-}
release_version=
artifact_dir="$tmp/assets"
draft_state_file="$tmp/draft-release-state.json"
printf '%s\n' '{"release_body_sha256":null,"assets_sha256":{}}' > "$draft_state_file"

if [[ "$phase" == pretag ]]; then
  [[ -z "$(git status --porcelain)" ]] || fail "WORKTREE_NOT_CLEAN"
  git remote get-url origin >/dev/null 2>&1 || fail "ORIGIN_MISSING"
  git fetch --quiet --no-tags origin main
  source_head=$(git rev-parse HEAD)
  remote_main=$(git rev-parse FETCH_HEAD)
  [[ "$source_head" == "$remote_main" ]] || {
    printf 'LOCAL_HEAD=%s\nREMOTE_MAIN=%s\n' "$source_head" "$remote_main" >&2
    fail "HEAD_NOT_ACCEPTED_MAIN"
  }
  release_version=$(python3 - <<'PY'
import tomllib
with open("Cargo.toml", "rb") as handle:
    print(tomllib.load(handle)["package"]["version"])
PY
  )
  mkdir -p "$artifact_dir"
  cargo fetch --locked >/dev/null
  build_log="$tmp/build.log"
  CLROOM_SOURCE_COMMIT="$source_head" CLROOM_TARGET=''     ./packaging/build-artifacts.sh "$artifact_dir" >"$build_log"
  artifact=$(sed -n 's/^ARTIFACT=//p' "$build_log" | tail -1)
  [[ -n "$artifact" && -f "$artifact" ]] || fail "ARTIFACT_MISSING"
else
  command -v gh >/dev/null 2>&1 || fail "GH_REQUIRED_FOR_DRAFT"
  gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED_FOR_DRAFT"
  release_version=${tag#v}
  is_draft=$(gh release view "$tag" --json isDraft --jq '.isDraft')
  tag_name=$(gh release view "$tag" --json tagName --jq '.tagName')
  title=$(gh release view "$tag" --json name --jq '.name')
  [[ "$is_draft" == true ]] || fail "RELEASE_NOT_DRAFT"
  [[ "$tag_name" == "$tag" ]] || fail "DRAFT_TAG_MISMATCH"
  [[ "$title" == "$tag — Clean Room Launcher" ]] || fail "DRAFT_TITLE_MISMATCH"

  mkdir -p "$artifact_dir"
  gh release download "$tag" --dir "$artifact_dir"
  expected_archive="$artifact_dir/clean-room-launcher-v${release_version}-aarch64-apple-darwin.tar.gz"
  [[ -f "$expected_archive" ]] || fail "DRAFT_ARCHIVE_MISSING"
  artifact="$expected_archive"
  [[ -f "$artifact_dir/SHA256SUMS" ]] || fail "DRAFT_SHA256SUMS_MISSING"
  [[ -f "$artifact_dir/sbom.cdx.json" ]] || fail "DRAFT_SBOM_MISSING"
  [[ -f "$artifact_dir/install.sh" ]] || fail "DRAFT_INSTALLER_MISSING"
  provenance="$artifact.provenance.sigstore.json"
  sbom_bundle="$artifact.sbom.sigstore.json"
  [[ -s "$provenance" && -s "$sbom_bundle" ]] || fail "DRAFT_ATTESTATION_BUNDLE_MISSING"
  [[ "$(find "$artifact_dir" -maxdepth 1 -type f | wc -l | tr -d ' ')" == 6 ]]     || fail "DRAFT_ASSET_COUNT"
  (
    cd "$artifact_dir"
    shasum -a 256 -c SHA256SUMS
  ) >/dev/null || fail "DRAFT_CHECKSUMS"

  gh attestation verify "$artifact"     -R y-sor/clean-room-launcher     --bundle "$provenance"     --signer-workflow y-sor/clean-room-launcher/.github/workflows/release.yml     --source-digest "$source_head"     --source-ref "refs/tags/$tag"     --deny-self-hosted-runners >/dev/null || fail "DRAFT_PROVENANCE"
  gh attestation verify "$artifact"     -R y-sor/clean-room-launcher     --bundle "$sbom_bundle"     --signer-workflow y-sor/clean-room-launcher/.github/workflows/release.yml     --source-digest "$source_head"     --source-ref "refs/tags/$tag"     --deny-self-hosted-runners >/dev/null || fail "DRAFT_SBOM_ATTESTATION"

  gh release view "$tag" --json body > "$tmp/draft-release.json" \
    || fail "DRAFT_RELEASE_BODY"
  python3 - "$tmp/draft-release.json" "$artifact_dir" "$draft_state_file" <<'PY' \
    || fail "DRAFT_STATE_SEAL"
import hashlib
import json
import pathlib
import sys

release_path, assets_dir, output = sys.argv[1:]
release = json.loads(pathlib.Path(release_path).read_text(encoding="utf-8"))
body = release.get("body")
if not isinstance(body, str) or not body.strip():
    raise SystemExit("release-body")
assets = {}
for path in sorted(pathlib.Path(assets_dir).iterdir()):
    if path.is_file():
        assets[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
if len(assets) != 6:
    raise SystemExit("asset-count")
state = {
    "release_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
    "assets_sha256": assets,
}
pathlib.Path(output).write_text(
    json.dumps(state, sort_keys=True, separators=(",", ":")) + "\n",
    encoding="utf-8",
)
PY

fi

python3 packaging/verify-artifact.py "$artifact" >/dev/null || fail "ARTIFACT_METADATA"
artifact_sha=$(shasum -a 256 "$artifact" | awk '{print $1}')

extract_root="$tmp/extracted"
mkdir -p "$extract_root"
tar -xzf "$artifact" -C "$extract_root"
archive_root=$(find "$extract_root" -mindepth 1 -maxdepth 1 -type d -print -quit)
[[ -n "$archive_root" ]] || fail "ARCHIVE_ROOT_MISSING"
clroom="$archive_root/bin/clroom"
[[ -x "$clroom" ]] || fail "ARCHIVE_CLROOM_MISSING"

version_file="$archive_root/VERSION"
[[ -f "$version_file" ]] || fail "ARCHIVE_VERSION_MISSING"
grep -Fqx "version=$release_version" "$version_file" || fail "ARCHIVE_VERSION_MISMATCH"
grep -Fqx "source_commit=$source_head" "$version_file" || fail "ARCHIVE_SOURCE_MISMATCH"
grep -Fqx "target=aarch64-apple-darwin" "$version_file" || fail "ARCHIVE_TARGET_MISMATCH"

fingerprint_config() {
  python3 - <<'PY'
import hashlib
import os

paths = [
    "~/.codex/config.toml",
    "~/.codex/AGENTS.md",
    "~/.claude/settings.json",
    "~/.claude/settings.local.json",
    "~/.claude/plugins/installed_plugins.json",
    "~/.claude/plugins/known_marketplaces.json",
]
digest = hashlib.sha256()
for raw in paths:
    path = os.path.expanduser(raw)
    digest.update(raw.encode())
    digest.update(b"\0")
    if os.path.isfile(path):
        with open(path, "rb") as handle:
            digest.update(handle.read())
    else:
        digest.update(b"<missing>")
    digest.update(b"\0")
print(digest.hexdigest())
PY
}

before=$(fingerprint_config)

"$clroom" --version >/dev/null || fail "CLROOM_VERSION"
"$clroom" --help >/dev/null || fail "CLROOM_HELP"
"$clroom" codex --version >/dev/null || fail "CODEX_VERSION_PATH"
"$clroom" claude --version >/dev/null || fail "CLAUDE_VERSION_PATH"

info_json="$tmp/plugin-info.json"
"$clroom" --output json info claude "plugin:$plugin_id" >"$info_json" 2>"$tmp/plugin-info.err"   || fail "PLUGIN_INFO_FAILED"

python3 - "$info_json" "$plugin_id" <<'PY' || fail "PLUGIN_NOT_RELEASE_QUALIFIED"
import json
import sys

path, plugin_id = sys.argv[1:]
with open(path, encoding="utf-8") as handle:
    data = json.load(handle)
entries = data.get("native_entries") or []
if len(entries) != 1:
    raise SystemExit("entry-count")
entry = entries[0]
native = entry.get("native") or {}
if native.get("id") != plugin_id:
    raise SystemExit("plugin-id")
if entry.get("installation") != "installed":
    raise SystemExit("installation")
if entry.get("selection") != "selectable":
    raise SystemExit("selection")
if entry.get("qualification") != "qualified":
    raise SystemExit("qualification")
if entry.get("activation_policy") != "atomic_bundle":
    raise SystemExit("activation-policy")
if entry.get("conflicts"):
    raise SystemExit("conflicts")
kinds = sorted({
    item.get("kind")
    for item in (entry.get("effective_components") or [])
    if isinstance(item, dict)
})
if kinds != ["skill"]:
    raise SystemExit("surface")
PY

set +e
"$clroom" claude --init-only >"$tmp/clean-init.out" 2>"$tmp/clean-init.err"
clean_init_rc=$?
"$clroom" claude --with="plugin:$plugin_id" --init-only \
  >"$tmp/selected-init.out" 2>"$tmp/selected-init.err"
selected_init_rc=$?
set -e
[[ "$clean_init_rc" -eq 0 ]] || fail "CLAUDE_CLEAN_INIT_ONLY"
[[ "$selected_init_rc" -eq 0 ]] || fail "CLAUDE_SELECTED_INIT_ONLY"

after_automated=$(fingerprint_config)
[[ "$before" == "$after_automated" ]] || fail "PERSISTENT_CONFIG_CHANGED_AUTOMATED"

[[ -t 0 && -t 1 ]] || fail "INTERACTIVE_TTY_REQUIRED"

echo
echo "========================================"
echo "MANUAL CODEX TUI SMOKE"
echo "No model prompt. Wait for the normal TUI, then exit normally."
echo "========================================"
echo
set +e
"$clroom" codex --no-alt-screen
codex_tui_rc=$?
set -e
[[ "$codex_tui_rc" -eq 0 ]] || fail "CODEX_TUI_EXIT"
printf 'Confirm Codex TUI opened normally and no model request was sent [y/N]: '
read -r codex_confirm
[[ "$codex_confirm" == y || "$codex_confirm" == Y ]] || fail "CODEX_TUI_NOT_CONFIRMED"

echo
echo "========================================"
echo "MANUAL CLEAN CLAUDE TUI SMOKE"
echo "No model prompt. Wait for the normal clean TUI."
echo "Type the selected plugin skill prefix and confirm it is NOT offered, then exit normally."
echo "========================================"
echo
set +e
"$clroom" claude
claude_clean_tui_rc=$?
set -e
[[ "$claude_clean_tui_rc" -eq 0 ]] || fail "CLAUDE_CLEAN_TUI_EXIT"
printf 'Confirm clean Claude TUI opened, selected plugin skill was absent, and no model request was sent [y/N]: '
read -r claude_clean_confirm
[[ "$claude_clean_confirm" == y || "$claude_clean_confirm" == Y ]] || fail "CLAUDE_CLEAN_TUI_NOT_CONFIRMED"

echo
echo "========================================"
echo "MANUAL CLAUDE SELECTED-PLUGIN TUI SMOKE"
echo "No model prompt. Wait for the normal TUI."
echo "Type the selected plugin skill prefix and confirm it IS offered, then exit normally."
echo "Selected plugin: $plugin_id"
echo "========================================"
echo
set +e
"$clroom" claude --with="plugin:$plugin_id"
claude_tui_rc=$?
set -e
[[ "$claude_tui_rc" -eq 0 ]] || fail "CLAUDE_SELECTED_TUI_EXIT"
printf 'Confirm selected-plugin Claude TUI opened, selected skill was visible, and no model request was sent [y/N]: '
read -r claude_confirm
[[ "$claude_confirm" == y || "$claude_confirm" == Y ]] || fail "CLAUDE_TUI_NOT_CONFIRMED"

after=$(fingerprint_config)
[[ "$before" == "$after" ]] || fail "PERSISTENT_CONFIG_CHANGED_INTERACTIVE"

evidence_dir="$root/target/release-evidence"
mkdir -p "$evidence_dir"
short_head=${source_head:0:12}
evidence="$evidence_dir/${phase}-v${release_version}-${short_head}.json"

python3 -   "$evidence" "$phase" "$release_version" "$source_head" "$artifact_sha"   "$codex_version" "$claude_version" "$codex_provider_sha" "$claude_provider_sha" \
  "$plugin_id" "$clean_init_rc" "$selected_init_rc" "$codex_tui_rc" "$claude_clean_tui_rc" \
  "$claude_tui_rc" "$tag" "$draft_state_file" <<'PY'
import datetime
import json
import sys

(
    output,
    phase,
    version,
    source,
    artifact_sha,
    codex,
    claude,
    codex_provider_sha,
    claude_provider_sha,
    plugin_id,
    clean_init_rc,
    selected_init_rc,
    codex_tui_rc,
    claude_clean_tui_rc,
    claude_tui_rc,
    tag,
    draft_state_path,
) = sys.argv[1:]

draft_state = json.loads(
    open(draft_state_path, encoding="utf-8").read()
)

record = {
    "schema_version": "clroom.local-release-smoke.v1",
    "result": "PASS",
    "phase": phase,
    "release_version": version,
    "source_head": source,
    "artifact_sha256": artifact_sha,
    "platform": "macos-aarch64",
    "provider_versions": {"codex": codex, "claude": claude},
    "provider_sha256": {
        "codex": codex_provider_sha,
        "claude": claude_provider_sha,
    },
    "claude_plugin_id": plugin_id,
    "automated": {
        "clean_init_only": True,
        "selected_init_only": True,
        "plugin_inventory_qualified": True,
        "persistent_config_unchanged": True,
        "model_prompt_sent": False,
        "clean_init_only_rc": int(clean_init_rc),
        "selected_init_only_rc": int(selected_init_rc),
    },
    "human": {
        "codex_tui_confirmed": True,
        "claude_clean_tui_confirmed": True,
        "claude_clean_selected_skill_absent_confirmed": True,
        "claude_selected_plugin_tui_confirmed": True,
        "claude_selected_skill_visible_confirmed": True,
        "model_prompt_sent": False,
        "codex_tui_exit_code": int(codex_tui_rc),
        "claude_clean_tui_exit_code": int(claude_clean_tui_rc),
        "claude_selected_tui_exit_code": int(claude_tui_rc),
    },
    "release_tag": tag or None,
    "draft_release_state": draft_state if phase == "draft" else None,
    "observed_at_utc": datetime.datetime.now(datetime.timezone.utc)
    .replace(microsecond=0)
    .isoformat()
    .replace("+00:00", "Z"),
}
with open(output, "w", encoding="utf-8") as handle:
    json.dump(record, handle, sort_keys=True, indent=2)
    handle.write("\n")
PY

echo
echo "========================================"
echo "LOCAL_RELEASE_SMOKE=PASS"
echo "PHASE=$phase"
echo "SOURCE_HEAD=$source_head"
echo "ARTIFACT_SHA256=$artifact_sha"
echo "CODEX_VERSION=$codex_version"
echo "CODEX_PROVIDER_SHA256=$codex_provider_sha"
echo "CLAUDE_VERSION=$claude_version"
echo "CLAUDE_PROVIDER_SHA256=$claude_provider_sha"
echo "PLUGIN_ID=$plugin_id"
echo "CLEAN_INIT_ONLY_RC=$clean_init_rc"
echo "SELECTED_INIT_ONLY_RC=$selected_init_rc"
echo "PERSISTENT_CONFIG_UNCHANGED=YES"
echo "EVIDENCE_FILE=${evidence#$root/}"
echo "========================================"
