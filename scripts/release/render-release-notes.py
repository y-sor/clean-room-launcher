#!/usr/bin/env python3
import argparse
from pathlib import Path

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    lines = Path("CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    prefix = f"## [{args.version}] - "
    matches = [i for i, line in enumerate(lines) if line.startswith(prefix)]
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one changelog section for {args.version}")
    start = matches[0] + 1
    body = []
    for line in lines[start:]:
        if line.startswith("## ["):
            break
        body.append(line)
    text = "\n".join(body).strip()
    if not text:
        raise SystemExit("release notes body is empty")

    footer = f"""
## Install

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/y-sor/clean-room-launcher/releases/latest/download/install.sh | sh
```

## Download and verification

- `install.sh` — one-line macOS Apple Silicon installer
- `{args.artifact}` — macOS Apple Silicon archive
- `SHA256SUMS` — SHA-256 digests for the archive, SBOM, and installer
- `sbom.cdx.json` — CycloneDX SBOM bound to the archive digest
- `{args.artifact}.provenance.sigstore.json` — release-visible Sigstore bundle for build provenance of the exact archive, SBOM, and installer bytes
- `{args.artifact}.sbom.sigstore.json` — release-visible Sigstore bundle for the CycloneDX SBOM attestation bound to the exact archive bytes

Verify the downloaded archive against its release-visible provenance bundle:

```sh
gh attestation verify "{args.artifact}" \
  -R y-sor/clean-room-launcher \
  --bundle "{args.artifact}.provenance.sigstore.json" \
  --signer-workflow y-sor/clean-room-launcher/.github/workflows/release.yml
```

The distributed archive is currently unsigned at the Apple platform-signing layer. Verify the checksums and release-visible GitHub attestation bundles before use.
""".strip()
    Path(args.output).write_text(text + "\n\n" + footer + "\n", encoding="utf-8")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
