#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: scripts/release/local-plugin-activation-smoke.sh pretag --plugin-id ID" >&2
  echo "       scripts/release/local-plugin-activation-smoke.sh draft --tag vX.Y.Z --plugin-id ID" >&2
  exit 64
}

fail() {
  echo "PLUGIN_RELEASE_SMOKE_BLOCKED:$1" >&2
  exit "${2:-1}"
}

phase=${1:-}
[[ "$phase" == "pretag" || "$phase" == "draft" ]] || usage
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
if [[ "$phase" == "draft" ]]; then
  [[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail "STABLE_TAG_REQUIRED"
else
  [[ -z "$tag" ]] || usage
fi

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"

[[ "$(uname -s)" == "Darwin" ]] || fail "MACOS_REQUIRED"
[[ "$(uname -m)" == "arm64" ]] || fail "APPLE_SILICON_REQUIRED"
for name in git cargo python3 claude shasum tar; do
  command -v "$name" >/dev/null 2>&1 || fail "COMMAND_MISSING:$name"
done
[[ -z "$(git status --porcelain)" ]] || fail "WORKTREE_NOT_CLEAN"

version=$(python3 - <<'PY'
import tomllib
with open("Cargo.toml", "rb") as handle:
    print(tomllib.load(handle)["package"]["version"])
PY
)
head=$(git rev-parse HEAD)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-plugin-release-smoke.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM

artifact=
source_head=
assets="$tmp/assets"
mkdir -p "$assets"

if [[ "$phase" == "pretag" ]]; then
  git fetch --quiet --no-tags origin main
  source_head=$(git rev-parse FETCH_HEAD)
  [[ "$head" == "$source_head" ]] || fail "HEAD_NOT_ACCEPTED_MAIN"
  python3 scripts/release/check-release-contract.py --report >/dev/null     || fail "RELEASE_CONTRACT"

  cargo fetch --locked >/dev/null
  CLROOM_SOURCE_COMMIT="$source_head" CLROOM_TARGET=''     ./packaging/build-artifacts.sh "$assets" >"$tmp/build.log"
  artifact=$(sed -n 's/^ARTIFACT=//p' "$tmp/build.log" | tail -1)
  [[ -n "$artifact" && -f "$artifact" ]] || fail "ARTIFACT_MISSING"
else
  command -v gh >/dev/null 2>&1 || fail "GH_REQUIRED"
  gh auth status >/dev/null 2>&1 || fail "GH_AUTH_REQUIRED"
  git fetch --quiet origin "refs/tags/$tag:refs/tags/$tag"
  source_head=$(git rev-list -n 1 "$tag")
  [[ "$head" == "$source_head" ]] || fail "HEAD_NOT_TAG_SOURCE"
  [[ "${tag#v}" == "$version" ]] || fail "TAG_VERSION_MISMATCH"
  [[ "$(gh release view "$tag" --json isDraft --jq .isDraft)" == "true" ]]     || fail "RELEASE_NOT_DRAFT"

  gh release download "$tag" --dir "$assets"
  artifact="$assets/clean-room-launcher-${tag}-aarch64-apple-darwin.tar.gz"
  [[ -f "$artifact" ]] || fail "DRAFT_ARCHIVE_MISSING"
  [[ -f "$assets/SHA256SUMS" ]] || fail "DRAFT_SHA256SUMS_MISSING"
  (
    cd "$assets"
    shasum -a 256 -c SHA256SUMS
  ) >/dev/null || fail "DRAFT_CHECKSUMS"

  provenance="$artifact.provenance.sigstore.json"
  sbom="$artifact.sbom.sigstore.json"
  [[ -s "$provenance" && -s "$sbom" ]] || fail "DRAFT_ATTESTATION_BUNDLE_MISSING"
  gh attestation verify "$artifact"     -R y-sor/clean-room-launcher     --bundle "$provenance"     --signer-workflow y-sor/clean-room-launcher/.github/workflows/release.yml     --source-digest "$source_head"     --source-ref "refs/tags/$tag"     --deny-self-hosted-runners >/dev/null || fail "DRAFT_PROVENANCE"
  gh attestation verify "$artifact"     -R y-sor/clean-room-launcher     --bundle "$sbom"     --signer-workflow y-sor/clean-room-launcher/.github/workflows/release.yml     --source-digest "$source_head"     --source-ref "refs/tags/$tag"     --deny-self-hosted-runners >/dev/null || fail "DRAFT_SBOM_ATTESTATION"
fi

python3 packaging/verify-artifact.py "$artifact" >/dev/null || fail "ARTIFACT_METADATA"
artifact_sha=$(shasum -a 256 "$artifact" | awk '{print $1}')

mkdir "$tmp/unpack"
tar -xzf "$artifact" -C "$tmp/unpack"
archive_root=$(find "$tmp/unpack" -mindepth 1 -maxdepth 1 -type d -print -quit)
[[ -n "$archive_root" ]] || fail "ARCHIVE_ROOT_MISSING"
clroom="$archive_root/bin/clroom"
[[ -x "$clroom" ]] || fail "ARCHIVE_CLROOM_MISSING"
grep -Fqx "version=$version" "$archive_root/VERSION" || fail "ARCHIVE_VERSION"
grep -Fqx "source_commit=$source_head" "$archive_root/VERSION" || fail "ARCHIVE_SOURCE"

registry="$HOME/.claude/plugins/installed_plugins.json"
[[ -f "$registry" ]] || fail "PLUGIN_REGISTRY_MISSING"

fingerprint() {
python3 <<'PY'
import hashlib, os
paths=[
    "~/.claude/settings.json",
    "~/.claude/settings.local.json",
    "~/.claude/plugins/installed_plugins.json",
    "~/.claude/plugins/known_marketplaces.json",
]
h=hashlib.sha256()
for raw in paths:
    p=os.path.expanduser(raw)
    h.update(raw.encode()+b"\0")
    if os.path.isfile(p):
        with open(p,"rb") as f: h.update(f.read())
    else:
        h.update(b"<missing>")
    h.update(b"\0")
print(h.hexdigest())
PY
}

before=$(fingerprint)
"$clroom" --output json info claude "plugin:$plugin_id" >"$tmp/info.json" 2>"$tmp/info.err"   || fail "PLUGIN_INFO"

set +e
"$clroom" claude -p --output-format stream-json --verbose "Reply exactly UNUSED."   >"$tmp/clean.jsonl" 2>"$tmp/clean.err"
clean_rc=$?
"$clroom" claude --with="plugin:$plugin_id" -p --output-format stream-json --verbose   "Reply exactly UNUSED." >"$tmp/selected.jsonl" 2>"$tmp/selected.err"
selected_rc=$?
set -e

after=$(fingerprint)
[[ "$before" == "$after" ]] || fail "PERSISTENT_CONFIG_CHANGED"

python3 - "$registry" "$plugin_id" "$tmp/info.json" "$tmp/clean.jsonl" "$tmp/selected.jsonl" <<'PY'   || fail "AUTOMATED_PLUGIN_E2E"
import json, os, sys
registry_path, plugin_id, info_path, clean_path, selected_path=sys.argv[1:]

registry=json.load(open(registry_path,encoding="utf-8"))
installed=registry.get("plugins",{})

def roots_for(pid):
    roots=[]
    for record in installed.get(pid,[]) if isinstance(installed.get(pid,[]),list) else []:
        if isinstance(record,dict):
            path=record.get("installPath")
            if isinstance(path,str) and os.path.isdir(path):
                roots.append(os.path.realpath(path))
    return sorted(set(roots))

if len(roots_for(plugin_id)) != 1:
    raise SystemExit("plugin-root-not-exact")

info=json.load(open(info_path,encoding="utf-8"))
entries=info.get("native_entries") or []
if len(entries) != 1:
    raise SystemExit("info-entry-count")
entry=entries[0]
native=entry.get("native") or {}
kinds=sorted({
    item.get("kind")
    for item in (entry.get("effective_components") or [])
    if isinstance(item,dict)
})
if not (
    native.get("id")==plugin_id
    and entry.get("installation")=="installed"
    and entry.get("selection")=="selectable"
    and entry.get("qualification")=="qualified"
    and entry.get("activation_policy")=="atomic_bundle"
    and not (entry.get("conflicts") or [])
    and kinds==["skill"]
):
    raise SystemExit("plugin-not-qualified-skill-only")

def read_init(path):
    init=None
    with open(path,encoding="utf-8") as handle:
        for raw in handle:
            try: obj=json.loads(raw)
            except Exception: continue
            if obj.get("type")=="system" and obj.get("subtype")=="init":
                init=obj
    return init

clean=read_init(clean_path)
selected=read_init(selected_path)
if clean is None or selected is None:
    raise SystemExit("missing-system-init")

def matches(plugin,pid):
    name=pid.rsplit("@",1)[0]
    roots=roots_for(pid)
    if isinstance(plugin,str):
        return plugin in (pid,name) or pid in plugin or (
            os.path.isabs(plugin) and os.path.realpath(plugin) in roots
        )
    if not isinstance(plugin,dict):
        return False
    for key in ("name","id","plugin_id","source"):
        value=plugin.get(key)
        if isinstance(value,str) and (value in (pid,name) or pid in value):
            return True
    path=plugin.get("path")
    return isinstance(path,str) and os.path.isabs(path) and os.path.realpath(path) in roots

clean_plugins=clean.get("plugins") or []
selected_plugins=selected.get("plugins") or []
if any(matches(p,plugin_id) for p in clean_plugins):
    raise SystemExit("target-present-in-clean")
if not any(matches(p,plugin_id) for p in selected_plugins):
    raise SystemExit("target-absent-in-selected")
if selected.get("plugin_errors"):
    raise SystemExit("selected-plugin-errors")

for pid in installed:
    if pid==plugin_id: continue
    clean_has=any(matches(p,pid) for p in clean_plugins)
    selected_has=any(matches(p,pid) for p in selected_plugins)
    if selected_has and not clean_has:
        raise SystemExit("new-sibling-plugin:"+pid)

print("AUTOMATED_PLUGIN_E2E=PASS")
PY

interactive=false
if [[ "$phase" == "pretag" ]]; then
  [[ -t 0 && -t 1 ]] || fail "INTERACTIVE_TTY_REQUIRED"
  echo
  echo "=== INTERACTIVE SELECTED-PLUGIN TUI ==="
  echo "Do not send a model prompt."
  echo "Confirm the normal Claude TUI opens and the selected plugin skill is visible in autocomplete."
  echo "Exit normally with /exit."
  echo
  "$clroom" claude --with="plugin:$plugin_id" || fail "SELECTED_TUI_EXIT"
  printf 'TUI opened normally and selected plugin skill was visible [y/N]: '
  read -r answer
  [[ "$answer" == "y" || "$answer" == "Y" ]] || fail "SELECTED_TUI_NOT_CONFIRMED"
  interactive=true
  [[ "$before" == "$(fingerprint)" ]] || fail "PERSISTENT_CONFIG_CHANGED_INTERACTIVE"
fi

evidence_dir="$root/target/release-evidence"
mkdir -p "$evidence_dir"
short=${source_head:0:12}
evidence="$evidence_dir/${phase}-v${version}-${short}.json"
python3 - "$evidence" "$phase" "$version" "$source_head" "$artifact_sha"   "$plugin_id" "$clean_rc" "$selected_rc" "$interactive" "$(claude --version 2>&1 | head -1)" <<'PY'
import datetime, json, sys
output,phase,version,source,artifact_sha,plugin_id,clean_rc,selected_rc,interactive,claude_version=sys.argv[1:]
record={
  "schema_version":"clroom.plugin-release-smoke.v1",
  "result":"PASS",
  "phase":phase,
  "release_version":version,
  "source_head":source,
  "artifact_sha256":artifact_sha,
  "platform":"macos-aarch64",
  "claude_version_output":claude_version,
  "plugin_id":plugin_id,
  "clean_system_init":True,
  "selected_system_init":True,
  "clean_target_plugin":False,
  "selected_target_plugin":True,
  "new_sibling_plugins":0,
  "selected_plugin_errors":0,
  "persistent_config_unchanged":True,
  "interactive_selected_tui_confirmed": interactive=="true",
  "model_prompt_sent":False,
  "clean_provider_rc":int(clean_rc),
  "selected_provider_rc":int(selected_rc),
  "observed_at_utc":datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00","Z"),
}
with open(output,"w",encoding="utf-8") as f:
    json.dump(record,f,sort_keys=True,indent=2)
    f.write("\n")
PY

echo "PLUGIN_RELEASE_SMOKE=PASS"
echo "PHASE=$phase"
echo "SOURCE_HEAD=$source_head"
echo "ARTIFACT_SHA256=$artifact_sha"
echo "PLUGIN_ID=$plugin_id"
echo "CLEAN_PROVIDER_RC=$clean_rc"
echo "SELECTED_PROVIDER_RC=$selected_rc"
echo "PERSISTENT_CONFIG_UNCHANGED=YES"
echo "EVIDENCE_FILE=${evidence#$root/}"
