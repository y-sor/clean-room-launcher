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

Release-candidate readiness has two explicit lifecycle states. When the manifest
version still equals the latest immutable published stable release, readiness is
in `POST_PUBLISH`: historical review evidence is left untouched, governance,
negative-contract, regression, installer, and supply-chain checks still run, and
candidate-only whole-delta/artifact qualification is skipped. Once the manifest
version advances beyond that published release, readiness enters
`ACTIVE_CANDIDATE`: the full whole-delta release contract is required against
the latest published stable baseline, including a new versioned review snapshot
and candidate artifact/provider qualification. The tag workflow always runs the
full contract check for the exact tagged candidate.

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

Publishing remains a separate action. Immediately before a protected tag
push, the tag helper refreshes the remote `main` tip, confirms the tag is still
absent, revalidates the active no-bypass `v*` tag ruleset, and reruns the
whole-release contract against the current published baseline. Any drift blocks
the push.

Because stable `v*` tags are protected against update/deletion, the new
Claude plugin capability is exercised twice:

1. **Pre-tag:** exact accepted `main` builds a candidate archive locally,
   proves clean/selected plugin separation and unchanged provider config, then
   opens the selected-plugin TUI without sending a model prompt. The PASS
   evidence is bound to the exact accepted-main SHA and records the observed
   Claude provider version and executable SHA-256; both are revalidated
   immediately before the protected tag push.
2. **Pre-publish:** repository release immutability must still be enabled, then
   the exact Draft Release archive is downloaded, checksum and attestation
   bundles are verified, and the same automated plugin separation checks run
   against those downloaded bytes.

Use:

```sh
scripts/release/local-plugin-activation-smoke.sh pretag --plugin-id <qualified-id>
scripts/release/local-plugin-activation-smoke.sh draft --tag vX.Y.Z --plugin-id <qualified-id>
```

The smoke never installs, updates, enables, disables, or downgrades Claude or a
plugin. Automated clean/selected probes use a fixed sentinel print-mode prompt
only to expose startup `system/init` evidence; model response content and
success are ignored. The pre-tag interactive TUI check sends no model prompt and
requires explicit confirmation before its evidence is accepted.

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

For an `ACTIVE_CANDIDATE`, the summary prints the authoritative published
baseline, the complete commit list, every changed file and its release domain,
the contract-evolution decision, artifact capability gates, and the
dependency/version diff. Full mode additionally runs the public-boundary check,
installer self-test, all locked tests, builds a candidate archive, verifies its
metadata, and prints its SHA-256.

For `POST_PUBLISH`, the same historical review snapshot is not rewritten or
reapplied as if it covered new bytes. The audit binds to the immutable published
baseline, reports the dependency/version delta, and full mode runs the local
regression/security checks but skips candidate-only artifact construction until
the manifest advances to a new release version.

Local audit complements GitHub CI and real-provider/draft-artifact evidence; it
does not grant merge, tag, or publish permission.
