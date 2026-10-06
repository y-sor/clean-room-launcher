---
layout: page
title: Install CLROOM
description: Install the current Clean Room Launcher release on macOS Apple Silicon, verify the release archive, or install the exact release tag with Cargo.
permalink: /install.html
nav_title: Install
---

Prerequisites:

- macOS on Apple Silicon;
- Codex CLI `0.147.0+` or Claude Code CLI `2.1.223+` already working on its own.

## One-line install

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/y-sor/clean-room-launcher/releases/latest/download/install.sh | sh
```

The installer downloads the latest published stable macOS Apple Silicon release
from GitHub Releases, verifies the exact archive against `SHA256SUMS`, extracts
the `clroom`, `clroom-codex`, and `clroom-claude` binaries, and installs them to
`~/.local/bin`. It does not
use `sudo`, edit shell startup files, install a service, or change provider
state.

If `~/.local/bin` is not already in `PATH`, the installer prints the directory
to add. The release archive is unsigned and unnotarized; do not disable
Gatekeeper globally if local macOS policy refuses it.

Before running a downloaded release, [verify its checksum, provenance, SBOM attestation, and publication identity](verify-release.md). Those checks answer different trust questions; the current archive remains unsigned and unnotarized at the Apple code-signing layer.

## If the first command fails

Use the symptom before changing system security or reinstalling anything:

| Symptom | First check |
| --- | --- |
| `clroom: command not found` | The one-line installer writes to `~/.local/bin`. Run `command -v clroom` and check whether `$HOME/.local/bin` is present in `PATH`. For the current shell, `export PATH="$HOME/.local/bin:$PATH"` is sufficient to test the installation. |
| CLROOM starts but cannot find the provider | The provider CLI is a prerequisite. Run `command -v codex` or `command -v claude` and verify that the provider works directly before debugging CLROOM. |
| macOS says the developer cannot be verified or Apple cannot check the software | The current CLROOM archive is unsigned and unnotarized. Verify the exact release first. Do **not** disable Gatekeeper globally. If your local/organization policy permits the release after verification, use the normal macOS per-app approval flow rather than weakening machine-wide security. |
| Architecture/format error | The current published qualification is macOS on Apple Silicon. `uname -m` should report `arm64`; Intel macOS is not qualified by this release. |

If these checks do not explain the failure, use [Support](SUPPORT.md) and include the CLROOM version, macOS/architecture, provider version, sanitized command, expected behavior, and observed error. Do not post credentials, provider tokens, prompts, transcripts, or unrestricted environment dumps.

The [problem index](problem-index.md#install-first-run-failures) also maps common first-run wording to this answer.

## Package-manager status

The current supported binary distribution is the GitHub Release installer/archive above.

- **Homebrew:** no supported CLROOM formula is currently claimed.
- **crates.io:** CLROOM is not currently published there.
- **Cargo:** an exact published Git tag can be installed from the Git repository as shown below.
- **npm and other package managers:** not current CLROOM distribution paths.

Do not treat an unrelated third-party package with a similar name as an official CLROOM release. The canonical release identity is the `y-sor/clean-room-launcher` GitHub Release and its published verification evidence.

## Manual release archive

The exact-version examples below require that the named tag and GitHub Release
have already been published.

```sh
VERSION=vX.Y.Z
ASSET=clean-room-launcher-${VERSION}-aarch64-apple-darwin.tar.gz
STAGE=$(mktemp -d "${TMPDIR:-/tmp}/clroom-archive.XXXXXX")
trap 'rm -rf -- "$STAGE"' EXIT

curl -fLO "https://github.com/y-sor/clean-room-launcher/releases/download/$VERSION/$ASSET"
curl -fLO "https://github.com/y-sor/clean-room-launcher/releases/download/$VERSION/SHA256SUMS"
EXPECTED=$(awk -v asset="$ASSET" '$2 == asset {print $1}' SHA256SUMS)
ACTUAL=$(shasum -a 256 "$ASSET" | awk '{print $1}')
test -n "$EXPECTED" && test "$ACTUAL" = "$EXPECTED"
tar -xzf "$ASSET" -C "$STAGE"
BIN="$STAGE/${ASSET%.tar.gz}/bin"
DEST="$HOME/.local/bin"
test -d "$BIN"
test ! -L "$DEST"
test ! -e "$DEST" || test -d "$DEST"
for name in clroom clroom-codex clroom-claude; do
  target="$DEST/$name"
  test ! -L "$target"
  test ! -e "$target" || test -f "$target"
done
mkdir -p "$DEST"
for name in clroom clroom-codex clroom-claude; do
  install -m 0755 "$BIN/$name" "$DEST/$name"
done
```

This verifies only the archive you downloaded; `SHA256SUMS` also covers the
other release assets.

## Cargo from the release tag

```sh
cargo install --git https://github.com/y-sor/clean-room-launcher \
  --tag vX.Y.Z --locked
```

The release is not published to crates.io.

## Verify the installation

Run only the provider command or commands you intend to use:

```sh
clroom --help
cd your-project
clroom codex --help       # if Codex is installed
clroom codex --version
clroom claude --version   # if Claude Code is installed
clroom-codex --help       # executable override for external launchers
clroom-claude --help      # executable override for external launchers
```

To remove an archive or one-line installation, delete the three files under
`$HOME/.local/bin` (`clroom`, `clroom-codex`, and `clroom-claude`). For Cargo,
run `cargo uninstall clean-room-launcher`.

These commands remove the installed binaries. They do not remove CLROOM-owned
provider support state such as Codex's `.clroom-clean-state-v1` directory.
No service or system setting is created.
