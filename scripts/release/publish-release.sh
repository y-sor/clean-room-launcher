#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "usage: CLROOM_OWNER_PUBLISH_APPROVED=YES:<tag>:<sha> bash scripts/release/publish-release.sh <tag> <expected-sha>" >&2
  exit 64
}

[[ $# -eq 2 ]] || usage
tag=$1
expected=$2
[[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+(-rc\.[0-9]+)?$ ]] || usage
[[ $expected =~ ^[0-9a-f]{40}$ ]] || usage
[[ ${CLROOM_OWNER_PUBLISH_APPROVED:-} == "YES:$tag:$expected" ]] || {
  echo "PUBLISH_GATE_BLOCKED:OWNER_APPROVAL_TOKEN" >&2
  exit 65
}

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd -P)
cd "$root"
repository="y-sor/clean-room-launcher"
version=${tag#v}

for name in git gh python3; do
  command -v "$name" >/dev/null 2>&1 || {
    echo "PUBLISH_GATE_BLOCKED:COMMAND_MISSING:$name" >&2
    exit 74
  }
done
gh auth status >/dev/null 2>&1 || {
  echo "PUBLISH_GATE_BLOCKED:GH_AUTH_REQUIRED" >&2
  exit 74
}
git diff --quiet
git diff --cached --quiet
git fetch --quiet origin main
[[ "$(git rev-parse FETCH_HEAD)" == "$expected" ]] || {
  echo "PUBLISH_GATE_BLOCKED:MAIN_DRIFT" >&2
  exit 66
}
[[ "$(git rev-parse HEAD)" == "$expected" ]] || {
  echo "PUBLISH_GATE_BLOCKED:LOCAL_HEAD" >&2
  exit 67
}

bash scripts/release/verify-draft-release.sh "$tag" "$expected" || {
  echo "PUBLISH_GATE_BLOCKED:DRAFT_VERIFY" >&2
  exit 70
}

source scripts/release/provider-pins.sh
source_tree=$(git rev-parse 'HEAD^{tree}')
review_digest=$(python3 - "$version" <<'PY'
import json, sys
with open(f"reports/release/v{sys.argv[1]}-review.json", encoding="utf-8") as handle:
    print(json.load(handle)["reviewed_content_digest"])
PY
)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/clroom-publish.XXXXXX")
trap 'rm -rf -- "$tmp"' EXIT HUP INT TERM
bash scripts/release/resolve-pretag-stage.sh "$version" "$expected" "$tmp/stage" || {
  echo "PUBLISH_GATE_BLOCKED:PRETAG_STAGE" >&2
  exit 70
}
python3 scripts/release/verify-pretag-stage.py \
  --dir "$tmp/stage" --version "$version" --source-head "$expected" \
  --source-tree "$source_tree" --reviewed-content-digest "$review_digest" \
  --codex-version "$CODEX_VERSION" --claude-version "$CLAUDE_VERSION" || {
  echo "PUBLISH_GATE_BLOCKED:PRETAG_BINDING" >&2
  exit 70
}
python3 scripts/release/verify-publishable-surface.py \
  --dir "$tmp/stage" --version "$version" --source-head "$expected" \
  --source-tree "$source_tree" --codex-version "$CODEX_VERSION" \
  --claude-version "$CLAUDE_VERSION" || {
  echo "PUBLISH_GATE_BLOCKED:PUBLISHABLE_SURFACE" >&2
  exit 70
}

immutable_enabled=$(gh api "repos/$repository/immutable-releases" --jq .enabled 2>/dev/null) || {
  echo "PUBLISH_GATE_BLOCKED:IMMUTABLE_POLICY_UNVERIFIED" >&2
  exit 74
}
[[ "$immutable_enabled" == true ]] || {
  echo "PUBLISH_GATE_BLOCKED:IMMUTABLE_POLICY_DISABLED" >&2
  exit 74
}

git fetch --quiet --force origin "refs/tags/$tag:refs/tags/$tag"
[[ "$(git cat-file -t "refs/tags/$tag")" == tag ]] || {
  echo "PUBLISH_GATE_BLOCKED:ANNOTATED_TAG" >&2
  exit 70
}
[[ "$(git rev-parse "refs/tags/$tag^{}")" == "$expected" ]] || {
  echo "PUBLISH_GATE_BLOCKED:TAG_TARGET" >&2
  exit 70
}

gh release view "$tag" --json tagName,name,isDraft,isPrerelease,body,assets >"$tmp/release.json" || {
  echo "PUBLISH_GATE_BLOCKED:RELEASE_QUERY" >&2
  exit 70
}
python3 - "$tmp/release.json" "$tmp/stage/publish-preview.json" <<'PY' || exit 71
import hashlib, json, sys
release_path, preview_path = sys.argv[1:]
release = json.load(open(release_path, encoding="utf-8"))
preview = json.load(open(preview_path, encoding="utf-8"))
if release.get("tagName") != preview.get("tag_name"):
    raise SystemExit("PUBLISH_GATE_BLOCKED:TAG")
if release.get("name") != preview.get("title"):
    raise SystemExit("PUBLISH_GATE_BLOCKED:TITLE")
if release.get("isDraft") is not True or release.get("isPrerelease") is not preview.get("prerelease"):
    raise SystemExit("PUBLISH_GATE_BLOCKED:STATE")
body = ((release.get("body") or "").rstrip() + "\n").encode("utf-8")
if hashlib.sha256(body).hexdigest() != preview.get("release_notes_sha256"):
    raise SystemExit("PUBLISH_GATE_BLOCKED:BODY")
if {item.get("name") for item in release.get("assets", [])} != set(preview.get("expected_release_assets") or []):
    raise SystemExit("PUBLISH_GATE_BLOCKED:ASSETS")
if preview.get("semantic_validation") != "PASS" or preview.get("manual_draft_repair") != "FORBIDDEN":
    raise SystemExit("PUBLISH_GATE_BLOCKED:PREVIEW")
PY
echo "PUBLISH_ACTION_TIME_PREVIEW_PASS tag=$tag target=$expected"

# Irreversible publication boundary: no build/provider/rewrite work after this point.
set +e
gh release edit "$tag" --draft=false
publish_rc=$?
set -e

# Never blind-retry publication. Reconcile the authoritative destination first.
if ! gh api "repos/$repository/releases/tags/$tag" >"$tmp/published.json"; then
  echo "PUBLISH_OUTCOME_UNKNOWN:RECONCILIATION_FAILED tag=$tag publish_rc=$publish_rc" >&2
  exit 82
fi
publish_state=$(python3 - "$tmp/published.json" "$tag" "$expected" "$tmp/stage/publish-preview.json" <<'PY'
import hashlib, json, sys
release_path, tag, expected, preview_path = sys.argv[1:]
data = json.load(open(release_path, encoding="utf-8"))
preview = json.load(open(preview_path, encoding="utf-8"))
if data.get("tag_name") != tag or data.get("target_commitish") not in (expected, "main"):
    print("MISMATCH")
    raise SystemExit(0)
body = ((data.get("body") or "").rstrip() + "\n").encode("utf-8")
if data.get("name") != preview.get("title"):
    print("MISMATCH")
elif hashlib.sha256(body).hexdigest() != preview.get("release_notes_sha256"):
    print("MISMATCH")
elif {item.get("name") for item in data.get("assets", [])} != set(preview.get("expected_release_assets") or []):
    print("MISMATCH")
elif data.get("draft") is False and data.get("published_at") and data.get("immutable") is True:
    print("PUBLISHED")
elif data.get("draft") is True and not data.get("published_at"):
    print("DRAFT")
else:
    print("MISMATCH")
PY
)
case "$publish_state" in
  PUBLISHED)
    echo "PUBLISH_OUTCOME_RECONCILED_PASS tag=$tag publish_rc=$publish_rc"
    ;;
  DRAFT)
    echo "PUBLISH_OUTCOME_RECONCILED_DRAFT tag=$tag publish_rc=$publish_rc" >&2
    if [[ $publish_rc -eq 0 ]]; then exit 83; else exit "$publish_rc"; fi
    ;;
  *)
    echo "PUBLISH_OUTCOME_UNKNOWN:STATE_MISMATCH tag=$tag publish_rc=$publish_rc" >&2
    exit 83
    ;;
