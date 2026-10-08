# External clean-install canary

This protocol originated in the `v0.2.0` release line and remains a reusable
public first-use check for the currently published stable release. Resolve the
exact published release tag and downloadable assets at execution time; this
historical protocol does not declare `v0.2.0` to be current.
It replaces the legacy controller-only v0.1 artifact procedure.

## Pre-publication evidence

Before tagging or publishing a release candidate:

1. `install.sh --self-test` passes on the release-readiness macOS runner.
2. The release workflow uploads `install.sh`, the qualified macOS archive,
   `SHA256SUMS`, and `sbom.cdx.json` as one reconciled bundle.
3. `SHA256SUMS` covers the archive, SBOM, and installer.
4. README and installation docs contain the canonical one-line command.
5. The installer fails closed on an unsupported OS or architecture, an
   ambiguous/malformed release manifest, checksum mismatch, and unexpected
   archive layout.

## Post-publication canary

After the Owner-authorized GitHub Release is published, use a clean macOS Apple
Silicon standard-user environment with an already working supported provider.
Run only the documented public command:

```sh
curl --proto '=https' --tlsv1.2 -fsSL \
  https://github.com/y-sor/clean-room-launcher/releases/latest/download/install.sh | sh
```

A PASS requires:

- the command exits successfully without `sudo` or a login prompt;
- the downloaded archive checksum matches the published `SHA256SUMS` entry;
- `~/.local/bin/clroom` is executable and `clroom --help` succeeds;
- no shell startup file, service, provider configuration, credential, or system
  setting is created or modified;
- removing `~/.local/bin/clroom` removes the one-line installation.

A failed canary is a release defect. Do not describe the one-line path as
verified until the published asset path has passed this canary.
