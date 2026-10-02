#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

HEADING_RE = re.compile(r"^## \[([0-9]+\.[0-9]+\.[0-9]+)\] - \d{4}-\d{2}-\d{2}$")


def release_range(lines: list[str], candidate: str, baseline: str) -> tuple[str, list[str]]:
    candidate_prefix = f"## [{candidate}] - "
    baseline_prefix = f"## [{baseline}] - "
    candidate_matches = [i for i, line in enumerate(lines) if line.startswith(candidate_prefix)]
    baseline_matches = [i for i, line in enumerate(lines) if line.startswith(baseline_prefix)]
    if len(candidate_matches) != 1:
        raise ValueError(f"expected exactly one changelog section for {candidate}")
    if len(baseline_matches) != 1:
        raise ValueError(f"expected exactly one published baseline section for {baseline}")
    start = candidate_matches[0]
    end = baseline_matches[0]
    if start >= end:
        raise ValueError("published baseline must appear after candidate in changelog")
    selected = lines[start:end]
    versions = [
        match.group(1)
        for line in selected
        if (match := HEADING_RE.fullmatch(line)) is not None
    ]
    if not versions or versions[0] != candidate or baseline in versions:
        raise ValueError("release changelog range is not candidate-through-baseline-exclusive")
    text = "\n".join(selected).strip()
    if not text:
        raise ValueError("release changelog range is empty")
    return text, versions


def footer(artifact: str) -> str:
    return f"""## Install

```sh
curl --proto '=https' --tlsv1.2 -fsSL https://github.com/y-sor/clean-room-launcher/releases/latest/download/install.sh | sh
```

## Download and verification

- `install.sh` — one-line macOS Apple Silicon installer
- `{artifact}` — macOS Apple Silicon archive
- `SHA256SUMS` — SHA-256 digests for the archive, SBOM, and installer
- `sbom.cdx.json` — CycloneDX SBOM bound to the archive digest
- `{artifact}.provenance.sigstore.json` — release-visible Sigstore bundle for build provenance of the exact archive, SBOM, and installer bytes
- `{artifact}.sbom.sigstore.json` — release-visible Sigstore bundle for the CycloneDX SBOM attestation bound to the exact archive bytes

Verify the downloaded archive against its release-visible provenance bundle:

```sh
gh attestation verify "{artifact}" \
  -R y-sor/clean-room-launcher \
  --bundle "{artifact}.provenance.sigstore.json" \
  --signer-workflow y-sor/clean-room-launcher/.github/workflows/release.yml
```

The distributed archive is currently unsigned at the Apple platform-signing layer. Verify the checksums and release-visible GitHub attestation bundles before use.""".strip()


def self_test() -> None:
    sample = [
        "# Changelog",
        "## [Unreleased]",
        "## [0.4.6] - 2026-10-02",
        "",
        "- current",
        "## [0.4.5] - 2026-10-01",
        "",
        "- unpublished intermediate",
        "## [0.4.4] - 2026-09-30",
        "",
        "- published baseline",
    ]
    text, versions = release_range(sample, "0.4.6", "0.4.4")
    if versions != ["0.4.6", "0.4.5"]:
        raise SystemExit("RELEASE_NOTES_SELF_TEST_FAIL:RANGE_VERSIONS")
    if "unpublished intermediate" not in text or "published baseline" in text:
        raise SystemExit("RELEASE_NOTES_SELF_TEST_FAIL:RANGE_CONTENT")
    try:
        release_range(sample, "0.4.4", "0.4.6")
    except ValueError:
        pass
    else:
        raise SystemExit("RELEASE_NOTES_SELF_TEST_FAIL:ORDER")
    print("RELEASE_NOTES_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--version")
    parser.add_argument("--baseline-tag")
    parser.add_argument("--artifact")
    parser.add_argument("--output")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    if not all((args.version, args.baseline_tag, args.artifact, args.output)):
        parser.error("--version, --baseline-tag, --artifact and --output are required")
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", args.baseline_tag):
        raise SystemExit("published baseline tag must be stable vX.Y.Z")

    lines = Path("CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    body, _versions = release_range(lines, args.version, args.baseline_tag[1:])
    Path(args.output).write_text(body + "\n\n" + footer(args.artifact) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
