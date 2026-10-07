---
layout: page
title: Verify a CLROOM release
description: Verify CLROOM release checksums, provenance and CycloneDX SBOM attestations, immutable GitHub release state, and current signing limitations.
permalink: /verify-release/
nav_title: Verify release
---

A CLROOM release carries several different kinds of evidence. They answer different questions.

**Short version:** verify the downloaded bytes against `SHA256SUMS`, verify the published GitHub attestations against the CLROOM release workflow, and keep the platform limitation in mind: the current macOS archive is **unsigned and unnotarized** at the Apple code-signing layer.

None of these checks means "the program is risk-free." Together they make the release identity, build provenance, dependency inventory, and documented qualification easier to audit.

## What each check proves

| Evidence | What it tells you | What it does not tell you |
| --- | --- | --- |
| **SHA-256 checksum** | The downloaded file matches the digest published in the same release. | By itself, it does not prove who produced the file. |
| **Build provenance attestation** | GitHub can verify that the subject is covered by CLROOM's tag-bound release attestation from the expected repository/workflow/ref. | It is not Apple code signing, notarization, a security audit, or proof that the program has no bugs. |
| **CycloneDX SBOM** | The release publishes a machine-readable software bill of materials for the staged archive. | An SBOM is an inventory, not a vulnerability-free guarantee. |
| **SBOM attestation** | The release workflow cryptographically binds the CycloneDX SBOM predicate to the archive subject. | It does not independently prove that every dependency is safe. |
| **Immutable GitHub Release** | After publication, GitHub reports the release as immutable and protects the associated published release identity/assets from ordinary modification. | It does not replace content verification or provider/runtime qualification. |
| **CLROOM qualification evidence** | CLROOM's release process tested the documented provider/version/platform paths for that release. | Evidence does not automatically transfer to another provider version, platform, architecture, or unsupported path. |
| **Apple signing/notarization** | Not currently claimed for the distributed archive. | Provenance attestations must not be described as Apple signing or notarization. |

## 1. Download one exact published release

The examples use GitHub CLI because the release attestations are GitHub artifact attestations exported as Sigstore bundles.

```sh
REPO="y-sor/clean-room-launcher"
VERSION="vX.Y.Z"
ASSET="clean-room-launcher-${VERSION}-aarch64-apple-darwin.tar.gz"
DIR="$(mktemp -d "${TMPDIR:-/tmp}/clroom-verify.XXXXXX")"
SOURCE="$(gh api "repos/$REPO/commits/$VERSION" --jq .sha)"

gh release download "$VERSION" -R "$REPO" -D "$DIR"
cd "$DIR"
```

Use a version that already exists as a published GitHub Release. Do not substitute an unpublished tag or a branch build.

## 2. Verify the archive checksum

```sh
EXPECTED="$(awk -v asset="$ASSET" '$2 == asset {print $1}' SHA256SUMS)"
ACTUAL="$(shasum -a 256 "$ASSET" | awk '{print $1}')"

test -n "$EXPECTED"
test "$ACTUAL" = "$EXPECTED"
printf 'SHA256 OK: %s\n' "$ACTUAL"
```

This proves that the archive matches the digest recorded in the published `SHA256SUMS` file.

## 3. Verify release provenance

The release publishes:

```text
<archive>.provenance.sigstore.json
<archive>.sbom.sigstore.json
```

Verify the archive against the provenance bundle and the exact CLROOM release workflow/ref:

```sh
PROVENANCE="$ASSET.provenance.sigstore.json"

gh attestation verify "$ASSET" \
  -R "$REPO" \
  --bundle "$PROVENANCE" \
  --signer-workflow "$REPO/.github/workflows/release.yml" \
  --source-digest "$SOURCE" \
  --source-ref "refs/tags/$VERSION" \
  --deny-self-hosted-runners
```

The public command mirrors the material provenance constraints used by CLROOM's release workflow: expected repository, signer workflow, exact source commit, tag ref, and published bundle. The release workflow performs the same binding before Draft promotion and again against reconciled Draft bytes.

The same provenance bundle covers the published `sbom.cdx.json` and `install.sh` subjects:

```sh
for subject in sbom.cdx.json install.sh; do
  gh attestation verify "$subject" \
    -R "$REPO" \
    --bundle "$PROVENANCE" \
    --signer-workflow "$REPO/.github/workflows/release.yml" \
    --source-ref "refs/tags/$VERSION" \
    --deny-self-hosted-runners
done
```

## 4. Verify the SBOM attestation

```sh
SBOM_BUNDLE="$ASSET.sbom.sigstore.json"

gh attestation verify "$ASSET" \
  -R "$REPO" \
  --bundle "$SBOM_BUNDLE" \
  --predicate-type https://cyclonedx.org/bom \
  --signer-workflow "$REPO/.github/workflows/release.yml" \
  --source-digest "$SOURCE" \
  --source-ref "refs/tags/$VERSION" \
  --deny-self-hosted-runners
```

The human-readable SBOM file is `sbom.cdx.json`. Review it as dependency inventory; do not interpret its presence as a security certification.

## 5. Confirm the published release identity

GitHub Releases is the authoritative publication surface.

```sh
gh release view "$VERSION" -R "$REPO" \
  --json tagName,isDraft,isPrerelease,isImmutable,publishedAt,url
```

For the release you intend to install, confirm that it is the expected tag, not a Draft, not an unexpected prerelease, and reports `isImmutable: true` after publication.

The project release process additionally requires the final published object to reconcile as immutable before the release is treated as published successfully.

## What remains outside these checks

These checks do **not** establish:

- Apple code signing or notarization — the current distributed archive is unsigned and unnotarized;
- complete machine, filesystem, or network isolation;
- absence of vulnerabilities;
- safety of arbitrary project files, prompts, fetched web content, or MCP/tool output;
- support for provider versions, platforms, transports, plugins, or MCP forms outside the release's documented qualification;
- a guarantee that model output will be deterministic.

For those boundaries, use:

- [Security policy](https://github.com/y-sor/clean-room-launcher/security/policy)
- [Threat model](threat-model.md)
- [Current limitations](limitations.md)
- [Configuration matrix](configuration-matrix.md)
- [Install CLROOM](install.md)

## Why CLROOM publishes several evidence types

A checksum, an attestation, an SBOM, provider qualification, and platform signing answer different trust questions. Treating one of them as a substitute for all the others produces a stronger claim than the evidence supports.

CLROOM's release process therefore keeps those layers separate and makes the current limitations explicit.