esac

if [[ "$tag" != *-rc.* ]]; then
  gh api "repos/$repository/releases/latest" >"$tmp/latest.json" || {
    echo "PUBLISH_GATE_BLOCKED:LATEST_QUERY" >&2
    exit 84
  }
  python3 - "$tmp/latest.json" "$tag" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
tag = sys.argv[2]
if (
    data.get("tag_name") != tag
    or data.get("draft") is not False
    or data.get("prerelease") is not False
    or data.get("immutable") is not True
    or not data.get("published_at")
):
    raise SystemExit("PUBLISH_GATE_BLOCKED:LATEST_RELEASE")
PY
  echo "LATEST_RELEASE_PASS tag=$tag"

  public_install="$tmp/public-install.sh"
  /usr/bin/curl --proto '=https' --tlsv1.2 --fail --location --silent --show-error --retry 3     --output "$public_install"     "https://github.com/$repository/releases/latest/download/install.sh" || {
      echo "PUBLISH_POSTVERIFY_BLOCKED:PUBLIC_INSTALL_DOWNLOAD" >&2
      exit 85
    }
  python3 - "$tmp/stage/pretag-manifest.json" "$public_install" <<'PY' || exit 85
import hashlib, json, pathlib, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
path = pathlib.Path(sys.argv[2])
actual = hashlib.sha256(path.read_bytes()).hexdigest()
expected = manifest["files"]["install.sh"]
if actual != expected:
    raise SystemExit(
        f"PUBLISH_POSTVERIFY_BLOCKED:PUBLIC_INSTALL_BYTES:expected={expected}:actual={actual}"
    )
PY
  public_home="$tmp/public-home"
  mkdir -p "$public_home"
  HOME="$public_home" /bin/sh "$public_install" >"$tmp/public-install.log" 2>&1 || {
    cat "$tmp/public-install.log" >&2
    echo "PUBLISH_POSTVERIFY_BLOCKED:PUBLIC_INSTALL_EXECUTION" >&2
    exit 85
  }
  for name in clroom clroom-codex clroom-claude; do
    "$public_home/.local/bin/$name" --clroom-installer-smoke >/dev/null 2>&1 || {
      echo "PUBLISH_POSTVERIFY_BLOCKED:PUBLIC_INSTALL_SMOKE:$name" >&2
      exit 85
    }
  done
  echo "PUBLIC_INSTALL_VERIFY_PASS tag=$tag"
fi
echo "RELEASE_PUBLISH_PASS tag=$tag target=$expected"
