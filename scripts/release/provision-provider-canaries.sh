#!/usr/bin/env bash
set -euo pipefail

fail() {
  printf 'PROVIDER_CANARY_BLOCKED:%s\n' "$1" >&2
  exit 1
}

[[ $# -eq 2 ]] || fail "USAGE"
provider_root=$1
env_file=$2

[[ "$(uname -s)" == "Darwin" ]] || fail "HOST_DARWIN_REQUIRED"
[[ "$(uname -m)" == "arm64" ]] || fail "HOST_ARM64_REQUIRED"
command -v npm >/dev/null 2>&1 || fail "NPM_REQUIRED"
command -v openssl >/dev/null 2>&1 || fail "OPENSSL_REQUIRED"
command -v python3 >/dev/null 2>&1 || fail "PYTHON_REQUIRED"
command -v cmp >/dev/null 2>&1 || fail "CMP_REQUIRED"

CODEX_VERSION=0.155.1
CLAUDE_VERSION=2.1.278
CODEX_SHA512='FV/x1OHXYv/ifjf3mXj9ThTTAWcUZN6cGIRQRhRxkKNOPuImu1WW0c8ev1vUkE9XGH90dEnYG1tBjIkxRikg0w=='
CODEX_PLATFORM_SHA512='HP/vJCH/t2hB9Kg6hotN9UglClJ6/z584fal5lEP14C9gNAgAQS4/kTQC7l5V+BA3TqwDPwINSjul28cX8AYXg=='
CLAUDE_SHA512='sOwHBM69H8Zka3/D3rc2VNNemPYNlgfYTdhsoqPoXZdK5KcKQlzoue4asJ2RVc+tGb/Pz1qxjVV9nVJQ87W7Ng=='
CLAUDE_PLATFORM_SHA512='l3CI1gPSCGkWNbAnX66SbDF4uFBecCCLu9FLN43JSbMMds5cb6tjOTBMSTr1ydZRZALW9AC/PYabtQOgXIbK5Q=='

pin_mismatch=0
verify_latest() {
  local package=$1 expected=$2 latest
  latest=$(npm view "$package" dist-tags.latest --silent) || fail "LATEST_LOOKUP_FAILED"
  if [[ "$latest" != "$expected" ]]; then
    printf 'PROVIDER_LATEST_MISMATCH package=%s pinned=%s latest=%s\n' "$package" "$expected" "$latest" >&2
    pin_mismatch=1
  fi
}

verify_registry_integrity() {
  local spec=$1 expected_sha512=$2 actual
  actual=$(npm view "$spec" dist.integrity --silent) || fail "INTEGRITY_LOOKUP_FAILED"
  if [[ "$actual" != "sha512-$expected_sha512" ]]; then
    printf 'PROVIDER_REGISTRY_INTEGRITY_MISMATCH spec=%s expected=sha512-%s actual=%s\n' \
      "$spec" "$expected_sha512" "$actual" >&2
    pin_mismatch=1
  fi
}

verify_latest '@openai/codex' "$CODEX_VERSION"
verify_latest '@anthropic-ai/claude-code' "$CLAUDE_VERSION"
verify_latest '@anthropic-ai/claude-code-darwin-arm64' "$CLAUDE_VERSION"
verify_registry_integrity "@openai/codex@$CODEX_VERSION" "$CODEX_SHA512"
verify_registry_integrity "@openai/codex@$CODEX_VERSION-darwin-arm64" "$CODEX_PLATFORM_SHA512"
verify_registry_integrity "@anthropic-ai/claude-code@$CLAUDE_VERSION" "$CLAUDE_SHA512"
verify_registry_integrity "@anthropic-ai/claude-code-darwin-arm64@$CLAUDE_VERSION" "$CLAUDE_PLATFORM_SHA512"
[[ $pin_mismatch -eq 0 ]] || fail "PIN_REGISTRY_MISMATCH"

rm -rf "$provider_root"
mkdir -p "$provider_root/packs"
pack_dir="$provider_root/packs"

pack_and_verify() {
  local spec=$1
  local expected_name=$2
  local expected_sha512=$3
  local output archive actual

  output=$(npm pack --ignore-scripts --silent --pack-destination "$pack_dir" "$spec") || fail "PACK_FAILED"
  archive="$pack_dir/$(printf '%s\n' "$output" | tail -n 1)"
  [[ "$(basename "$archive")" == "$expected_name" ]] || fail "PACK_NAME_MISMATCH"
  [[ -f "$archive" ]] || fail "PACK_MISSING"
  actual=$(openssl dgst -sha512 -binary "$archive" | base64)
  [[ "$actual" == "$expected_sha512" ]] || fail "PACK_INTEGRITY_MISMATCH"
  printf '%s\n' "$archive"
}

safe_extract() {
  local archive=$1
  local destination=$2
  mkdir -p "$destination"
  python3 - "$archive" "$destination" <<'PY'
import os
import pathlib
import sys
import tarfile

archive, destination = sys.argv[1:]
root = pathlib.Path(destination).resolve()
with tarfile.open(archive, "r:gz") as handle:
    members = handle.getmembers()
    if not members:
        raise SystemExit("empty npm package")
    for member in members:
        path = pathlib.PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "package":
            raise SystemExit(f"unsafe npm package path: {member.name}")
        if member.issym() or member.islnk():
            target = pathlib.PurePosixPath(member.linkname)
            if target.is_absolute() or ".." in target.parts:
                raise SystemExit(f"unsafe npm package link: {member.name}")
        candidate = (root / pathlib.Path(*path.parts)).resolve(strict=False)
        if candidate != root and root not in candidate.parents:
            raise SystemExit(f"npm package escapes destination: {member.name}")
    handle.extractall(root)
PY
}

resolve_bin() {
  local package_root=$1
  local bin_name=$2
  python3 - "$package_root/package.json" "$bin_name" <<'PY'
import json
import pathlib
import sys

manifest_path = pathlib.Path(sys.argv[1]).resolve()
bin_name = sys.argv[2]
data = json.loads(manifest_path.read_text(encoding="utf-8"))
bin_value = data.get("bin")
if isinstance(bin_value, str):
    relative = bin_value
elif isinstance(bin_value, dict):
    relative = bin_value.get(bin_name)
else:
    relative = None
if not relative:
    raise SystemExit(f"missing bin entry {bin_name}")
root = manifest_path.parent
binary = (root / relative).resolve(strict=False)
if binary != root and root not in binary.parents:
    raise SystemExit("bin entry escapes package root")
if not binary.is_file():
    raise SystemExit(f"bin entry is not a file: {binary}")
print(binary)
PY
}

codex_archive=$(pack_and_verify \
  "@openai/codex@$CODEX_VERSION" \
  "openai-codex-$CODEX_VERSION.tgz" \
  "$CODEX_SHA512")
codex_platform_archive=$(pack_and_verify \
  "@openai/codex@$CODEX_VERSION-darwin-arm64" \
  "openai-codex-$CODEX_VERSION-darwin-arm64.tgz" \
  "$CODEX_PLATFORM_SHA512")
claude_archive=$(pack_and_verify \
  "@anthropic-ai/claude-code@$CLAUDE_VERSION" \
  "anthropic-ai-claude-code-$CLAUDE_VERSION.tgz" \
  "$CLAUDE_SHA512")
claude_platform_archive=$(pack_and_verify \
  "@anthropic-ai/claude-code-darwin-arm64@$CLAUDE_VERSION" \
  "anthropic-ai-claude-code-darwin-arm64-$CLAUDE_VERSION.tgz" \
  "$CLAUDE_PLATFORM_SHA512")

safe_extract "$codex_archive" "$provider_root/codex"
safe_extract "$codex_platform_archive" "$provider_root/codex-platform"
safe_extract "$claude_archive" "$provider_root/claude"
safe_extract "$claude_platform_archive" "$provider_root/claude-platform"

codex_root="$provider_root/codex/package"
claude_root="$provider_root/claude/package"
platform_root="$provider_root/codex-platform/package"
platform_alias="$codex_root/node_modules/@openai/codex-darwin-arm64"
mkdir -p "$(dirname "$platform_alias")"
mv "$platform_root" "$platform_alias"
rmdir "$provider_root/codex-platform"

codex_native="$platform_alias/vendor/aarch64-apple-darwin/bin/codex"
[[ -f "$codex_native" ]] || fail "CODEX_NATIVE_MISSING"
chmod 0755 "$codex_native"

codex_bin=$(resolve_bin "$codex_root" codex) || fail "CODEX_BIN_INVALID"
claude_bin=$(resolve_bin "$claude_root" claude) || fail "CLAUDE_BIN_INVALID"
claude_platform_root="$provider_root/claude-platform/package"
claude_native="$claude_platform_root/claude"
[[ -f "$claude_native" ]] || fail "CLAUDE_NATIVE_MISSING"
chmod 0755 "$codex_bin" "$claude_bin" "$claude_native"

# The wrapper package normally materializes its optional native package during
# postinstall. Release qualification must not run install scripts, so use the
# independently SHA-512-verified darwin-arm64 package directly. CLROOM production
# resolution still requires the command name `claude`, therefore copy those exact
# verified native bytes to a command-name path and prove byte identity.
mkdir -p "$provider_root/bin"
claude_canary="$provider_root/bin/claude"
cp "$claude_native" "$claude_canary"
chmod 0755 "$claude_canary"
cmp -s "$claude_native" "$claude_canary" || fail "CLAUDE_CANARY_COPY_MISMATCH"

[[ -x "$codex_native" ]] || fail "CODEX_NATIVE_NOT_EXECUTABLE"
[[ -x "$codex_bin" ]] || fail "CODEX_BIN_NOT_EXECUTABLE"
[[ -x "$claude_bin" ]] || fail "CLAUDE_BIN_NOT_EXECUTABLE"
[[ -x "$claude_native" ]] || fail "CLAUDE_NATIVE_NOT_EXECUTABLE"
[[ -x "$claude_canary" ]] || fail "CLAUDE_CANARY_NOT_EXECUTABLE"
[[ -f "$env_file" || -e "$env_file" ]] || :
printf 'CLROOM_PROVIDER_CODEX=%s\n' "$codex_native" >> "$env_file"
printf 'CLROOM_PROVIDER_CLAUDE=%s\n' "$claude_canary" >> "$env_file"
printf 'CLROOM_PROVIDER_CODEX_VERSION=%s\n' "$CODEX_VERSION" >> "$env_file"
printf 'CLROOM_PROVIDER_CLAUDE_VERSION=%s\n' "$CLAUDE_VERSION" >> "$env_file"
printf 'PROVIDER_CANARY_PASS codex=%s claude=%s\n' "$CODEX_VERSION" "$CLAUDE_VERSION"
