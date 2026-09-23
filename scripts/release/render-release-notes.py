#!/usr/bin/env python3
import argparse
from pathlib import Path

def main() -> int:
    p=argparse.ArgumentParser()
    p.add_argument("--version", required=True)
    p.add_argument("--artifact", required=True)
    p.add_argument("--output", required=True)
    a=p.parse_args()
    lines=Path("CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    start=None
    body=[]
    for i,line in enumerate(lines):
        if line.startswith(f"## [{a.version}] - "):
            start=i+1
            continue
        if start is not None and line.startswith("## ["):
            break
        if start is not None:
            body.append(line)
    if start is None:
        raise SystemExit("RELEASE_NOTES_BLOCKED:MISSING_CHANGELOG_SECTION")
    text="\n".join(body).strip()
    footer=f"""
## Install

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/y-sor/clean-room-launcher/releases/latest/download/install.sh | sh
```

## Download and verification

- `install.sh` — one-line macOS Apple Silicon installer
- `{a.artifact}` — macOS Apple Silicon archive
- `SHA256SUMS` — SHA-256 digests for the archive, SBOM, and installer
- `sbom.cdx.json` — CycloneDX SBOM bound to the archive digest
- `{a.artifact}.provenance.sigstore.json` — release-visible Sigstore bundle for build provenance of the exact archive, SBOM, and installer bytes
- `{a.artifact}.sbom.sigstore.json` — release-visible Sigstore bundle for the CycloneDX SBOM attestation bound to the exact archive bytes

Verify the downloaded archive against its release-visible provenance bundle:

```sh
gh attestation verify "{a.artifact}" \
  -R y-sor/clean-room-launcher \
  --bundle "{a.artifact}.provenance.sigstore.json" \
  --signer-workflow y-sor/clean-room-launcher/.github/workflows/release.yml
```

The distributed archive is currently unsigned at the Apple platform-signing layer. Verify the checksums and release-visible GitHub attestation bundles before use.
""".strip()
    Path(a.output).write_text(text+"\n\n"+footer+"\n",encoding="utf-8")
    return 0
if __name__=="__main__":
    raise SystemExit(main())
