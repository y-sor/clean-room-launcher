#!/usr/bin/env bash
set -euo pipefail

fail(){ printf 'DRAFT_RELEASE_VERIFY_BLOCKED:%s\n' "$1" >&2; exit "${2:-1}"; }
[[ $# -eq 2 ]] || fail USAGE 64
tag=$1
expected=$2
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]] || fail TAG
[[ "$expected" =~ ^[0-9a-f]{40}$ ]] || fail EXPECTED_SHA

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"
repository="y-sor/clean-room-launcher"
command -v gh >/dev/null 2>&1 || fail GH_REQUIRED
command -v python3 >/dev/null 2>&1 || fail PYTHON_REQUIRED
gh auth status >/dev/null 2>&1 || fail GH_AUTH_REQUIRED
[[ -z "$(git status --porcelain)" ]] || fail WORKTREE_NOT_CLEAN
[[ "$(git rev-parse HEAD)" == "$expected" ]] || fail HEAD_NOT_EXPECTED

git fetch --quiet origin "refs/tags/$tag:refs/tags/$tag" || fail TAG_FETCH
[[ "$(git cat-file -t "refs/tags/$tag")" == tag ]] || fail ANNOTATED_TAG_REQUIRED
[[ "$(git rev-parse "$tag^{}")" == "$expected" ]] || fail TAG_TARGET
version=${tag#v}
manifest_version=$(python3 - <<'PY'
import tomllib
print(tomllib.load(open("Cargo.toml","rb"))["package"]["version"])
PY
)
[[ "$manifest_version" == "$version" ]] || fail VERSION_MISMATCH

immutable_enabled=$(gh api repos/$repository/immutable-releases --jq .enabled 2>/dev/null) || fail IMMUTABLE_RELEASE_POLICY_UNVERIFIED
[[ "$immutable_enabled" == true ]] || fail IMMUTABLE_RELEASE_POLICY_DISABLED

rules_tmp=$(mktemp "${TMPDIR:-/tmp}/clroom-draft-rules.XXXXXX")
gh api "repos/$repository/rulesets" >"$rules_tmp" || fail RULESET_READ
python3 - "$rules_tmp" <<'PY' || fail TAG_RULESET
import json,subprocess,sys
for item in json.load(open(sys.argv[1],encoding="utf-8")):
    if item.get("target")!="tag" or item.get("enforcement")!="active": continue
    d=json.loads(subprocess.check_output(["gh","api",f"repos/y-sor/clean-room-launcher/rulesets/{item['id']}"],text=True))
    refs=d.get("conditions",{}).get("ref_name",{}).get("include",[])
    types={x.get("type") for x in d.get("rules",[])}
    if "refs/tags/v*" in refs and {"update","deletion"} <= types and not d.get("bypass_actors") and d.get("current_user_can_bypass") in (None,"never"):
        raise SystemExit(0)
raise SystemExit(1)
PY
rm -f "$rules_tmp"

tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-draft-verify.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM
stage="$tmp/stage"
bash scripts/release/resolve-release-stage.sh "$version" "$expected" "$stage" || fail RELEASE_STAGE
python3 scripts/release/stage-manifest.py verify --root "$stage" --version "$version" --source-head "$expected" || fail RELEASE_STAGE_MANIFEST

gh release view "$tag" --json isDraft,isPrerelease,tagName,body >"$tmp/release.json" || fail RELEASE_VIEW
python3 - "$tmp/release.json" "$tag" "$stage/release-notes.md" <<'PY' || fail RELEASE_IDENTITY_OR_NOTES
import json,sys
r=json.load(open(sys.argv[1],encoding="utf-8"))
notes=open(sys.argv[3],encoding="utf-8").read()
if r.get("tagName")!=sys.argv[2] or r.get("isDraft") is not True:
    raise SystemExit(1)
if (r.get("body") or "").rstrip("\r\n") != notes.rstrip("\r\n"):
    raise SystemExit(2)
PY

assets="$tmp/assets"
mkdir -p "$assets"
gh release download "$tag" --dir "$assets" || fail RELEASE_DOWNLOAD
artifact="$assets/clean-room-launcher-v${version}-aarch64-apple-darwin.tar.gz"
test "$(find "$assets" -maxdepth 1 -type f | wc -l | tr -d ' ')" = 6 || fail ASSET_COUNT
for name in "clean-room-launcher-v${version}-aarch64-apple-darwin.tar.gz" SHA256SUMS sbom.cdx.json install.sh; do
  cmp "$stage/$name" "$assets/$name" || fail "STAGED_BYTE_DRIFT:$name"
done
(
  cd "$assets"
  shasum -a 256 -c SHA256SUMS
) >/dev/null || fail DRAFT_CHECKSUMS
provenance="$artifact.provenance.sigstore.json"
sbom="$artifact.sbom.sigstore.json"
[[ -s "$provenance" && -s "$sbom" ]] || fail DRAFT_ATTESTATIONS_MISSING
for subject in "$artifact" "$assets/sbom.cdx.json" "$assets/install.sh"; do
  gh attestation verify "$subject" -R "$repository" --bundle "$provenance" --signer-workflow "$repository/.github/workflows/release.yml" --source-digest "$expected" --source-ref "refs/tags/$tag" --deny-self-hosted-runners >/dev/null || fail "DRAFT_PROVENANCE:$(basename "$subject")"
done
gh attestation verify "$artifact" -R "$repository" --bundle "$sbom" --predicate-type https://cyclonedx.org/bom --signer-workflow "$repository/.github/workflows/release.yml" --source-digest "$expected" --source-ref "refs/tags/$tag" --deny-self-hosted-runners >/dev/null || fail DRAFT_SBOM_ATTESTATION

gh api -X GET "repos/$repository/actions/runs" -f head_sha="$expected" -f event=push -f per_page=100 >"$tmp/runs.json" || fail ACTIONS_QUERY
python3 - "$tmp/runs.json" "$tag" "$expected" <<'PY' || fail TAG_RELEASE_WORKFLOW
import json,sys
data=json.load(open(sys.argv[1],encoding="utf-8")); tag,expected=sys.argv[2:]
runs=[r for r in data.get("workflow_runs",[]) if r.get("name")=="Release" and r.get("path")==".github/workflows/release.yml" and r.get("head_branch")==tag and r.get("head_sha")==expected and r.get("event")=="push"]
if not runs: raise SystemExit("missing")
if any(r.get("status")!="completed" or r.get("conclusion")!="success" for r in runs): raise SystemExit("not-success")
PY

stage_manifest="$stage/release-stage.json"
read -r current_tree review_digest artifact_sha claude_version < <(
python3 - "$stage_manifest" <<'PY'
import json,sys
r=json.load(open(sys.argv[1],encoding="utf-8")); a=r["artifact_name"]
print(r["source_tree"],r["reviewed_content_digest"],r["files"][a],r["providers"]["claude"]["version"])
PY
)
git_common_dir=$(git rev-parse --git-common-dir)
[[ "$git_common_dir" == /* ]] || git_common_dir="$root/$git_common_dir"
evidence_dir=${CLROOM_RELEASE_EVIDENCE_DIR:-"$git_common_dir/clroom-release-evidence"}
claude_stage="$evidence_dir/stage-v${version}-${expected:0:12}.json"
[[ -f "$claude_stage" ]] || fail CLAUDE_STAGE_EVIDENCE_MISSING
python3 - "$claude_stage" "$version" "$expected" "$current_tree" "$review_digest" "$artifact_sha" "$claude_version" <<'PY' || fail CLAUDE_STAGE_EVIDENCE
import json,sys
path,version,head,tree,digest,artifact_sha,provider_version=sys.argv[1:]
r=json.load(open(path,encoding="utf-8"))
required={"schema_version":"clroom.plugin-release-smoke.v3","result":"PASS","phase":"stage","release_version":version,"source_head":head,"source_tree":tree,"reviewed_content_digest":digest,"evidence_binding":"content-addressed-runtime-v1","artifact_sha256":artifact_sha,"platform":"macos-aarch64","claude_version":provider_version,"interactive_selected_tui_confirmed":True,"interactive_no_model_prompt_confirmed":True,"external_ancestor_agents_absent_confirmed":True,"project_agents_retained_confirmed":True,"external_ancestor_agents_sandbox_probe_passed":True,"persistent_config_unchanged":True}
for k,v in required.items():
    if r.get(k)!=v: raise SystemExit(k)
PY

printf 'DRAFT_RELEASE_VERIFY_PASS tag=%s target=%s artifact_sha256=%s\n' "$tag" "$expected" "$artifact_sha"
