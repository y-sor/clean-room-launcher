# Release Contract

CLROOM reviews releases as a whole product delta, not as the last pull request.

The authoritative baseline is the latest published stable GitHub Release. Before
tagging, the release candidate must classify every changed path since that
baseline, record a disposition for every changed release domain, record all
known near-misses, and decide whether the release contract itself must expand.

## What is machine-enforced

`scripts/release/check-release-contract.py` fails closed when:

- the declared baseline is not the current latest published stable release;
- a changed path is not classified by the release contract;
- a changed domain lacks an evidence-backed disposition;
- a known near-miss lacks a disposition;
- contract expansion is declared without a durable promoted control;
- semantic product outcome is missing;
- any tracked byte, executable mode, symlink, or semantic review declaration
  changes after the semantic review seal.

The semantic review seal is a SHA-256 digest over the tracked Git tree
(mode/type/blob/path). The release review JSON participates through canonical
JSON semantics with only its self-referential `reviewed_content_digest` field
removed. Changing source, docs, workflows, packaging, tests, scripts, file
modes, symlinks, dispositions, near-misses, product outcome, contract-evolution
decision, or capability gates therefore requires a fresh review seal.

Release readiness and the tag workflow both run the same contract check.

## Contract evolution review

Every release must explicitly choose one:

- `EXPAND`: a new/repeated failure mode requires a new durable gate or evidence;
- `NO_CHANGE`: existing gates already detect all newly relevant failure modes,
  with a written rationale.

This is intentionally separate from ordinary CI. CI answers whether the current
candidate passes existing controls. Contract evolution asks whether the delta
made any existing control insufficient.

## Artifact integrity

The release workflow qualifies the provider launchers extracted from the exact
release archive, not sibling build outputs. The archive, installer, SBOM,
checksums, provenance attestation bundle, and SBOM attestation bundle are
verified before a guarded Draft Release is created.

Publishing remains a separate action.

Because stable `v*` tags are protected against update/deletion, the new
Claude plugin capability is exercised twice:

1. **Pre-tag:** exact accepted `main` builds a candidate archive locally,
   proves clean/selected plugin separation and unchanged provider config, then
   opens the selected-plugin TUI without sending a model prompt. The PASS
   evidence is bound to the exact accepted-main SHA and is required by the tag
   helper.
2. **Pre-publish:** the exact Draft Release archive is downloaded, checksum and
   attestation bundles are verified, and the same automated plugin separation
   checks run against those downloaded bytes.

Use:

```sh
scripts/release/local-plugin-activation-smoke.sh pretag --plugin-id <qualified-id>
scripts/release/local-plugin-activation-smoke.sh draft --tag vX.Y.Z --plugin-id <qualified-id>
```

The smoke never installs, updates, enables, disables, or downgrades Claude or a
plugin. Provider inference success is not required: qualification is based on
startup `system/init` evidence before any billing/model response.

## Local audit

To inspect what is actually in the candidate relative to the last published
release:

```sh
scripts/release/local-release-audit.sh
```

For the full local test/build/artifact pass:

```sh
scripts/release/local-release-audit.sh --full
```

The summary prints the authoritative published baseline, the complete commit
list, every changed file and its release domain, the contract-evolution
decision, artifact capability gates, and the dependency/version diff.

The full mode additionally runs the public-boundary check, installer self-test,
all locked tests, builds a candidate archive, verifies its metadata, and prints
its SHA-256.

Local audit complements GitHub CI and real-provider/draft-artifact evidence; it
does not grant merge, tag, or publish permission.
