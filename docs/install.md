---
layout: page
title: Install CLROOM
description: Install the current Clean Room Launcher release on macOS Apple Silicon, verify the release archive, or install the exact release tag with Cargo.
permalink: /install.html
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
